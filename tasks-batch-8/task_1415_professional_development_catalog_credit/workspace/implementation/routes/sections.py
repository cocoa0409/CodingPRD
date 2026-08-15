"""Sections, meetings, and bulk meeting attendance."""
from datetime import timedelta
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_MEETING_OUTSIDE_SECTION, ERR_ROOM_CONFLICT, \
    ERR_CAPACITY_BELOW_REGISTERED, ERR_NOT_RESOURCE_OWNER
from serializers import ser_section, ser_meeting, ser_attendance, \
    section_seats_registered
from services import promotion_sweep
from validate import req_str, req_int, opt_int, req_datetime, opt_datetime, \
    opt_str

bp = Blueprint("sections", __name__)

TURNOVER = timedelta(minutes=30)


def get_section_or_404(sid):
    s = store.sections.get(sid)
    if s is None:
        raise err(ERR_NOT_FOUND, "section not found")
    return s


def get_meeting_or_404(mid):
    m = store.meetings.get(mid)
    if m is None:
        raise err(ERR_NOT_FOUND, "meeting not found")
    return m


@bp.post("/pd/sections")
def create_section():
    require_role("PDCoordinator")
    body = get_body()
    course_id = req_str(body, "course_id")
    term = req_str(body, "term")
    instructor_id = req_str(body, "instructor_id")
    building_id = req_str(body, "building_id")
    room = req_str(body, "room")
    capacity = req_int(body, "seat_capacity", minimum=1)
    starts = req_datetime(body, "starts_at")
    ends = req_datetime(body, "ends_at")
    opens = req_datetime(body, "registration_opens_at")
    closes = req_datetime(body, "registration_closes_at")
    fee = opt_int(body, "fee_cents", minimum=0)
    if not (ends > starts):
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    course = store.courses.get(course_id)
    if course is None:
        raise err(ERR_NOT_FOUND, "course_id not found")
    if instructor_id not in store.employees:
        raise err(ERR_NOT_FOUND, "instructor_id not found")
    if building_id not in store.buildings:
        raise err(ERR_NOT_FOUND, "building_id not found")
    if fee is None:
        fee = course["fee_cents"]
    s = new_resource()
    s.update({
        "course_id": course_id,
        "term": term,
        "instructor_id": instructor_id,
        "building_id": building_id,
        "room": room,
        "seat_capacity": capacity,
        "fee_cents": fee,
        "starts_at": starts,
        "ends_at": ends,
        "registration_opens_at": opens,
        "registration_closes_at": closes,
        "status": "DRAFT",
    })
    store.sections[s["id"]] = s
    return ok(ser_section(s), 201)


@bp.get("/pd/sections/<sid>")
def get_section(sid):
    require_any_role()
    return ok(ser_section(get_section_or_404(sid)), 200)


@bp.get("/pd/sections")
def list_sections():
    require_any_role()
    items = store.sections.values()
    for key in ("course_id", "instructor_id", "building_id", "term", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [s for s in items if s[key] == v]
    return paginate([ser_section(s) for s in sort_by_created(items)])


@bp.post("/pd/sections/<sid>/publish")
def publish_section(sid):
    require_role("PDCoordinator")
    get_body()
    s = get_section_or_404(sid)
    if s["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "only a DRAFT section can be published")
    course = store.courses.get(s["course_id"])
    if course is None or course["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "course is not ACTIVE")
    has_meeting = any(m["section_id"] == s["id"]
                      for m in store.meetings.values())
    if not has_meeting:
        raise err(ERR_INVALID_STATE, "section has no meetings")
    if not (s["registration_opens_at"] <= s["registration_closes_at"]
            <= s["starts_at"] < s["ends_at"]):
        raise err(ERR_INVALID_STATE, "section window is not coherent")
    s["status"] = "PUBLISHED"
    touch(s)
    return ok(ser_section(s), 200)


@bp.patch("/pd/sections/<sid>")
def patch_section(sid):
    require_role("PDCoordinator")
    s = get_section_or_404(sid)
    body = get_body()
    # shape (step 4)
    new_cap = opt_int(body, "seat_capacity", minimum=1)
    new_room = opt_str(body, "room")
    new_starts = opt_datetime(body, "starts_at")
    new_ends = opt_datetime(body, "ends_at")
    eff_starts = new_starts if new_starts is not None else s["starts_at"]
    eff_ends = new_ends if new_ends is not None else s["ends_at"]
    if not (eff_ends > eff_starts):
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    # state (step 6)
    if s["status"] != "PUBLISHED":
        raise err(ERR_INVALID_STATE, "only a PUBLISHED section can be edited")
    # domain (step 10)
    if new_cap is not None and new_cap < section_seats_registered(s):
        raise err(ERR_CAPACITY_BELOW_REGISTERED,
                  "seat_capacity below current seats_registered")
    old_cap = s["seat_capacity"]
    if new_cap is not None:
        s["seat_capacity"] = new_cap
    if new_room is not None:
        s["room"] = new_room
    if new_starts is not None:
        s["starts_at"] = new_starts
    if new_ends is not None:
        s["ends_at"] = new_ends
    touch(s)
    if new_cap is not None and new_cap > old_cap:
        promotion_sweep(s)
    return ok(ser_section(s), 200)


@bp.post("/pd/sections/<sid>/cancel")
def cancel_section(sid):
    require_role("PDCoordinator")
    get_body()
    s = get_section_or_404(sid)
    if s["status"] not in ("DRAFT", "PUBLISHED", "REGISTRATION_CLOSED"):
        raise err(ERR_INVALID_STATE, "section cannot be canceled from this state")
    s["status"] = "CANCELED"
    touch(s)
    regs = [r for r in store.registrations.values()
            if r["section_id"] == s["id"]]
    regs.sort(key=lambda r: r["_seq"])
    for r in regs:
        if r["status"] == "REGISTERED":
            # release encumbrance; no promotion sweep (terminal section)
            if r["encumbered_cents"] > 0:
                from services import find_budget
                from db import fiscal_year
                emp = store.employees.get(r["teacher_id"])
                if emp is not None:
                    budget = find_budget(emp["primary_building_id"],
                                         fiscal_year(s["starts_at"]))
                    if budget is not None:
                        budget["encumbered_cents"] -= r["encumbered_cents"]
                        touch(budget)
                r["encumbered_cents"] = 0
            r["status"] = "DROPPED"
            touch(r)
        elif r["status"] == "WAITLISTED":
            r["status"] = "EXPIRED"
            touch(r)
    return ok(ser_section(s), 200)


@bp.post("/pd/sections/<sid>/meetings")
def create_meeting(sid):
    require_role("PDCoordinator")
    s = get_section_or_404(sid)
    body = get_body()
    starts = req_datetime(body, "starts_at")
    ends = req_datetime(body, "ends_at")
    room = req_str(body, "room")
    if not (ends > starts):
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    if s["status"] not in ("DRAFT", "PUBLISHED"):
        raise err(ERR_INVALID_STATE,
                  "meetings can only be added to DRAFT or PUBLISHED sections")
    if not (starts >= s["starts_at"] and ends <= s["ends_at"]):
        raise err(ERR_MEETING_OUTSIDE_SECTION,
                  "meeting interval must be contained in the section window")
    for m in store.meetings.values():
        if m["room"] != room:
            continue
        # 30-minute turnover gap: ok iff ends+30m <= m.starts or m.ends+30m <= starts
        if not (ends + TURNOVER <= m["starts_at"]
                or m["ends_at"] + TURNOVER <= starts):
            raise err(ERR_ROOM_CONFLICT,
                      "meeting violates the 30-minute room turnover buffer")
    m = new_resource()
    m.update({"section_id": s["id"], "starts_at": starts, "ends_at": ends,
              "room": room})
    store.meetings[m["id"]] = m
    return ok(ser_meeting(m), 201)


@bp.get("/pd/sections/<sid>/meetings")
def list_meetings(sid):
    require_any_role()
    s = get_section_or_404(sid)
    items = [m for m in store.meetings.values() if m["section_id"] == s["id"]]
    return paginate([ser_meeting(m) for m in sort_by_created(items)])


@bp.get("/pd/meetings/<mid>")
def get_meeting(mid):
    require_any_role()
    return ok(ser_meeting(get_meeting_or_404(mid)), 200)


@bp.post("/pd/meetings/<mid>/attendance")
def record_attendance(mid):
    ctx = require_role("Instructor", "PDCoordinator")
    m = get_meeting_or_404(mid)
    body = get_body()
    records = body.get("records")
    if not isinstance(records, list):
        raise err(ERR_INVALID_REQUEST, "records must be an array")
    # shape (step 4), FK (step 5) — validate everything before any write
    validated = []
    for item in records:
        if not isinstance(item, dict):
            raise err(ERR_INVALID_REQUEST, "each record must be an object")
        reg_id = item.get("registration_id")
        mark = item.get("mark")
        if not isinstance(reg_id, str) or not reg_id:
            raise err(ERR_INVALID_REQUEST, "record.registration_id required")
        if mark not in ("PRESENT", "ABSENT", "EXCUSED"):
            raise err(ERR_INVALID_REQUEST, "record.mark invalid")
        reg = store.registrations.get(reg_id)
        if reg is None:
            raise err(ERR_NOT_FOUND, "registration not found")
        if reg["section_id"] != m["section_id"]:
            raise err(ERR_INVALID_REQUEST,
                      "registration does not belong to this meeting's section")
        validated.append((reg, mark))
    # ownership (step 8): instructor of record only
    section = store.sections.get(m["section_id"])
    if ctx.role == "Instructor" and section["instructor_id"] != ctx.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the section's instructor")
    for reg, mark in validated:
        key = (reg["id"], m["id"])
        existing_id = store.attendance_by_pair.get(key)
        if existing_id is not None:
            rec = store.attendance[existing_id]
            rec["mark"] = mark
            rec["recorded_by_user_id"] = ctx.user_id
            touch(rec)
        else:
            rec = new_resource()
            rec.update({
                "registration_id": reg["id"],
                "meeting_id": m["id"],
                "mark": mark,
                "recorded_by_user_id": ctx.user_id,
            })
            store.attendance[rec["id"]] = rec
            store.attendance_by_pair[key] = rec["id"]
    return ok({"recorded_count": len(validated)}, 200)


@bp.get("/pd/meetings/<mid>/attendance")
def list_meeting_attendance(mid):
    require_any_role()
    m = get_meeting_or_404(mid)
    items = [a for a in store.attendance.values() if a["meeting_id"] == m["id"]]
    return paginate([ser_attendance(a) for a in sort_by_created(items)])
