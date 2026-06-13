"""Appraiser endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
from services import domain, serialize, validate

bp = Blueprint("appraisers", __name__)

APPRAISER_STATUSES = {"ACTIVE", "SUSPENDED", "RETIRED"}


@bp.route("/amc/appraisers", methods=["POST"])
def create_appraiser():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    data = validate.body()

    full_name = validate.require_str(data, "full_name")
    license_state = validate.require_str(data, "license_state")
    if not (len(license_state) == 2 and license_state.isupper() and license_state.isalpha()):
        raise errors.invalid_request("license_state must be a 2-letter uppercase code.")
    base_pct = validate.require_number(data, "base_fee_share_pct")
    if not (0.0 < float(base_pct) <= 1.0):
        raise errors.invalid_request("base_fee_share_pct must be in (0.0, 1.0].")

    appraiser = {
        "full_name": full_name,
        "license_state": license_state,
        "status": "ACTIVE",
        "base_fee_share_pct": base_pct,
        "active_assignment_count": 0,
        "completed_count": 0,
        "on_time_count": 0,
        "last_assigned_at": None,
        "_last_assigned_dt": None,
        "panel_score": 0.0,
    }
    db.stamp_create(appraiser)
    db.appraisers[appraiser["id"]] = appraiser
    return response.ok_object(serialize.public(appraiser), 201)


@bp.route("/amc/appraisers/<aid>", methods=["GET"])
def get_appraiser(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(
        role, {"AMCCoordinator", "PlatformAdmin", "ComplianceReviewer", "Appraiser"})
    appraiser = db.appraisers.get(aid)
    if appraiser is None:
        raise errors.not_found("Appraiser not found.")
    return response.ok_object(serialize.public(appraiser), 200)


@bp.route("/amc/appraisers/<aid>/status", methods=["POST"])
def change_status(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    appraiser = db.appraisers.get(aid)
    if appraiser is None:
        raise errors.not_found("Appraiser not found.")
    data = validate.body()
    status = validate.require_enum(data, "status", APPRAISER_STATUSES)
    appraiser["status"] = status
    domain.recompute_panel_score_only(appraiser)
    db.touch(appraiser)
    return response.ok_object(serialize.public(appraiser), 200)
