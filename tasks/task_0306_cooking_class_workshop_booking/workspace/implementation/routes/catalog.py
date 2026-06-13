"""Instructors, Members, Templates, Series, and the test-driving clock."""
from flask import Blueprint

import db
from errors import err
from helpers import (
    get_json_body, require_fields, require_string, require_int, require_enum,
    optional_enum, stamp_create, touch, serialize, get_pagination, paginate,
    sort_by_created, parse_dt,
)
from lookups import get_instructor, get_member, get_template, get_series
from middleware import authenticate, require_role
from response import success, list_success
from services import calc, engine
from datetime import timedelta

bp = Blueprint("catalog", __name__)

SKILL_LEVELS = {"BEGINNER", "INTERMEDIATE", "ADVANCED", "PROFESSIONAL"}
CADENCES = {"WEEKLY", "BIWEEKLY", "MONTHLY"}
CADENCE_DAYS = {"WEEKLY": 7, "BIWEEKLY": 14, "MONTHLY": 28}


# ============================ Instructors ============================
@bp.route("/culinary/instructors", methods=["POST"])
def create_instructor():
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    body = get_json_body()
    require_fields(body, ["full_name", "email", "max_skill_level"])
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    max_skill = require_enum(body, "max_skill_level", SKILL_LEVELS)
    for ins in db.instructors.values():
        if ins["email"] == email:
            raise err("ERR_INVALID_REQUEST", "Instructor email already exists")
    obj = {
        "full_name": full_name,
        "email": email,
        "max_skill_level": max_skill,
        "status": "ACTIVE",
    }
    stamp_create(obj)
    db.instructors[obj["id"]] = obj
    return success(serialize(obj), status=201)


@bp.route("/culinary/instructors/<rid>", methods=["GET"])
def get_instructor_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor"])
    obj = get_instructor(rid)
    return success(serialize(obj))


# ============================ Members ============================
@bp.route("/culinary/members", methods=["POST"])
def create_member():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    body = get_json_body()
    require_fields(body, ["full_name", "email"])
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    dietary = body.get("dietary_flags", [])
    if dietary is None:
        dietary = []
    if not isinstance(dietary, list) or not all(isinstance(x, str) for x in dietary):
        raise err("ERR_INVALID_REQUEST", "dietary_flags must be an array of strings")
    for m in db.members.values():
        if m["email"] == email:
            raise err("ERR_INVALID_REQUEST", "Member email already exists")
    obj = {
        "full_name": full_name,
        "email": email,
        "dietary_flags": list(dietary),
        "wallet_credit_cents": 0,
        "no_show_count": 0,
        "late_cancel_count": 0,
        "reliability_score": 100,
        "booking_status": "GOOD_STANDING",
    }
    stamp_create(obj)
    db.members[obj["id"]] = obj
    return success(serialize(obj), status=201)


@bp.route("/culinary/members/<rid>", methods=["GET"])
def get_member_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    obj = get_member(rid)
    # PROVISIONAL reliability recompute on read (settled strikes only)
    calc.recompute_reliability(obj)
    return success(serialize(obj))


@bp.route("/culinary/members/<rid>/no-show-records", methods=["GET"])
def list_member_no_show(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    get_member(rid)
    rows = [r for r in db.no_show_records.values() if r["member_id"] == rid]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/culinary/members/<rid>/wallet/adjustments", methods=["POST"])
def wallet_adjustment(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    member = get_member(rid)
    body = get_json_body()
    require_fields(body, ["amount_cents"])
    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise err("ERR_INVALID_REQUEST", "amount_cents must be an integer")
    new_balance = member["wallet_credit_cents"] + amount
    if new_balance < 0:
        raise err("ERR_INVALID_WALLET_ADJUSTMENT", "Adjustment would drive wallet below zero")
    member["wallet_credit_cents"] = new_balance
    touch(member)
    return success(serialize(member))


# ============================ Templates ============================
@bp.route("/culinary/templates", methods=["POST"])
def create_template():
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    body = get_json_body()
    require_fields(body, [
        "title", "skill_level", "base_price_cents", "default_capacity",
        "station_fixed_cost_cents", "prep_minutes", "cleanup_minutes",
    ])
    obj = {
        "title": require_string(body, "title"),
        "skill_level": require_enum(body, "skill_level", SKILL_LEVELS),
        "base_price_cents": require_int(body, "base_price_cents", minimum=0),
        "default_capacity": require_int(body, "default_capacity", minimum=1, maximum=40),
        "station_fixed_cost_cents": require_int(body, "station_fixed_cost_cents", minimum=0),
        "prep_minutes": require_int(body, "prep_minutes", minimum=0, maximum=480),
        "cleanup_minutes": require_int(body, "cleanup_minutes", minimum=0, maximum=240),
        "status": "DRAFT",
    }
    stamp_create(obj)
    db.templates[obj["id"]] = obj
    return success(serialize(obj), status=201)


@bp.route("/culinary/templates/<rid>/publish", methods=["POST"])
def publish_template(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    tmpl = get_template(rid)
    if tmpl["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Template not in DRAFT")
    tmpl["status"] = "PUBLISHED"
    touch(tmpl)
    return success(serialize(tmpl))


@bp.route("/culinary/templates/<rid>", methods=["GET"])
def get_template_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    return success(serialize(get_template(rid)))


# ============================ Series ============================
@bp.route("/culinary/series", methods=["POST"])
def create_series():
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    body = get_json_body()
    require_fields(body, ["template_id", "instructor_id", "cadence", "occurrence_count", "first_start_at"])
    template_id = require_string(body, "template_id")
    instructor_id = require_string(body, "instructor_id")
    cadence = require_enum(body, "cadence", CADENCES)
    occurrence_count = require_int(body, "occurrence_count", minimum=1, maximum=52)
    first_start_at_dt = parse_dt(body.get("first_start_at"), "first_start_at")
    # existence of referenced resources (ERR_NOT_FOUND)
    get_template(template_id)
    get_instructor(instructor_id)
    obj = {
        "template_id": template_id,
        "instructor_id": instructor_id,
        "cadence": cadence,
        "occurrence_count": occurrence_count,
        "first_start_at": body.get("first_start_at"),
        "status": "DRAFT",
        "active_session_count": 0,
        "_first_start_at_dt": first_start_at_dt,
    }
    stamp_create(obj)
    db.series[obj["id"]] = obj
    return success(serialize(obj), status=201)


@bp.route("/culinary/series/<rid>/publish", methods=["POST"])
def publish_series(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    ser = get_series(rid)
    if ser["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Series not in DRAFT")
    tmpl = db.templates.get(ser["template_id"])
    instr = db.instructors.get(ser["instructor_id"])
    if tmpl is None or instr is None:
        raise err("ERR_NOT_FOUND", "Referenced template or instructor missing")
    # preconditions evaluated via the skill business-safety check (priority 10)
    if tmpl["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Template is not PUBLISHED")
    if instr["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Instructor is not ACTIVE")
    if not calc.skill_at_least(instr["max_skill_level"], tmpl["skill_level"]):
        raise err("ERR_INSTRUCTOR_SKILL_INSUFFICIENT", "Instructor skill below template level")
    # spawn sessions
    interval = timedelta(days=CADENCE_DAYS[ser["cadence"]])
    first_dt = ser["_first_start_at_dt"]
    for k in range(ser["occurrence_count"]):
        start_dt = first_dt + interval * k
        sess = {
            "template_id": ser["template_id"],
            "series_id": ser["id"],
            "instructor_id": ser["instructor_id"],
            "station_id": None,
            "event_type": "GROUP",
            "start_at": _iso_z(start_dt),
            "end_at": None,
            "planned_seats": tmpl["default_capacity"],
            "confirmed_seats": 0,
            "private_event_fee_cents": 0,
            "prep_cost_per_seat_cents": 0,
            "status": "SCHEDULED",
            "_start_at_dt": start_dt,
            "_end_at_dt": None,
        }
        stamp_create(sess)
        db.sessions[sess["id"]] = sess
    ser["status"] = "PUBLISHED"
    ser["active_session_count"] = ser["occurrence_count"]
    touch(ser)
    return success(serialize(ser))


@bp.route("/culinary/series/<rid>/cancel", methods=["POST"])
def cancel_series(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    ser = get_series(rid)
    if ser["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Series not in PUBLISHED")
    children = [s for s in db.sessions.values() if s.get("series_id") == ser["id"]]
    for sess in children:
        if sess["status"] not in ("COMPLETED", "CANCELLED"):
            engine.cancel_session(sess)
    ser["status"] = "CANCELLED"
    ser["active_session_count"] = 0
    touch(ser)
    return success(serialize(ser))


@bp.route("/culinary/series/<rid>", methods=["GET"])
def get_series_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    return success(serialize(get_series(rid)))


@bp.route("/culinary/series", methods=["GET"])
def list_series():
    from flask import request
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    rows = list(db.series.values())
    tid = request.args.get("template_id")
    iid = request.args.get("instructor_id")
    st = request.args.get("status")
    if tid is not None:
        rows = [r for r in rows if r["template_id"] == tid]
    if iid is not None:
        rows = [r for r in rows if r["instructor_id"] == iid]
    if st is not None:
        rows = [r for r in rows if r["status"] == st]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/culinary/series/<rid>/sessions", methods=["GET"])
def list_series_sessions(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    get_series(rid)
    rows = [s for s in db.sessions.values() if s.get("series_id") == rid]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(s) for s in page], limit, offset, total)


# ============================ Clock ============================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body.get("to_iso8601"), "to_iso8601")
    db.set_clock(dt)
    return success({"current_utc": _iso_z(dt)})


def _iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
