"""Friction assessment routes."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_ASSESSMENT_NOT_FOUND, ERR_EVENT_NOT_ACTIVE,
                    ERR_EVENT_NOT_FOUND, ERR_STALE_VERSION,
                    ERR_SURFACE_NOT_FOUND, not_found, validation)
from middleware import require_roles
from response import success_list, success_object
from services.core import (get_pagination, is_int, is_number, new_id,
                           now_iso_ms, paginate, parse_iso, to_decimal)
from services.domain import (derive_braking_action,
                             recompute_active_notam_count,
                             serialize_friction_assessment,
                             supersede_notams_for_assessment)

bp = Blueprint("friction_assessments", __name__)


@bp.route("/friction-assessments", methods=["POST"])
def create_assessment():
    user_id, role = require_roles("AirfieldInspector")
    body = request.get_json(silent=True) or {}
    required = ("event_id", "surface_id", "mu_value", "measured_at")
    for f in required:
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if not is_number(body["mu_value"]):
        raise validation("mu_value must be a number")
    mu = to_decimal(body["mu_value"], "mu_value")
    if mu < 0 or mu > Decimal("1.00"):
        raise validation("mu_value must be 0.00..1.00")
    measured_dt = parse_iso(body["measured_at"], "measured_at")
    if measured_dt > db.logical_clock:
        raise validation("measured_at must not be ahead of the logical clock")

    ev = db.snow_events.get(body["event_id"])
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")
    surface = db.airfield_surfaces.get(body["surface_id"])
    if not surface:
        raise not_found(ERR_SURFACE_NOT_FOUND, "AirfieldSurface not found")

    if ev["status"] not in ("ACTIVATED", "ESCALATED"):
        raise ApiError(ERR_EVENT_NOT_ACTIVE, 409,
                       "Referenced SnowEvent not ACTIVATED/ESCALATED")

    if "expected_surface_version" in body:
        esv = body["expected_surface_version"]
        if not is_int(esv):
            raise validation("expected_surface_version must be an integer")
        if esv != surface["version"]:
            raise ApiError(ERR_STALE_VERSION, 412,
                           "expected_surface_version mismatch")

    ba = derive_braking_action(mu)
    now = now_iso_ms()
    a = {
        "id": new_id(),
        "event_id": body["event_id"],
        "surface_id": body["surface_id"],
        "mu_value": mu,
        "measured_at": body["measured_at"],
        "braking_action": ba,
        "status": "REPORTED",
        "superseded_by_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.friction_assessments[a["id"]] = a

    prior = None
    for x in db.friction_assessments.values():
        if (x["id"] != a["id"]
                and x["event_id"] == body["event_id"]
                and x["surface_id"] == body["surface_id"]
                and x["status"] == "REPORTED"):
            prior = x
            break

    if prior:
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_id"] = a["id"]
        prior["version"] += 1
        prior["updated_at"] = now
        supersede_notams_for_assessment(prior["id"])

    surface["version"] += 1
    surface["updated_at"] = now
    recompute_active_notam_count(surface["id"])

    return success_object(serialize_friction_assessment(a), 201)


@bp.route("/friction-assessments", methods=["GET"])
def list_assessments():
    user_id, role = require_roles("OpsController", "AirfieldInspector")
    limit, offset = get_pagination(request.args)
    items = list(db.friction_assessments.values())
    ev_q = request.args.get("event_id")
    s_q = request.args.get("surface_id")
    st_q = request.args.get("status")
    if ev_q:
        items = [a for a in items if a["event_id"] == ev_q]
    if s_q:
        items = [a for a in items if a["surface_id"] == s_q]
    if st_q:
        items = [a for a in items if a["status"] == st_q]
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_friction_assessment(a) for a in page],
                        limit, offset, total)


@bp.route("/friction-assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    user_id, role = require_roles("OpsController", "AirfieldInspector")
    a = db.friction_assessments.get(assessment_id)
    if not a:
        raise not_found(ERR_ASSESSMENT_NOT_FOUND, "FrictionAssessment not found")
    return success_object(serialize_friction_assessment(a))
