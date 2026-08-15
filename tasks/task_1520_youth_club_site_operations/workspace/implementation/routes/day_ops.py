"""Routes: club days, attendance, program areas, rotation assignments,
transport routes and rides, meal claims, behavior incidents, funder reports,
and the logical clock."""

import math

from flask import Blueprint, request

import db
from clock_util import CLOCK
from errors import err
from middleware import authenticate, authorize
from response import success
from services import core, finance
from validators import get_body, reject_unknown, require_fields, parse_pagination, paginate

bp = Blueprint("day_ops", __name__)

ALL = ["PlatformAdmin", "SiteDirector", "FrontlineStaff", "StateAgencyReviewer", "FunderContact"]
DIRECTOR_OR_FRONT = ["SiteDirector", "FrontlineStaff"]
DIRECTOR_ONLY = ["SiteDirector"]


def _auth(allowed):
    role, user_id = authenticate()
    authorize(role, allowed)
    return role, user_id


def _list_response(records, filters):
    for key, value in filters.items():
        if value is not None:
            records = [r for r in records if r.get(key) == value]
    limit, offset = parse_pagination()
    page, meta = paginate(records, limit, offset)
    return success(page, 200, is_list=True, pagination=meta)


# ---------------------------------------------------------------------------
# Club days
# ---------------------------------------------------------------------------

@bp.post("/club-days")
def create_club_day():
    role, _ = _auth(DIRECTOR_ONLY)
    body = get_body()
    reject_unknown(body, {"site_id", "date"})
    vals = require_fields(body, {
        "site_id": {"type": "string", "required": True},
        "date": {"type": "string", "required": True, "date": True},
    })
    site = core.resolve_fk("sites", vals["site_id"])
    today = CLOCK.today()
    # Opening sweeps run against the logical date (PRD §3.4).
    core.suspension_sweep(site["id"], today)
    core.staff_lapse_sweep(site["id"])
    if vals["date"] != today:
        raise err("ERR_DAY_NOT_TODAY", "club-day date must equal logical today")
    for existing in db.find("club_days", site_id=site["id"]):
        if existing["date"] == vals["date"]:
            raise err("ERR_DUPLICATE_CLUB_DAY", "a club day already exists for this site and date")
    now = db.now_iso()
    day = {
        "id": db.new_id(),
        "site_id": site["id"],
        "date": vals["date"],
        "status": "OPEN",
        "present_count": 0,
        "signed_out_count": 0,
        "missing_signout_count": 0,
        "meal_counts": core.zeroed_meal_counts(),
        "posture": "NORMAL",
        "weekly_fees_accrued": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("club_days", day)
    return success(day, 201)


@bp.get("/club-days/<day_id>")
def read_club_day(day_id):
    _auth(ALL)
    day = core.require("club_days", day_id)
    return success(day, 200)


@bp.get("/sites/<site_id>/club-days")
def list_club_days(site_id):
    _auth(ALL)
    core.require("sites", site_id)
    records = db.find("club_days", site_id=site_id)
    month = request.args.get("month")
    filters = {"status": request.args.get("status")}
    for key, value in filters.items():
        if value is not None:
            records = [r for r in records if r.get(key) == value]
    if month is not None:
        records = [r for r in records if r["date"][:7] == month]
    limit, offset = parse_pagination()
    page, meta = paginate(records, limit, offset)
    return success(page, 200, is_list=True, pagination=meta)


@bp.post("/club-days/<day_id>/close")
def close_club_day(day_id):
    role, _ = _auth(DIRECTOR_ONLY)
    day = core.require("club_days", day_id)
    get_body(allow_empty=True)
    if day["status"] != "OPEN":
        raise err("ERR_CLUB_DAY_NOT_OPEN", "club day is not OPEN")
    # Close sweep: ON_SITE attendance -> MISSING_SIGNOUT.
    flipped = 0
    for rec in db.find("attendance", club_day_id=day["id"]):
        if rec["status"] == "ON_SITE":
            rec["status"] = "MISSING_SIGNOUT"
            db.touch(rec)
            flipped += 1
    day["present_count"] -= flipped
    day["missing_signout_count"] += flipped
    # Rotation assignments: SCHEDULED -> CANCELLED, CHECKED_IN -> COMPLETED.
    for ra in db.find("rotations", club_day_id=day["id"]):
        if ra["status"] == "SCHEDULED":
            ra["status"] = "CANCELLED"
            db.touch(ra)
        elif ra["status"] == "CHECKED_IN":
            ra["status"] = "COMPLETED"
            db.touch(ra)
    day["status"] = "CLOSED"
    site = db.get("sites", day["site_id"])
    finance.weekly_accrual(site, day)
    core.recompute_posture(day)
    db.touch(day)
    return success(day, 200)


@bp.post("/club-days/<day_id>/reconcile")
def reconcile_club_day(day_id):
    role, _ = _auth(DIRECTOR_ONLY)
    day = core.require("club_days", day_id)
    get_body(allow_empty=True)
    if day["status"] != "CLOSED":
        raise err("ERR_CLUB_DAY_NOT_CLOSED", "club day is not CLOSED")
    signed_out_by_tier = _tier_counts(day, statuses=("SIGNED_OUT",))
    for meal_type in core.MEAL_TYPES:
        counts = day["meal_counts"].get(meal_type, {})
        for tier in core.TIERS:
            if counts.get(tier, 0) > signed_out_by_tier.get(tier, 0):
                raise err("ERR_MEAL_COUNTS_EXCEED_ATTENDANCE",
                          "meal count for tier %s exceeds signed-out attendance of that tier" % tier)
    day["status"] = "RECONCILED"
    db.touch(day)
    return success(day, 200)


def _tier_counts(day, statuses):
    counts = {t: 0 for t in core.TIERS}
    for rec in db.find("attendance", club_day_id=day["id"]):
        if rec["status"] not in statuses:
            continue
        member = db.get("members", rec["member_id"])
        if member is None or member.get("eligibility_tier") is None:
            continue
        counts[member["eligibility_tier"]] += 1
    return counts


@bp.post("/club-days/<day_id>/meal-counts")
def upsert_meal_counts(day_id):
    role, _ = _auth(DIRECTOR_OR_FRONT)
    day = core.require("club_days", day_id)
    body = get_body()
    reject_unknown(body, {"meal_type", "free_count", "reduced_count", "paid_count"})
    vals = require_fields(body, {
        "meal_type": {"type": "string", "required": True, "enum": core.MEAL_TYPES},
        "free_count": {"type": "integer", "required": True, "nonnegative": True},
        "reduced_count": {"type": "integer", "required": True, "nonnegative": True},
        "paid_count": {"type": "integer", "required": True, "nonnegative": True},
    })
    if day["status"] == "RECONCILED":
        raise err("ERR_DAY_LOCKED", "meal counts are locked on a RECONCILED day")
    if day["status"] != "OPEN":
        raise err("ERR_CLUB_DAY_NOT_OPEN", "club day is not OPEN")
    eligible = _tier_counts(day, statuses=("ON_SITE", "SIGNED_OUT"))
    requested = {"FREE": vals["free_count"], "REDUCED": vals["reduced_count"], "PAID": vals["paid_count"]}
    for tier in core.TIERS:
        if requested[tier] > eligible.get(tier, 0):
            raise err("ERR_MEAL_COUNTS_EXCEED_ATTENDANCE",
                      "meal count for tier %s exceeds same-day eligible attendance" % tier)
    day["meal_counts"][vals["meal_type"]] = requested
    db.touch(day)
    return success(day, 200)


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

@bp.post("/attendance-records")
def sign_in():
    role, _ = _auth(DIRECTOR_OR_FRONT)
    body = get_body()
    reject_unknown(body, {"club_day_id", "member_id"})
    vals = require_fields(body, {
        "club_day_id": {"type": "string", "required": True},
        "member_id": {"type": "string", "required": True},
    })
    day = core.resolve_fk("club_days", vals["club_day_id"])
    member = core.resolve_fk("members", vals["member_id"])
    site = db.get("sites", day["site_id"])
    core.recompute_posture(day)
    if day["date"] != CLOCK.today():
        raise err("ERR_DAY_NOT_TODAY", "sign-in is only allowed on the day whose date equals logical today")
    if day["status"] != "OPEN":
        raise err("ERR_CLUB_DAY_NOT_OPEN", "club day is not OPEN")
    if member["status"] != "ACTIVE":
        raise err("ERR_MEMBER_NOT_ACTIVE", "sign-in requires an ACTIVE member")
    for rec in db.find("attendance", club_day_id=day["id"]):
        if rec["member_id"] == member["id"]:
            raise err("ERR_DUPLICATE_ATTENDANCE", "member already has an attendance record for this club day")
    if day["posture"] == "OVER_CAPACITY":
        raise err("ERR_OVER_CAPACITY", "club day is at capacity")
    if member["fee_balance_cents"] > site["max_arrears_cents"]:
        raise err("ERR_FEE_ARREARS_EXCEEDED", "fee balance exceeds the arrears limit")
    now = db.now_iso()
    rec = {
        "id": db.new_id(),
        "club_day_id": day["id"],
        "member_id": member["id"],
        "sign_in_at": now,
        "sign_out_at": None,
        "sign_out_type": None,
        "pickup_name": None,
        "status": "ON_SITE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("attendance", rec)
    day["present_count"] += 1
    core.recompute_posture(day)
    db.touch(day)
    return success(rec, 201)


@bp.post("/attendance-records/<rec_id>/sign-out")
def sign_out(rec_id):
    role, _ = _auth(DIRECTOR_OR_FRONT)
    rec = core.require("attendance", rec_id)
    body = get_body()
    reject_unknown(body, {"sign_out_type", "pickup_name"})
    vals = require_fields(body, {
        "sign_out_type": {"type": "string", "required": True,
                          "enum": ["AUTHORIZED_PICKUP", "WALKER", "BUS"]},
        "pickup_name": {"type": "string", "required": False, "allow_null": True},
    })
    if rec["status"] == "SIGNED_OUT":
        raise err("ERR_ALREADY_SIGNED_OUT", "attendance record is already SIGNED_OUT")
    if rec["status"] == "MISSING_SIGNOUT":
        raise err("ERR_ATTENDANCE_FINAL", "attendance record is final (MISSING_SIGNOUT)")
    day = db.get("club_days", rec["club_day_id"])
    member = db.get("members", rec["member_id"])
    st = vals["sign_out_type"]
    if st == "AUTHORIZED_PICKUP":
        pickup = vals.get("pickup_name")
        matched = False
        if pickup is not None:
            for g in db.find("guardians", member_id=member["id"]):
                if g["status"] == "ACTIVE" and g["full_name"] == pickup:
                    matched = True
                    break
        if not matched:
            raise err("ERR_PICKUP_NOT_AUTHORIZED",
                      "pickup_name does not case-sensitively match an ACTIVE guardian")
    elif st == "WALKER":
        if not member["walker_ok"]:
            raise err("ERR_WALKER_NOT_PERMITTED", "member may not sign out as WALKER")
    elif st == "BUS":
        if core.ride_covers(member["id"], day["date"]) is None:
            raise err("ERR_NO_RIDE_FOR_DATE", "no ACTIVE ride assignment covers the club day date")
    rec["sign_out_at"] = db.now_iso()
    rec["sign_out_type"] = st
    rec["pickup_name"] = vals.get("pickup_name") if st == "AUTHORIZED_PICKUP" else None
    rec["status"] = "SIGNED_OUT"
    db.touch(rec)
    day["present_count"] -= 1
    day["signed_out_count"] += 1
    core.recompute_posture(day)
    db.touch(day)
    return success(rec, 200)


@bp.get("/club-days/<day_id>/attendance-records")
def list_day_attendance(day_id):
    _auth(ALL)
    core.require("club_days", day_id)
    records = db.find("attendance", club_day_id=day_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


@bp.get("/members/<member_id>/attendance-records")
def list_member_attendance(member_id):
    _auth(ALL)
    core.require("members", member_id)
    records = db.find("attendance", member_id=member_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


# ---------------------------------------------------------------------------
# Program areas and rotation assignments
# ---------------------------------------------------------------------------

@bp.post("/program-areas")
def create_area():
    role, _ = _auth(["PlatformAdmin"])
    body = get_body()
    reject_unknown(body, {"site_id", "name", "capacity", "risk_tier", "ratio_override"})
    vals = require_fields(body, {
        "site_id": {"type": "string", "required": True},
        "name": {"type": "string", "required": True},
        "capacity": {"type": "integer", "required": True, "positive": True},
        "risk_tier": {"type": "string", "required": False, "enum": ["STANDARD", "ELEVATED"]},
        "ratio_override": {"type": "integer", "required": False, "positive": True, "allow_null": True},
    })
    core.resolve_fk("sites", vals["site_id"])
    now = db.now_iso()
    area = {
        "id": db.new_id(),
        "site_id": vals["site_id"],
        "name": vals["name"],
        "capacity": vals["capacity"],
        "risk_tier": vals.get("risk_tier") or "STANDARD",
        "ratio_override": vals.get("ratio_override"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("areas", area)
    return success(area, 201)


@bp.get("/program-areas/<area_id>")
def read_area(area_id):
    _auth(ALL)
    area = core.require("areas", area_id)
    return success(area, 200)


@bp.get("/sites/<site_id>/program-areas")
def list_areas(site_id):
    _auth(ALL)
    core.require("sites", site_id)
    records = db.find("areas", site_id=site_id)
    return _list_response(records, {})


@bp.get("/program-areas/<area_id>/rotation-assignments")
def list_area_rotations(area_id):
    _auth(ALL)
    core.require("areas", area_id)
    records = db.find("rotations", area_id=area_id)
    filters = {
        "club_day_id": request.args.get("club_day_id"),
        "block": request.args.get("block"),
        "status": request.args.get("status"),
    }
    return _list_response(records, filters)


def _check_staff_compliance(staff):
    if staff["status"] != "ACTIVE" or staff["compliance_status"] not in ("COMPLIANT", "EXPIRING"):
        raise err("ERR_STAFF_NOT_COMPLIANT",
                  "staff assignment requires an ACTIVE staffer with compliance COMPLIANT or EXPIRING")


@bp.post("/rotation-assignments")
def create_rotation():
    role, _ = _auth(DIRECTOR_OR_FRONT)
    body = get_body()
    reject_unknown(body, {"club_day_id", "area_id", "block", "kind", "member_id", "staff_id"})
    vals = require_fields(body, {
        "club_day_id": {"type": "string", "required": True},
        "area_id": {"type": "string", "required": True},
        "block": {"type": "string", "required": True, "enum": ["BLOCK_A", "BLOCK_B", "BLOCK_C"]},
        "kind": {"type": "string", "required": True, "enum": ["YOUTH", "STAFF"]},
        "member_id": {"type": "string", "required": False, "allow_null": True},
        "staff_id": {"type": "string", "required": False, "allow_null": True},
    })
    day = core.resolve_fk("club_days", vals["club_day_id"])
    area = core.resolve_fk("areas", vals["area_id"])
    # Stage 4 discipline: YOUTH requires member_id and forbids staff_id; STAFF the reverse.
    if vals["kind"] == "YOUTH":
        if not vals.get("member_id") or vals.get("staff_id"):
            raise err("ERR_VALIDATION", "kind=YOUTH requires member_id and forbids staff_id")
    else:
        if not vals.get("staff_id") or vals.get("member_id"):
            raise err("ERR_VALIDATION", "kind=STAFF requires staff_id and forbids member_id")
    member = None
    staff = None
    if vals["kind"] == "YOUTH":
        member = core.resolve_fk("members", vals["member_id"])
    else:
        staff = core.resolve_fk("staff", vals["staff_id"])
    # Referenced-entity state.
    if day["status"] != "OPEN":
        raise err("ERR_CLUB_DAY_NOT_OPEN", "rotation scheduling requires an OPEN club day")
    if vals["kind"] == "YOUTH":
        if member["status"] != "ACTIVE":
            raise err("ERR_MEMBER_NOT_ACTIVE", "youth rotation requires an ACTIVE member")
    else:
        _check_staff_compliance(staff)
    # One non-terminal assignment per member per (day, block).
    if vals["kind"] == "YOUTH":
        for ra in db.find("rotations", club_day_id=day["id"], member_id=member["id"]):
            if ra["block"] == vals["block"] and ra["status"] in ("SCHEDULED", "CHECKED_IN"):
                raise err("ERR_ASSIGNMENT_CONFLICT",
                          "member already has a non-terminal assignment for this club day and block")
    now = db.now_iso()
    ra = {
        "id": db.new_id(),
        "club_day_id": day["id"],
        "area_id": area["id"],
        "block": vals["block"],
        "kind": vals["kind"],
        "member_id": vals.get("member_id") if vals["kind"] == "YOUTH" else None,
        "staff_id": vals.get("staff_id") if vals["kind"] == "STAFF" else None,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("rotations", ra)
    return success(ra, 201)


def _validate_youth_capacity_then_ratio(day, area, block):
    """Pinned order: capacity first (ERR_AREA_CAPACITY_EXCEEDED), then ratio
    (ERR_RATIO_VIOLATION)."""
    site = db.get("sites", day["site_id"])
    youth_now, staff_now = core.checked_in_counts(day["id"], area["id"], block)
    youth_after = youth_now + 1
    if youth_after > area["capacity"]:
        raise err("ERR_AREA_CAPACITY_EXCEEDED", "area capacity would be exceeded for this block")
    ratio = core.effective_ratio(area, site)
    required_staff = math.ceil(youth_after / ratio)
    if required_staff > staff_now:
        raise err("ERR_RATIO_VIOLATION", "required staff exceeds checked-in staff for this block")


@bp.post("/rotation-assignments/<ra_id>/check-in")
def check_in_rotation(ra_id):
    role, _ = _auth(DIRECTOR_OR_FRONT)
    ra = core.require("rotations", ra_id)
    get_body(allow_empty=True)
    if ra["status"] != "SCHEDULED":
        raise err("ERR_ASSIGNMENT_NOT_CHECKABLE", "assignment is not SCHEDULED")
    day = db.get("club_days", ra["club_day_id"])
    if day["status"] != "OPEN":
        raise err("ERR_CLUB_DAY_NOT_OPEN", "club day is not OPEN")
    if ra["kind"] == "STAFF":
        staff = db.get("staff", ra["staff_id"])
        _check_staff_compliance(staff)
    else:
        area = db.get("areas", ra["area_id"])
        _validate_youth_capacity_then_ratio(day, area, ra["block"])
    ra["status"] = "CHECKED_IN"
    db.touch(ra)
    core.recompute_posture(day)
    db.touch(day)
    return success(ra, 200)


@bp.post("/rotation-assignments/<ra_id>/move")
def move_rotation(ra_id):
    role, _ = _auth(DIRECTOR_OR_FRONT)
    ra = core.require("rotations", ra_id)
    body = get_body()
    reject_unknown(body, {"new_area_id"})
    vals = require_fields(body, {
        "new_area_id": {"type": "string", "required": True},
    })
    new_area = core.resolve_fk("areas", vals["new_area_id"])
    if ra["status"] != "CHECKED_IN":
        raise err("ERR_ASSIGNMENT_NOT_MOVABLE", "assignment is not CHECKED_IN")
    day = db.get("club_days", ra["club_day_id"])
    if day["status"] != "OPEN":
        raise err("ERR_CLUB_DAY_NOT_OPEN", "club day is not OPEN")
    if ra["kind"] == "YOUTH":
        _validate_youth_capacity_then_ratio(day, new_area, ra["block"])
    ra["status"] = "MOVED"
    db.touch(ra)
    now = db.now_iso()
    successor = {
        "id": db.new_id(),
        "club_day_id": ra["club_day_id"],
        "area_id": new_area["id"],
        "block": ra["block"],
        "kind": ra["kind"],
        "member_id": ra["member_id"],
        "staff_id": ra["staff_id"],
        "status": "CHECKED_IN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("rotations", successor)
    core.recompute_posture(day)
    db.touch(day)
    return success(successor, 200)


@bp.get("/club-days/<day_id>/rotation-assignments")
def list_day_rotations(day_id):
    _auth(ALL)
    core.require("club_days", day_id)
    records = db.find("rotations", club_day_id=day_id)
    filters = {
        "area_id": request.args.get("area_id"),
        "block": request.args.get("block"),
        "kind": request.args.get("kind"),
        "status": request.args.get("status"),
    }
    return _list_response(records, filters)


@bp.get("/members/<member_id>/rotation-assignments")
def list_member_rotations(member_id):
    _auth(ALL)
    core.require("members", member_id)
    records = db.find("rotations", member_id=member_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


# ---------------------------------------------------------------------------
# Transport routes and ride assignments
# ---------------------------------------------------------------------------

@bp.post("/transport-routes")
def create_route():
    role, _ = _auth(["PlatformAdmin"])
    body = get_body()
    reject_unknown(body, {"site_id", "route_name", "school_name", "seat_capacity"})
    vals = require_fields(body, {
        "site_id": {"type": "string", "required": True},
        "route_name": {"type": "string", "required": True},
        "school_name": {"type": "string", "required": True},
        "seat_capacity": {"type": "integer", "required": True, "positive": True},
    })
    core.resolve_fk("sites", vals["site_id"])
    now = db.now_iso()
    route = {
        "id": db.new_id(),
        "site_id": vals["site_id"],
        "route_name": vals["route_name"],
        "school_name": vals["school_name"],
        "seat_capacity": vals["seat_capacity"],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("routes", route)
    return success(route, 201)


@bp.get("/transport-routes/<route_id>")
def read_route(route_id):
    _auth(ALL)
    route = core.require("routes", route_id)
    return success(route, 200)


@bp.get("/sites/<site_id>/transport-routes")
def list_routes(site_id):
    _auth(ALL)
    core.require("sites", site_id)
    records = db.find("routes", site_id=site_id)
    return _list_response(records, {})


@bp.get("/transport-routes/<route_id>/ride-assignments")
def list_route_rides(route_id):
    _auth(ALL)
    core.require("routes", route_id)
    records = db.find("rides", route_id=route_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; adjacency permitted."""
    return a_start < (b_end if b_end is not None else "9999-12-31") and \
           b_start < (a_end if a_end is not None else "9999-12-31")


@bp.post("/ride-assignments")
def create_ride():
    role, _ = _auth(DIRECTOR_ONLY)
    body = get_body()
    reject_unknown(body, {"route_id", "member_id", "effective_start_date", "effective_end_date"})
    vals = require_fields(body, {
        "route_id": {"type": "string", "required": True},
        "member_id": {"type": "string", "required": True},
        "effective_start_date": {"type": "string", "required": True, "date": True},
        "effective_end_date": {"type": "string", "required": False, "date": True, "allow_null": True},
    })
    route = core.resolve_fk("routes", vals["route_id"])
    member = core.resolve_fk("members", vals["member_id"])
    start = vals["effective_start_date"]
    end = vals.get("effective_end_date")
    if end is not None and end <= start:
        raise err("ERR_INVALID_DATE_WINDOW", "effective_end_date must be later than effective_start_date")
    if member["status"] != "ACTIVE":
        raise err("ERR_MEMBER_NOT_ACTIVE", "ride assignment requires an ACTIVE member")
    for other in db.find("rides", member_id=member["id"]):
        if other["status"] != "ACTIVE":
            continue
        if _windows_overlap(start, end, other["effective_start_date"], other.get("effective_end_date")):
            raise err("ERR_RIDE_WINDOW_OVERLAP", "window overlaps another ACTIVE ride of this member")
    # Aggregate seat occupancy on each existing club day inside the new window.
    for day in db.find("club_days", site_id=route["site_id"]):
        d = day["date"]
        if not (start <= d and (end is None or d < end)):
            continue
        occupancy = 0
        for ride in db.find("rides", route_id=route["id"]):
            if ride["status"] != "ACTIVE":
                continue
            if ride["effective_start_date"] <= d and (ride.get("effective_end_date") is None or d < ride["effective_end_date"]):
                occupancy += 1
        if occupancy + 1 > route["seat_capacity"]:
            raise err("ERR_SEAT_CAPACITY_EXCEEDED",
                      "route seat capacity would be exceeded on club day %s" % d)
    now = db.now_iso()
    ride = {
        "id": db.new_id(),
        "route_id": route["id"],
        "member_id": member["id"],
        "effective_start_date": start,
        "effective_end_date": end,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("rides", ride)
    return success(ride, 201)


@bp.post("/ride-assignments/<ride_id>/end")
def end_ride(ride_id):
    role, _ = _auth(DIRECTOR_ONLY)
    ride = core.require("rides", ride_id)
    body = get_body()
    reject_unknown(body, {"end_date"})
    vals = require_fields(body, {
        "end_date": {"type": "string", "required": True, "date": True},
    })
    if ride["status"] != "ACTIVE":
        raise err("ERR_RIDE_NOT_ACTIVE", "ride assignment is not ACTIVE")
    end_date = vals["end_date"]
    if end_date <= ride["effective_start_date"] or (
        ride.get("effective_end_date") is not None and end_date > ride["effective_end_date"]
    ):
        raise err("ERR_INVALID_DATE_WINDOW",
                  "end_date must be later than effective_start_date and no later than effective_end_date")
    ride["effective_end_date"] = end_date
    ride["status"] = "ENDED"
    db.touch(ride)
    return success(ride, 200)


@bp.get("/members/<member_id>/ride-assignments")
def list_member_rides(member_id):
    _auth(ALL)
    core.require("members", member_id)
    records = db.find("rides", member_id=member_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


# ---------------------------------------------------------------------------
# Meal claims
# ---------------------------------------------------------------------------

@bp.post("/meal-claims")
def create_claim():
    role, _ = _auth(DIRECTOR_ONLY)
    body = get_body()
    reject_unknown(body, {"site_id", "claim_month"})
    vals = require_fields(body, {
        "site_id": {"type": "string", "required": True},
        "claim_month": {"type": "string", "required": True, "month": True},
    })
    site = core.resolve_fk("sites", vals["site_id"])
    for existing in db.find("claims", site_id=site["id"]):
        if existing["claim_month"] == vals["claim_month"]:
            raise err("ERR_DUPLICATE_CLAIM_MONTH", "a meal claim already exists for this site and month")
    snapshot = finance.pin_rate_snapshot(site, vals["claim_month"])
    provisional = finance.compute_claim_total(snapshot, site["id"], vals["claim_month"],
                                              statuses=("CLOSED", "RECONCILED"))
    now = db.now_iso()
    claim = {
        "id": db.new_id(),
        "site_id": site["id"],
        "claim_month": vals["claim_month"],
        "status": "DRAFT",
        "rate_snapshot": snapshot,
        "provisional_total_cents": provisional,
        "final_total_cents": None,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("claims", claim)
    return success(claim, 201)


@bp.get("/sites/<site_id>/meal-claims")
def list_claims(site_id):
    _auth(ALL)
    core.require("sites", site_id)
    records = db.find("claims", site_id=site_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


@bp.post("/meal-claims/<claim_id>/submit")
def submit_claim(claim_id):
    role, user_id = _auth(DIRECTOR_ONLY)
    claim = core.require("claims", claim_id)
    get_body(allow_empty=True)
    if claim["status"] != "DRAFT":
        raise err("ERR_CLAIM_NOT_SUBMITTABLE", "claim is not in DRAFT")
    reconciled = [d for d in db.find("club_days", site_id=claim["site_id"])
                  if d["date"][:7] == claim["claim_month"] and d["status"] == "RECONCILED"]
    if not reconciled:
        raise err("ERR_CLAIM_NO_RECONCILED_DAYS", "no RECONCILED club days in the claim month")
    claim["final_total_cents"] = finance.compute_claim_total(
        claim["rate_snapshot"], claim["site_id"], claim["claim_month"], statuses=("RECONCILED",))
    claim["submitted_by_user_id"] = user_id
    claim["status"] = "SUBMITTED"
    db.touch(claim)
    return success(claim, 200)


@bp.post("/meal-claims/<claim_id>/approve")
def approve_claim(claim_id):
    role, user_id = _auth(["StateAgencyReviewer"])
    claim = core.require("claims", claim_id)
    get_body(allow_empty=True)
    if claim["status"] != "SUBMITTED":
        raise err("ERR_CLAIM_NOT_SUBMITTED", "claim is not SUBMITTED")
    if user_id == claim["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "approver must differ from submitter")
    claim["approved_by_user_id"] = user_id
    claim["status"] = "APPROVED"
    db.touch(claim)
    return success(claim, 200)


# ---------------------------------------------------------------------------
# Behavior incidents
# ---------------------------------------------------------------------------

@bp.post("/behavior-incidents")
def create_incident():
    role, _ = _auth(DIRECTOR_OR_FRONT)
    body = get_body()
    reject_unknown(body, {"member_id", "incident_date", "category", "description"})
    vals = require_fields(body, {
        "member_id": {"type": "string", "required": True},
        "incident_date": {"type": "string", "required": True, "date": True},
        "category": {"type": "string", "required": True, "enum": ["LEVEL_1", "LEVEL_2", "LEVEL_3"]},
        "description": {"type": "string", "required": False, "allow_null": True},
    })
    core.resolve_fk("members", vals["member_id"])
    now = db.now_iso()
    incident = {
        "id": db.new_id(),
        "member_id": vals["member_id"],
        "incident_date": vals["incident_date"],
        "category": vals["category"],
        "points": core.POINTS_BY_CATEGORY[vals["category"]],
        "description": vals.get("description"),
        "adjudication_status": "REPORTED",
        "suspension_status": "NONE",
        "suspension_start_date": None,
        "suspension_days": None,
        "adjudicated_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("incidents", incident)
    return success(incident, 201)


@bp.get("/members/<member_id>/behavior-incidents")
def list_incidents(member_id):
    _auth(ALL)
    core.require("members", member_id)
    records = db.find("incidents", member_id=member_id)
    return _list_response(records, {})


@bp.post("/behavior-incidents/<incident_id>/adjudicate")
def adjudicate_incident(incident_id):
    role, user_id = _auth(DIRECTOR_ONLY)
    incident = core.require("incidents", incident_id)
    body = get_body()
    reject_unknown(body, {"outcome", "suspension_days", "suspension_start_date"})
    vals = require_fields(body, {
        "outcome": {"type": "string", "required": True, "enum": ["SUSTAINED", "DISMISS"]},
        "suspension_days": {"type": "integer", "required": False, "allow_null": True},
        "suspension_start_date": {"type": "string", "required": False, "date": True, "allow_null": True},
    })
    days = vals.get("suspension_days")
    if days is not None and days <= 0:
        raise err("ERR_VALIDATION", "suspension_days must be positive when provided")
    if incident["adjudication_status"] != "REPORTED":
        raise err("ERR_INCIDENT_NOT_REPORTED", "incident is not in REPORTED")
    member = db.get("members", incident["member_id"])
    core.recompute_behavior_points(member)
    today = CLOCK.today()
    if vals["outcome"] == "DISMISS":
        incident["adjudication_status"] = "DISMISSED"
        incident["suspension_status"] = "NONE"
        incident["adjudicated_by_user_id"] = user_id
        db.touch(incident)
        core.recompute_behavior_points(member)
        db.touch(member)
        return success(incident, 200)
    # SUSTAINED
    if days is None:
        if member["discipline_watch"]:
            raise err("ERR_SUSPENSION_MANDATORY",
                      "suspension is mandatory while discipline_watch is true")
        incident["adjudication_status"] = "ADJUDICATED"
        incident["suspension_status"] = "NONE"
        incident["adjudicated_by_user_id"] = user_id
        db.touch(incident)
        core.recompute_behavior_points(member)
        db.touch(member)
        return success(incident, 200)
    start = vals.get("suspension_start_date")
    if start is None:
        raise err("ERR_VALIDATION", "suspension_start_date is required when suspension_days is provided")
    incident["adjudication_status"] = "ADJUDICATED"
    incident["suspension_days"] = days
    incident["suspension_start_date"] = start
    if start <= today:
        incident["suspension_status"] = "ACTIVE"
        if member["status"] == "ACTIVE":
            member["status"] = "SUSPENDED"
    else:
        incident["suspension_status"] = "IMPOSED"
    incident["adjudicated_by_user_id"] = user_id
    db.touch(incident)
    core.recompute_behavior_points(member)
    db.touch(member)
    return success(incident, 200)


@bp.post("/behavior-incidents/<incident_id>/appeal")
def appeal_incident(incident_id):
    role, _ = _auth(DIRECTOR_OR_FRONT)
    incident = core.require("incidents", incident_id)
    get_body(allow_empty=True)
    if incident["suspension_status"] != "ACTIVE":
        raise err("ERR_INCIDENT_NOT_APPEALABLE", "suspension is not ACTIVE")
    incident["suspension_status"] = "APPEALED"
    db.touch(incident)
    return success(incident, 200)


@bp.post("/behavior-incidents/<incident_id>/resolve-appeal")
def resolve_appeal(incident_id):
    role, user_id = _auth(DIRECTOR_ONLY)
    incident = core.require("incidents", incident_id)
    body = get_body()
    reject_unknown(body, {"decision"})
    vals = require_fields(body, {
        "decision": {"type": "string", "required": True, "enum": ["DENIED", "UPHELD"]},
    })
    if incident["suspension_status"] != "APPEALED":
        raise err("ERR_APPEAL_NOT_PENDING", "suspension is not APPEALED")
    if user_id == incident["adjudicated_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "resolver must differ from adjudicator")
    member = db.get("members", incident["member_id"])
    if vals["decision"] == "DENIED":
        incident["suspension_status"] = "ACTIVE"
        db.touch(incident)
        return success(incident, 200)
    incident["suspension_status"] = "RESCINDED"
    db.touch(incident)
    core.recompute_behavior_points(member)
    core.maybe_reinstate_member(member)
    db.touch(member)
    return success(incident, 200)


# ---------------------------------------------------------------------------
# Funder reports
# ---------------------------------------------------------------------------

@bp.post("/funder-reports")
def create_report():
    role, _ = _auth(DIRECTOR_ONLY)
    body = get_body()
    reject_unknown(body, {"site_id", "report_month", "funder_type"})
    vals = require_fields(body, {
        "site_id": {"type": "string", "required": True},
        "report_month": {"type": "string", "required": True, "month": True},
        "funder_type": {"type": "string", "required": True, "enum": ["UNITED_WAY", "STATE_GRANT"]},
    })
    site = core.resolve_fk("sites", vals["site_id"])
    for existing in db.find("reports", site_id=site["id"]):
        if existing["report_month"] == vals["report_month"]:
            raise err("ERR_DUPLICATE_REPORT_MONTH", "a funder report already exists for this site and month")
    metrics = finance.compute_report_metrics(site, vals["report_month"], vals["funder_type"])
    now = db.now_iso()
    report = {
        "id": db.new_id(),
        "site_id": site["id"],
        "report_month": vals["report_month"],
        "funder_type": vals["funder_type"],
        "status": "DRAFT",
        "operating_days": metrics["operating_days"],
        "member_days_attended": metrics["member_days_attended"],
        "member_days_enrolled": metrics["member_days_enrolled"],
        "average_daily_attendance": metrics["average_daily_attendance"],
        "attendance_rate_enrollment_basis": metrics["attendance_rate_enrollment_basis"],
        "attendance_rate_capacity_basis": metrics["attendance_rate_capacity_basis"],
        "headline_attendance_rate": metrics["headline_attendance_rate"],
        "meals_served_total": metrics["meals_served_total"],
        "incidents_total": metrics["incidents_total"],
        "submitted_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.insert("reports", report)
    return success(report, 201)


@bp.get("/sites/<site_id>/funder-reports")
def list_reports(site_id):
    _auth(ALL)
    core.require("sites", site_id)
    records = db.find("reports", site_id=site_id)
    filters = {"status": request.args.get("status")}
    return _list_response(records, filters)


@bp.post("/funder-reports/<report_id>/submit")
def submit_report(report_id):
    role, user_id = _auth(DIRECTOR_ONLY)
    report = core.require("reports", report_id)
    get_body(allow_empty=True)
    if report["status"] != "DRAFT":
        raise err("ERR_REPORT_NOT_SUBMITTABLE", "report is not in DRAFT")
    report["submitted_by_user_id"] = user_id
    report["status"] = "SUBMITTED"
    db.touch(report)
    return success(report, 200)


@bp.post("/funder-reports/<report_id>/accept")
def accept_report(report_id):
    role, user_id = _auth(["FunderContact"])
    report = core.require("reports", report_id)
    get_body(allow_empty=True)
    if report["status"] != "SUBMITTED":
        raise err("ERR_REPORT_NOT_SUBMITTED", "report is not SUBMITTED")
    if user_id == report["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "acceptor must differ from submitter")
    report["status"] = "ACCEPTED"
    db.touch(report)
    return success(report, 200)


# ---------------------------------------------------------------------------
# Logical clock (test-driving capability, PRD §2.4)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    role, _ = _auth(["PlatformAdmin"])
    body = get_body()
    reject_unknown(body, {"to_iso8601"})
    vals = require_fields(body, {
        "to_iso8601": {"type": "string", "required": True, "datetime": True},
    })
    new_dt = CLOCK.set(vals["to_iso8601"])
    return success({"current_utc": CLOCK.format(new_dt)}, 200)
