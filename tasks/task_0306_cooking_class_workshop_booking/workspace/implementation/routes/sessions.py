"""ClassSession lifecycle and IngredientLine routes."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (
    get_json_body, require_fields, require_string, require_int, require_number,
    require_enum, optional_enum, stamp_create, touch, serialize, get_pagination,
    paginate, sort_by_created, parse_dt,
)
from lookups import get_template, get_instructor, get_session, require_session_owner
from middleware import authenticate, require_role
from response import success, list_success
from services import calc, engine

bp = Blueprint("sessions", __name__)

EVENT_TYPES = {"GROUP", "PRIVATE"}
DIETARY_TAGS = {"NEUTRAL", "CONTAINS_GLUTEN", "CONTAINS_NUT", "CONTAINS_DAIRY", "ANIMAL_PRODUCT"}
OCCUPIED_STATUSES = {"SCHEDULED", "OPEN", "FULL", "LOCKED"}


def _iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ============================ ClassSession ============================
@bp.route("/culinary/sessions", methods=["POST"])
def create_session():
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    body = get_json_body()
    require_fields(body, ["template_id", "instructor_id", "station_id", "event_type",
                          "start_at", "end_at", "planned_seats"])
    template_id = require_string(body, "template_id")
    instructor_id = require_string(body, "instructor_id")
    station_id = require_string(body, "station_id")
    event_type = require_enum(body, "event_type", EVENT_TYPES)
    start_dt = parse_dt(body.get("start_at"), "start_at")
    end_dt = parse_dt(body.get("end_at"), "end_at")
    planned_seats = require_int(body, "planned_seats", minimum=1, maximum=40)
    private_fee = body.get("private_event_fee_cents", 0)
    if private_fee is None:
        private_fee = 0
    if isinstance(private_fee, bool) or not isinstance(private_fee, int) or private_fee < 0:
        raise err("ERR_INVALID_REQUEST", "private_event_fee_cents must be a non-negative integer")
    series_id = body.get("series_id")
    # existence (left-to-right: template then instructor)
    tmpl = get_template(template_id)
    instr = get_instructor(instructor_id)
    if series_id is not None:
        if series_id not in db.series:
            raise err("ERR_NOT_FOUND", "Series not found")
    # business safety: skill (priority 10) before time window (priority 23)
    if not calc.skill_at_least(instr["max_skill_level"], tmpl["skill_level"]):
        raise err("ERR_INSTRUCTOR_SKILL_INSUFFICIENT", "Instructor skill below template level")
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_TIME_WINDOW", "end_at must be strictly after start_at")
    obj = {
        "template_id": template_id,
        "series_id": series_id,
        "instructor_id": instructor_id,
        "station_id": station_id,
        "event_type": event_type,
        "start_at": body.get("start_at"),
        "end_at": body.get("end_at"),
        "planned_seats": planned_seats,
        "confirmed_seats": 0,
        "private_event_fee_cents": private_fee,
        "prep_cost_per_seat_cents": 0,
        "status": "SCHEDULED",
        "_start_at_dt": start_dt,
        "_end_at_dt": end_dt,
    }
    stamp_create(obj)
    db.sessions[obj["id"]] = obj
    return success(serialize(obj), status=201)


@bp.route("/culinary/sessions/<rid>", methods=["GET"])
def get_session_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    return success(serialize(get_session(rid)))


@bp.route("/culinary/sessions", methods=["GET"])
def list_sessions():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    rows = list(db.sessions.values())
    for key in ("template_id", "series_id", "instructor_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/culinary/sessions/<rid>/open", methods=["POST"])
def open_session(rid):
    p = authenticate()
    require_role(p, ["Instructor"])
    sess = get_session(rid)
    require_session_owner(p, sess)
    if sess["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Session not in SCHEDULED")
    lines = [il for il in db.ingredient_lines.values() if il["session_id"] == sess["id"]]
    if len(lines) < 1:
        raise err("ERR_INVALID_STATE", "Session has no ingredient lines")
    # station temporal-overlap check (priority 22)
    _check_station_overlap(sess)
    calc.refresh_prep_cost(sess)
    sess["status"] = "OPEN"
    touch(sess)
    return success(serialize(sess))


def _occupation_interval(sess):
    tmpl = db.templates[sess["template_id"]]
    from datetime import timedelta
    start = sess["_start_at_dt"] - timedelta(minutes=tmpl["prep_minutes"])
    end = sess["_end_at_dt"] + timedelta(minutes=tmpl["cleanup_minutes"])
    return start, end


def _check_station_overlap(sess):
    a_start, a_end = _occupation_interval(sess)
    for other in db.sessions.values():
        if other["id"] == sess["id"]:
            continue
        if other.get("station_id") != sess.get("station_id"):
            continue
        if other["status"] not in OCCUPIED_STATUSES:
            continue
        if other.get("_end_at_dt") is None or other.get("_start_at_dt") is None:
            continue
        b_start, b_end = _occupation_interval(other)
        # half-open overlap: a_start < b_end and b_start < a_end
        if a_start < b_end and b_start < a_end:
            raise err("ERR_STATION_DOUBLE_BOOKED", "Station occupation overlaps another session")


@bp.route("/culinary/sessions/<rid>/lock", methods=["POST"])
def lock_session(rid):
    p = authenticate()
    require_role(p, ["Instructor"])
    sess = get_session(rid)
    require_session_owner(p, sess)
    if sess["status"] not in ("OPEN", "FULL"):
        raise err("ERR_INVALID_STATE", "Session not in OPEN or FULL")
    sess["status"] = "LOCKED"
    touch(sess)
    return success(serialize(sess))


@bp.route("/culinary/sessions/<rid>/complete", methods=["POST"])
def complete_session_route(rid):
    p = authenticate()
    require_role(p, ["Instructor"])
    sess = get_session(rid)
    require_session_owner(p, sess)
    if sess["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Session not in LOCKED")
    engine.complete_session(sess)
    return success(serialize(sess))


@bp.route("/culinary/sessions/<rid>/cancel", methods=["POST"])
def cancel_session_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    sess = get_session(rid)
    if sess["status"] not in ("SCHEDULED", "OPEN", "FULL", "LOCKED"):
        raise err("ERR_INVALID_STATE", "Session not in a cancellable state")
    engine.cancel_session(sess)
    return success(serialize(sess))


# ============================ IngredientLine ============================
@bp.route("/culinary/sessions/<rid>/ingredient-lines", methods=["POST"])
def add_ingredient_line(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor"])
    sess = get_session(rid)
    require_session_owner(p, sess)
    body = get_json_body()
    require_fields(body, ["name", "qty_per_seat", "unit_cost_cents"])
    name = require_string(body, "name")
    qty = require_number(body, "qty_per_seat", minimum=0)
    unit_cost = require_int(body, "unit_cost_cents", minimum=0)
    dietary_tag = optional_enum(body, "dietary_tag", DIETARY_TAGS, "NEUTRAL")
    obj = {
        "session_id": sess["id"],
        "name": name,
        "qty_per_seat": qty,
        "unit_cost_cents": unit_cost,
        "dietary_tag": dietary_tag,
    }
    stamp_create(obj)
    db.ingredient_lines[obj["id"]] = obj
    calc.refresh_prep_cost(sess)
    touch(sess)
    return success(serialize(obj), status=201)


@bp.route("/culinary/sessions/<rid>/ingredient-lines", methods=["GET"])
def list_ingredient_lines(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    get_session(rid)
    rows = [il for il in db.ingredient_lines.values() if il["session_id"] == rid]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)
