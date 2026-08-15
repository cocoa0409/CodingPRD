"""Permit endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_DATE_IN_PAST,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    parse_iso_date,
    require_enum,
    require_fields,
    require_roles,
    spine_at_least,
    validate_crossings,
)
from response import success_list, success_object
from services.calculations import permit_fee
from services.domain import get_application, get_permit, touch

bp = Blueprint("permits", __name__)

PERMIT_TYPES = ("ROAD_CUT", "EASEMENT", "RAILROAD_CROSSING", "DOT_HIGHWAY")


@bp.route("/permits", methods=["POST"])
def create_permit():
    require_roles("PermitCoordinator")
    body = get_body()
    require_fields(body, "service_application_id", "permit_type", "jurisdiction")
    app = get_application(body["service_application_id"])
    permit_type = require_enum(body, "permit_type", PERMIT_TYPES)
    jurisdiction = body["jurisdiction"]
    if not isinstance(jurisdiction, str) or not jurisdiction:
        raise_error(ERR_INVALID_REQUEST, "jurisdiction must be a non-empty string")
    # §2.6: "a road-cut permit with an empty crossing list" is a malformed request body
    crossings = validate_crossings(body.get("crossings", []))
    if permit_type == "ROAD_CUT" and len(crossings) == 0:
        raise_error(ERR_INVALID_REQUEST, "A ROAD_CUT permit requires a non-empty crossings list")
    check_app_mutable(app)
    now = db.now_iso()
    permit = {
        "id": new_id(),
        "service_application_id": app["id"],
        "permit_type": permit_type,
        "jurisdiction": jurisdiction,
        "crossings": crossings,
        "permit_fee_cents": permit_fee(crossings),
        "status": "DRAFT",
        "filed_at": None,
        "decided_at": None,
        "expires_at": None,
        "decision_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.permits[permit["id"]] = permit
    return success_object(permit, 201)


@bp.route("/permits/<pid>", methods=["GET"])
def get_one_permit(pid):
    require_roles(*ANY_ROLE)
    return success_object(get_permit(pid))


@bp.route("/permits", methods=["GET"])
def list_permits():
    require_roles(*ANY_ROLE)
    records = list(db.permits.values())
    app_id = request.args.get("service_application_id")
    ptype = request.args.get("permit_type")
    status = request.args.get("status")
    if app_id is not None:
        records = [p for p in records if p["service_application_id"] == app_id]
    if ptype is not None:
        records = [p for p in records if p["permit_type"] == ptype]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/permits/<pid>/file", methods=["POST"])
def file_permit(pid):
    require_roles("PermitCoordinator")
    permit = get_permit(pid)
    app = get_application(permit["service_application_id"])
    check_app_mutable(app)
    if permit["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Only DRAFT permits can be filed")
    if permit["permit_type"] == "ROAD_CUT" and len(permit["crossings"]) == 0:
        raise_error(ERR_INVALID_REQUEST, "A ROAD_CUT permit requires a non-empty crossings list")
    permit["status"] = "FILED"
    permit["filed_at"] = db.now_iso()
    touch(permit)
    # Spine nudge: APPROVED_FOR_CONSTRUCTION → PERMITTING on first FILED permit
    if app["status"] == "APPROVED_FOR_CONSTRUCTION":
        app["status"] = "PERMITTING"
        touch(app)
    return success_object(permit)


@bp.route("/permits/<pid>/record-decision", methods=["POST"])
def record_decision(pid):
    require_roles("PermitCoordinator")
    permit = get_permit(pid)
    app = get_application(permit["service_application_id"])
    body = get_body()
    require_fields(body, "decision")
    decision = require_enum(body, "decision", ("APPROVED", "REJECTED"))
    check_app_mutable(app)
    if permit["status"] != "FILED":
        raise_error(ERR_INVALID_STATE, "Only FILED permits can receive a decision")
    if decision == "APPROVED":
        if "expires_at" not in body or body["expires_at"] is None:
            raise_error(ERR_INVALID_REQUEST, "expires_at is required for an APPROVED decision")
        expires = parse_iso_date(body["expires_at"], "expires_at")
        if expires < db.today_date():
            raise_error(ERR_DATE_IN_PAST, "expires_at must be on or after the current date")
        permit["expires_at"] = body["expires_at"]
        permit["status"] = "APPROVED"
    else:
        permit["status"] = "REJECTED"
    if "decision_note" in body and body["decision_note"] is not None:
        permit["decision_note"] = body["decision_note"]
    permit["decided_at"] = db.now_iso()
    touch(permit)
    return success_object(permit)


@bp.route("/permits/<pid>/amend", methods=["POST"])
def amend_permit(pid):
    require_roles("PermitCoordinator")
    permit = get_permit(pid)
    app = get_application(permit["service_application_id"])
    body = get_body()
    check_app_mutable(app)
    if permit["status"] not in ("REJECTED", "EXPIRED"):
        raise_error(ERR_INVALID_STATE, "Only REJECTED or EXPIRED permits can be amended")
    crossings_changed = False
    if "jurisdiction" in body and body["jurisdiction"] is not None:
        if not isinstance(body["jurisdiction"], str) or not body["jurisdiction"]:
            raise_error(ERR_INVALID_REQUEST, "jurisdiction must be a non-empty string")
        permit["jurisdiction"] = body["jurisdiction"]
    if "crossings" in body and body["crossings"] is not None:
        new_crossings = validate_crossings(body["crossings"])
        if permit["permit_type"] == "ROAD_CUT" and len(new_crossings) == 0:
            raise_error(ERR_INVALID_REQUEST, "A ROAD_CUT permit requires a non-empty crossings list")
        permit["crossings"] = new_crossings
        crossings_changed = True
    if crossings_changed:
        permit["permit_fee_cents"] = permit_fee(permit["crossings"])
    permit["status"] = "DRAFT"
    touch(permit)
    return success_object(permit)


@bp.route("/permits/<pid>/close", methods=["POST"])
def close_permit(pid):
    require_roles("PermitCoordinator")
    permit = get_permit(pid)
    app = get_application(permit["service_application_id"])
    check_app_mutable(app)
    if permit["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "Only APPROVED permits can be closed")
    if not spine_at_least(app, "SERVICE_INSTALLED"):
        raise_error(ERR_INVALID_STATE, "Application must be at SERVICE_INSTALLED or later to close a permit")
    permit["status"] = "CLOSED"
    touch(permit)
    return success_object(permit)
