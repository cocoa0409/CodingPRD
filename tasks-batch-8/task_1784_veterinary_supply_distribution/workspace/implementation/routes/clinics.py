"""Clinic endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_CLINIC_INVALID_STATE,
    ERR_STALE_CLINIC_VERSION,
)
from middleware import authorized
from response import success_object
from services.core import (
    get_body, require_fields, require_string, require_int, public,
    get_clinic_or_404,
)
from util import new_id, now_ts, touch

bp = Blueprint("clinics", __name__)

READ_ROLES = ["AccountManager", "ClinicBuyer", "SupplyChainPlanner", "ComplianceOfficer"]


@bp.route("/vet/clinics", methods=["POST"])
def create_clinic():
    authorized(["AccountManager"])
    body = get_body()
    require_fields(body, ["clinic_name", "license_number", "ship_to_address",
                          "credit_limit_cents", "minimum_order_value_cents",
                          "delivery_frequency_per_week", "free_freight_threshold_cents"])
    clinic = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "clinic_name": require_string(body, "clinic_name"),
        "license_number": require_string(body, "license_number"),
        "dea_registration_number": body.get("dea_registration_number"),
        "ship_to_address": require_string(body, "ship_to_address"),
        "status": "PENDING_VERIFICATION",
        "credit_limit_cents": require_int(body, "credit_limit_cents", minimum=0),
        "credit_used_cents": 0,
        "minimum_order_value_cents": require_int(body, "minimum_order_value_cents", minimum=0),
        "delivery_frequency_per_week": require_int(body, "delivery_frequency_per_week", minimum=1),
        "free_freight_threshold_cents": require_int(body, "free_freight_threshold_cents", minimum=0),
    }
    db["clinics"][clinic["id"]] = clinic
    return success_object(public(clinic), status=201)


@bp.route("/vet/clinics/<cid>", methods=["GET"])
def get_clinic(cid):
    authorized(READ_ROLES)
    clinic = get_clinic_or_404(cid)
    return success_object(public(clinic))


@bp.route("/vet/clinics/<cid>", methods=["PATCH"])
def patch_clinic(cid):
    authorized(["AccountManager"])
    clinic = get_clinic_or_404(cid)
    body = get_body()
    # OCC: expected_clinic_version is a non-optional field (PRD 2.7).
    if "expected_clinic_version" not in body or body["expected_clinic_version"] is None:
        raise_error(ERR_STALE_CLINIC_VERSION,
                    "expected_clinic_version is required")
    expected = body["expected_clinic_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_error(ERR_STALE_CLINIC_VERSION,
                    "expected_clinic_version must be an integer")
    if expected != clinic["version"]:
        raise_error(ERR_STALE_CLINIC_VERSION,
                    "expected_clinic_version does not match the clinic's current version")

    for field in ("clinic_name", "ship_to_address"):
        if field in body and body[field] is not None:
            clinic[field] = require_string(body, field)
    for field in ("credit_limit_cents", "minimum_order_value_cents",
                  "free_freight_threshold_cents"):
        if field in body and body[field] is not None:
            clinic[field] = require_int(body, field, minimum=0)
    if "delivery_frequency_per_week" in body and body["delivery_frequency_per_week"] is not None:
        clinic["delivery_frequency_per_week"] = require_int(
            body, "delivery_frequency_per_week", minimum=1)
    touch(clinic)
    return success_object(public(clinic))


def _transition(cid, from_state, to_state):
    authorized(["AccountManager"])
    clinic = get_clinic_or_404(cid)
    if clinic["status"] != from_state:
        raise_error(ERR_CLINIC_INVALID_STATE,
                    f"clinic must be {from_state} (is {clinic['status']})")
    clinic["status"] = to_state
    touch(clinic)
    return success_object(public(clinic))


@bp.route("/vet/clinics/<cid>/activate", methods=["POST"])
def activate_clinic(cid):
    return _transition(cid, "PENDING_VERIFICATION", "ACTIVE")


@bp.route("/vet/clinics/<cid>/suspend", methods=["POST"])
def suspend_clinic(cid):
    # Suspension cascades to nothing: DRAFT orders remain DRAFT (PRD 3.1).
    return _transition(cid, "ACTIVE", "SUSPENDED")


@bp.route("/vet/clinics/<cid>/reinstate", methods=["POST"])
def reinstate_clinic(cid):
    return _transition(cid, "SUSPENDED", "ACTIVE")
