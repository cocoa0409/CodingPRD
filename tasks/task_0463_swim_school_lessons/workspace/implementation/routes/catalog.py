"""Clock, Location, Level, Skill, Instructor routes. PRD 3.1, 3.2, 3.11."""
from flask import Blueprint

from clock import clock
from db import store, iso, common_fields_on_create
from errors import err, ERR_INVALID_REQUEST
from helpers import (
    get_body, require_str, opt_str, require_int, opt_int, require_number,
    opt_number, require_datetime, parse_pagination, paginate,
)
from middleware import get_principal, require_roles
from response import object_response, array_response
from domain import (
    serialize_location, serialize_level, serialize_skill, serialize_instructor,
)
from lookups import get_location, get_level, get_instructor

bp = Blueprint("catalog", __name__)

ALL_ROLES = ["SchoolAdmin", "BillingAdmin", "Instructor", "Parent"]


# ---------------------------------------------------------------------------
# Logical clock — PRD 3.11. Shared SchoolAdmin + BillingAdmin.
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "BillingAdmin"])
    body = get_body()
    dt = require_datetime(body, "to_iso8601")
    clock.set(dt)
    return object_response({"current_utc": iso(clock.now())}, 200)


# ---------------------------------------------------------------------------
# Location — PRD 3.1
# ---------------------------------------------------------------------------
@bp.route("/locations", methods=["POST"])
def create_location():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    body = get_body()
    name = require_str(body, "name")
    timezone = opt_str(body, "timezone", "UTC")
    rec = common_fields_on_create()
    rec.update({"name": name, "timezone": timezone, "status": "OPEN"})
    store.locations[rec["id"]] = rec
    return object_response(serialize_location(rec), 201)


@bp.route("/locations", methods=["GET"])
def list_locations():
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    window, total = paginate(list(store.locations.values()), limit, offset)
    return array_response([serialize_location(r) for r in window], limit, offset, total)


@bp.route("/locations/<id>", methods=["GET"])
def get_location_route(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    rec = get_location(id)
    return object_response(serialize_location(rec), 200)


# ---------------------------------------------------------------------------
# Level + Skill — PRD 3.1
# ---------------------------------------------------------------------------
@bp.route("/levels", methods=["POST"])
def create_level():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    body = get_body()
    name = require_str(body, "name")
    sequence_order = require_int(body, "sequence_order", min_value=1)
    # sequence_order unique across levels.
    for lv in store.levels.values():
        if lv["sequence_order"] == sequence_order:
            err(ERR_INVALID_REQUEST, "sequence_order must be unique")
    next_level_id = opt_str(body, "next_level_id", None)
    if next_level_id is not None:
        # FK existence: a missing next_level points at a nonexistent level.
        get_level(next_level_id)
    min_age_months = require_int(body, "min_age_months", min_value=0)
    max_age_months = require_int(body, "max_age_months")
    if max_age_months <= min_age_months:
        err(ERR_INVALID_REQUEST, "max_age_months must be > min_age_months")
    max_students = require_int(body, "max_students_per_instructor", min_value=1)
    monthly_tuition = require_int(body, "monthly_tuition_cents", min_value=0)
    readiness = opt_number(body, "readiness_threshold", 0.80)
    if not (0 < readiness <= 1):
        err(ERR_INVALID_REQUEST, "readiness_threshold must be in (0, 1]")
    rec = common_fields_on_create()
    rec.update({
        "name": name,
        "sequence_order": sequence_order,
        "next_level_id": next_level_id,
        "min_age_months": min_age_months,
        "max_age_months": max_age_months,
        "max_students_per_instructor": max_students,
        "monthly_tuition_cents": monthly_tuition,
        "readiness_threshold": readiness,
    })
    store.levels[rec["id"]] = rec
    return object_response(serialize_level(rec), 201)


@bp.route("/levels", methods=["GET"])
def list_levels():
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    from flask import request
    records = list(store.levels.values())
    next_level_id = request.args.get("next_level_id")
    if next_level_id is not None:
        records = [r for r in records if r["next_level_id"] == next_level_id]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_level(r) for r in window], limit, offset, total)


@bp.route("/levels/<id>", methods=["GET"])
def get_level_route(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    rec = get_level(id)
    return object_response(serialize_level(rec), 200)


@bp.route("/levels/<id>/skills", methods=["POST"])
def add_skill(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    level = get_level(id)
    body = get_body()
    name = require_str(body, "name")
    weight = opt_number(body, "weight", 1.0)
    if weight <= 0:
        err(ERR_INVALID_REQUEST, "weight must be > 0")
    rec = common_fields_on_create()
    rec.update({"level_id": level["id"], "name": name, "weight": weight})
    store.skills[rec["id"]] = rec
    return object_response(serialize_skill(rec), 201)


@bp.route("/levels/<id>/skills", methods=["GET"])
def list_skills(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    level = get_level(id)
    limit, offset = parse_pagination()
    records = [s for s in store.skills.values() if s["level_id"] == level["id"]]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_skill(r) for r in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Instructor — PRD 3.2
# ---------------------------------------------------------------------------
@bp.route("/instructors", methods=["POST"])
def create_instructor():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    body = get_body()
    full_name = require_str(body, "full_name")
    certified = body.get("certified_level_ids", None)
    if certified is None:
        certified = []
    if not isinstance(certified, list) or not all(isinstance(x, str) for x in certified):
        err(ERR_INVALID_REQUEST, "certified_level_ids must be an array of strings")
    rec = common_fields_on_create()
    rec.update({
        "full_name": full_name,
        "certified_level_ids": list(certified),
        "status": "ACTIVE",
    })
    store.instructors[rec["id"]] = rec
    return object_response(serialize_instructor(rec), 201)


@bp.route("/instructors", methods=["GET"])
def list_instructors():
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    window, total = paginate(list(store.instructors.values()), limit, offset)
    return array_response([serialize_instructor(r) for r in window], limit, offset, total)


@bp.route("/instructors/<id>", methods=["GET"])
def get_instructor_route(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    rec = get_instructor(id)
    return object_response(serialize_instructor(rec), 200)
