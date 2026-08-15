"""NOTAM routes."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_ASSESSMENT_NOT_FOUND, ERR_EVENT_NOT_FOUND,
                    ERR_INVALID_NOTAM_STATE, ERR_INVALID_SURFACE_STATE,
                    ERR_NOTAM_NOT_FOUND, ERR_NOTAM_WINDOW_OVERLAP,
                    ERR_REPORT_NOT_FOUND, ERR_SURFACE_NOT_FOUND,
                    ERR_UNSAFE_NOTAM_CONDITION, not_found, validation)
from middleware import require_roles
from response import success_list, success_object
from services.core import (get_pagination, is_int, is_number, new_id,
                           now_iso_ms, paginate, parse_iso)
from services.domain import (recompute_active_notam_count, serialize_notam)

bp = Blueprint("notams", __name__)

NOTAM_TYPES = {"SURFACE_CONDITION", "RUNWAY_CLOSURE", "CHEMICAL_TREATMENT"}


def _get_notam_or_404(notam_id: str) -> dict:
    n = db.notams.get(notam_id)
    if not n:
        raise not_found(ERR_NOTAM_NOT_FOUND, "Notam not found")
    return n


def _latest_reported_assessment(surface_id: str):
    cands = [a for a in db.friction_assessments.values()
             if a["surface_id"] == surface_id and a["status"] == "REPORTED"]
    if not cands:
        return None
    cands.sort(key=lambda a: a["created_at"])
    return cands[-1]


def _check_window_overlap(surface_id: str, notam_type: str,
                          from_dt, until_dt, exclude_id=None):
    for n in db.notams.values():
        if n["surface_id"] != surface_id:
            continue
        if n["notam_type"] != notam_type:
            continue
        if n["status"] != "ISSUED":
            continue
        if exclude_id and n["id"] == exclude_id:
            continue
        n_from = parse_iso(n["effective_from"], "effective_from")
        n_until = parse_iso(n["effective_until"], "effective_until")
        # closed-interval overlap: shares any instant
        if not (until_dt < n_from or from_dt > n_until):
            return True
    return False


@bp.route("/notams", methods=["POST"])
def create_notam():
    user_id, role = require_roles("OpsController")
    body = request.get_json(silent=True) or {}
    required = ("event_id", "surface_id", "notam_type", "effective_from",
                "effective_until", "message")
    for f in required:
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if body["notam_type"] not in NOTAM_TYPES:
        raise validation("invalid notam_type")
    if not isinstance(body["message"], str):
        raise validation("message must be a string")
    from_dt = parse_iso(body["effective_from"], "effective_from")
    until_dt = parse_iso(body["effective_until"], "effective_until")
    if from_dt >= until_dt:
        raise validation("effective_from must be < effective_until")

    ev = db.snow_events.get(body["event_id"])
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")
    surface = db.airfield_surfaces.get(body["surface_id"])
    if not surface:
        raise not_found(ERR_SURFACE_NOT_FOUND, "AirfieldSurface not found")

    src_assessment_id = body.get("source_assessment_id")
    src_report_id = body.get("source_report_id")
    if src_assessment_id is not None:
        if src_assessment_id not in db.friction_assessments:
            raise not_found(ERR_ASSESSMENT_NOT_FOUND,
                            "FrictionAssessment not found")
    if src_report_id is not None:
        if src_report_id not in db.condition_reports:
            raise not_found(ERR_REPORT_NOT_FOUND, "ConditionReport not found")

    now = now_iso_ms()
    n = {
        "id": new_id(),
        "event_id": body["event_id"],
        "surface_id": body["surface_id"],
        "notam_type": body["notam_type"],
        "effective_from": body["effective_from"],
        "effective_until": body["effective_until"],
        "message": body["message"],
        "source_assessment_id": src_assessment_id,
        "source_report_id": src_report_id,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.notams[n["id"]] = n
    return success_object(serialize_notam(n), 201)


@bp.route("/notams/<notam_id>/notam-actions", methods=["POST"])
def notam_actions(notam_id):
    user_id, role = require_roles("OpsController")
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if not isinstance(action, str) or not action:
        raise validation("action is required")
    if action not in ("ISSUE", "REISSUE", "RESCIND"):
        raise validation("Unknown action")

    n = _get_notam_or_404(notam_id)
    surface = db.airfield_surfaces.get(n["surface_id"])
    if not surface:
        raise not_found(ERR_SURFACE_NOT_FOUND, "AirfieldSurface not found")

    # state machine check
    if action == "ISSUE":
        if n["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_NOTAM_STATE, 409,
                           "ISSUE requires DRAFT status")
    elif action == "REISSUE":
        if n["status"] != "REISSUE_REQUIRED":
            raise ApiError(ERR_INVALID_NOTAM_STATE, 409,
                           "REISSUE requires REISSUE_REQUIRED status")
    elif action == "RESCIND":
        if n["status"] not in ("ISSUED", "REISSUE_REQUIRED"):
            raise ApiError(ERR_INVALID_NOTAM_STATE, 409,
                           "RESCIND requires ISSUED or REISSUE_REQUIRED status")

    # effective window override for REISSUE
    effective_from = body.get("effective_from", n["effective_from"])
    effective_until = body.get("effective_until", n["effective_until"])
    from_dt = parse_iso(effective_from, "effective_from")
    until_dt = parse_iso(effective_until, "effective_until")
    if from_dt >= until_dt:
        raise validation("effective_from must be < effective_until")

    if action in ("ISSUE", "REISSUE"):
        # gate 1: surface must be RESTRICTED or CLOSED
        if surface["status"] not in ("RESTRICTED", "CLOSED"):
            raise ApiError(ERR_INVALID_SURFACE_STATE, 409,
                           "Surface must be RESTRICTED or CLOSED")
        # gate 2: SURFACE_CONDITION safety check
        if n["notam_type"] == "SURFACE_CONDITION":
            latest = _latest_reported_assessment(n["surface_id"])
            if latest and latest["braking_action"] in ("POOR", "NIL"):
                raise ApiError(ERR_UNSAFE_NOTAM_CONDITION, 409,
                               "Latest REPORTED braking action POOR/NIL")
        # gate 3: window overlap
        if _check_window_overlap(n["surface_id"], n["notam_type"],
                                  from_dt, until_dt, exclude_id=n["id"]):
            raise ApiError(ERR_NOTAM_WINDOW_OVERLAP, 409,
                           "Window overlaps existing ISSUED NOTAM")
        n["effective_from"] = effective_from
        n["effective_until"] = effective_until
        n["status"] = "ISSUED"
        n["version"] += 1
        n["updated_at"] = now_iso_ms()
        surface["active_notam_count"] += 1
        surface["updated_at"] = now_iso_ms()
    else:  # RESCIND
        if surface["status"] != "OPEN":
            raise ApiError(ERR_INVALID_SURFACE_STATE, 409,
                           "RESCIND requires surface OPEN")
        was_issued = (n["status"] == "ISSUED")
        n["status"] = "RESCINDED"
        n["version"] += 1
        n["updated_at"] = now_iso_ms()
        if was_issued:
            surface["active_notam_count"] -= 1
            surface["updated_at"] = now_iso_ms()

    return success_object(serialize_notam(n))


@bp.route("/notams", methods=["GET"])
def list_notams():
    user_id, role = require_roles("OpsController", "AirlineCoordinator")
    limit, offset = get_pagination(request.args)
    items = list(db.notams.values())
    for f in ("event_id", "surface_id", "status", "notam_type",
              "source_assessment_id", "source_report_id"):
        q = request.args.get(f)
        if q:
            items = [n for n in items if n[f] == q]
    items.sort(key=lambda n: n["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_notam(n) for n in page], limit, offset, total)


@bp.route("/notams/<notam_id>", methods=["GET"])
def get_notam(notam_id):
    user_id, role = require_roles("OpsController", "AirlineCoordinator")
    n = _get_notam_or_404(notam_id)
    return success_object(serialize_notam(n))
