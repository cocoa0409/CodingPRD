"""Staff roster endpoints per PRD 3.1."""

from datetime import datetime, timedelta, timezone

from flask import request

from .auth import require
from .blueprint import bp
from .calc import allocate_week, monday_of
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, not_found
from .serialize import (
    ser_assignment,
    ser_call_in,
    ser_correction,
    ser_review,
    ser_staff,
)
from .store import STORE, new_entity, now, touch
from .util import (
    body,
    fmt_dt,
    opt_enum,
    opt_int,
    paged,
    pagination_params,
    req_enum,
    req_int,
    req_str,
    sort_created,
)

ROLE_CAPABILITIES = (
    "REPORTER",
    "PHOTOGRAPHER",
    "COPY_EDITOR",
    "FACT_CHECKER",
    "LEGAL_REVIEWER",
    "DESK_EDITOR",
    "MANAGING_EDITOR",
    "NEWS_DIRECTOR",
    "ANALYST",
)
HOME_DESKS = ("METRO", "BUSINESS", "SPORTS", "FEATURES")
EMPLOYMENT_STATUSES = ("ACTIVE", "ON_LEAVE", "INACTIVE")


def get_staff(sid):
    s = STORE.staff.get(sid)
    if s is None:
        not_found("ERR_STAFF_NOT_FOUND", "StaffMember")
    return s


@bp.post("/newsroom/staff")
def create_staff():
    require(["NewsDirector"])
    b = body()
    full_name = req_str(b, "full_name")
    role_capability = req_enum(b, "role_capability", ROLE_CAPABILITIES)
    home_desk = req_enum(b, "home_desk", HOME_DESKS)
    hourly_rate_cents = req_int(b, "hourly_rate_cents", minimum=0)
    max_concurrent = opt_int(b, "max_concurrent_assignments", 3, minimum=1)

    e = new_entity()
    e.update({
        "full_name": full_name,
        "role_capability": role_capability,
        "home_desk": home_desk,
        "employment_status": "ACTIVE",
        "max_concurrent_assignments": max_concurrent,
        "hourly_rate_cents": hourly_rate_cents,
        "active_assignment_count": 0,
    })
    STORE.staff[e["id"]] = e
    return ok_obj(ser_staff(e), 201)


@bp.get("/newsroom/staff")
def list_staff():
    require(["AssignmentEditor", "ManagingEditor", "NewsDirector"])
    items = list(STORE.staff.values())
    rc = request.args.get("role_capability")
    if rc:
        items = [s for s in items if s["role_capability"] == rc]
    es = request.args.get("employment_status")
    if es:
        items = [s for s in items if s["employment_status"] == es]
    hd = request.args.get("home_desk")
    if hd:
        items = [s for s in items if s["home_desk"] == hd]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_staff(s) for s in page], limit, offset, total)


@bp.get("/newsroom/staff/<sid>")
def read_staff(sid):
    require([
        "Reporter",
        "Photographer",
        "CopyEditor",
        "FactChecker",
        "LegalReviewer",
        "AssignmentEditor",
        "ManagingEditor",
        "NewsDirector",
        "AnalyticsProducer",
    ])
    return ok_obj(ser_staff(get_staff(sid)))


@bp.patch("/newsroom/staff/<sid>")
def patch_staff(sid):
    require(["NewsDirector"])
    s = get_staff(sid)
    b = body()
    if "employment_status" in b and b["employment_status"] is not None:
        s["employment_status"] = req_enum(b, "employment_status", EMPLOYMENT_STATUSES)
    if "max_concurrent_assignments" in b and b["max_concurrent_assignments"] is not None:
        s["max_concurrent_assignments"] = req_int(
            b, "max_concurrent_assignments", minimum=1
        )
    if "hourly_rate_cents" in b and b["hourly_rate_cents"] is not None:
        s["hourly_rate_cents"] = req_int(b, "hourly_rate_cents", minimum=0)
    touch(s)
    return ok_obj(ser_staff(s))


@bp.get("/newsroom/staff/<sid>/assignments")
def staff_assignments(sid):
    require(["AssignmentEditor", "ManagingEditor", "NewsDirector"])
    get_staff(sid)
    items = [a for a in STORE.assignments.values() if a["staff_id"] == sid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_assignment(a) for a in page], limit, offset, total)


def _parse_week_start(raw):
    """Parse an ISO date into a Monday 00:00:00Z datetime; ERR_VALIDATION otherwise."""
    if not isinstance(raw, str) or not raw.strip():
        bad_request("week_start must be an ISO date (YYYY-MM-DD) naming a Monday")
    s = raw.strip()
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        bad_request("week_start must be an ISO date (YYYY-MM-DD) naming a Monday")
    dt = d.replace(tzinfo=timezone.utc)
    if dt.weekday() != 0:
        bad_request("week_start must name a Monday")
    return dt


@bp.get("/newsroom/staff/<sid>/payroll")
def staff_payroll(sid):
    require(["ManagingEditor", "NewsDirector"])
    staff = get_staff(sid)
    raw = request.args.get("week_start")
    if raw is None:
        week_start = monday_of(now())
    else:
        week_start = _parse_week_start(raw)
    rows = allocate_week(staff["id"], week_start)
    assignment_count = len(rows)
    regular_minutes = sum(r[1] for r in rows)
    overtime_minutes = sum(r[2] for r in rows)
    total_cents = sum(r[3] for r in rows)
    return ok_obj({
        "week_start": week_start.strftime("%Y-%m-%d"),
        "assignment_count": assignment_count,
        "regular_minutes": regular_minutes,
        "overtime_minutes": overtime_minutes,
        "total_cents": total_cents,
    })


@bp.get("/newsroom/staff/<sid>/reviews")
def staff_reviews(sid):
    require(["AssignmentEditor", "ManagingEditor", "NewsDirector"])
    get_staff(sid)
    items = [r for r in STORE.reviews.values() if r["reviewer_staff_id"] == sid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_review(r) for r in page], limit, offset, total)


@bp.get("/newsroom/staff/<sid>/corrections")
def staff_corrections(sid):
    require(["ManagingEditor", "NewsDirector"])
    get_staff(sid)
    items = [
        c
        for c in STORE.corrections.values()
        if c["proposer_staff_id"] == sid or c.get("approver_staff_id") == sid
    ]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_correction(c) for c in page], limit, offset, total)


@bp.get("/newsroom/staff/<sid>/call-ins")
def staff_call_ins(sid):
    require(["NewsDirector"])
    get_staff(sid)
    items = [c for c in STORE.call_ins.values() if c["staff_id"] == sid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_call_in(c) for c in page], limit, offset, total)
