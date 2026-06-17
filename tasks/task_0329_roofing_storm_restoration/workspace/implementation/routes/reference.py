"""Estimators, Crews (reference data) and the test-driving clock."""
from flask import Blueprint

import errors
from db import db, common_create_fields
from errors import ApiError
from middleware import require_role, get_json_body
from response import success
from timeutil import parse_iso8601
from clock import clock
import validators as V

bp = Blueprint("reference", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}


# ---------------------------------------------------------------------------
# Estimators (reference data: only id + created_at)
# ---------------------------------------------------------------------------
@bp.route("/estimators", methods=["POST"])
def create_estimator():
    require_role({"Estimator", "ProductionManager"})
    body = get_json_body()
    name = V.require_field(body, "name")
    license_no = V.require_field(body, "license_no")
    if not isinstance(name, str):
        V.missing_field("name")
    if not isinstance(license_no, str):
        V.missing_field("license_no")
    ent = common_create_fields(versioned=False)
    ent.update({"name": name, "license_no": license_no})
    with db.lock:
        db.estimators[ent["id"]] = ent
    return success(ent, status=201)


@bp.route("/estimators/<entity_id>", methods=["GET"])
def get_estimator(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.estimators, entity_id)
    return success(ent, status=200)


# ---------------------------------------------------------------------------
# Crews
# ---------------------------------------------------------------------------
@bp.route("/crews", methods=["POST"])
def create_crew():
    require_role({"ProductionManager"})
    body = get_json_body()
    name = V.require_field(body, "name")
    if not isinstance(name, str):
        V.missing_field("name")

    max_squares = body.get("max_squares_per_day", 30)
    if max_squares is None:
        max_squares = 30
    V.validate_number(max_squares, "max_squares_per_day")

    active = body.get("active", True)
    if active is None:
        active = True
    if not isinstance(active, bool):
        V.invalid_request("active must be a boolean")

    ent = common_create_fields(versioned=True)
    ent.update({
        "name": name,
        "max_squares_per_day": max_squares,
        "active": active,
    })
    with db.lock:
        db.crews[ent["id"]] = ent
    return success(ent, status=201)


@bp.route("/crews/<entity_id>", methods=["GET"])
def get_crew(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.crews, entity_id)
    return success(ent, status=200)


# ---------------------------------------------------------------------------
# Test-driving clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    require_role({"ProductionManager"})
    body = get_json_body()
    to_iso = V.require_field(body, "to_iso8601")
    dt = parse_iso8601(to_iso)
    if dt is None:
        V.invalid_request("to_iso8601 must be an ISO 8601 datetime")
    clock.set(dt)
    return success({}, status=200)
