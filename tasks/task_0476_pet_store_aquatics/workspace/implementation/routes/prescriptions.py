"""Prescription endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
from db import stamp_create, touch
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_int, as_datetime,
)
from services.serialize import prescription_out

bp = Blueprint("prescriptions", __name__)

READ_ROLES = ["InventoryManager", "StoreClerk", "ClinicVet", "Customer"]


@bp.route("/prescriptions", methods=["POST"])
def issue_prescription():
    _, role = require_auth()
    require_role(role, ["ClinicVet"])
    body = get_body()
    customer_id = as_str(require_present(body, "customer_id"), "customer_id")
    product_id = as_str(require_present(body, "product_id"), "product_id")
    appt_id = as_str(require_present(body, "issued_by_appointment_id"), "issued_by_appointment_id")
    # FK existence (step 5).
    lookup("customers", customer_id)
    lookup("products", product_id)
    appointment = lookup("clinic_appointments", appt_id)

    max_units = as_int(require_present(body, "max_units_per_order"), "max_units_per_order")
    if max_units <= 0:
        raise err("ERR_INVALID_FIELD_VALUE", "max_units_per_order must be > 0.")
    expires_at = require_present(body, "expires_at")
    as_datetime(expires_at, "expires_at")

    # Referential: appointment must be a COMPLETED VET_EXAM for the same customer.
    if (
        appointment["status"] != "COMPLETED"
        or appointment["service_type"] != "VET_EXAM"
        or appointment["customer_id"] != customer_id
    ):
        raise err("ERR_APPOINTMENT_NOT_ELIGIBLE")

    record = {
        "customer_id": customer_id,
        "product_id": product_id,
        "issued_by_appointment_id": appt_id,
        "max_units_per_order": max_units,
        "expires_at": expires_at,
        "status": "ACTIVE",
    }
    stamp_create(record)
    db.prescriptions[record["id"]] = record
    return object_response(prescription_out(record), 201)


@bp.route("/prescriptions", methods=["GET"])
def list_prescriptions():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.prescriptions.values())
    for field in ("customer_id", "product_id", "issued_by_appointment_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, total = paginate(records, limit, offset)
    return array_response([prescription_out(r) for r in page], limit, offset, total)


@bp.route("/prescriptions/<prescription_id>", methods=["GET"])
def get_prescription(prescription_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    record = lookup("prescriptions", prescription_id)
    return object_response(prescription_out(record))


@bp.route("/prescriptions/<prescription_id>/revoke", methods=["POST"])
def revoke_prescription(prescription_id):
    _, role = require_auth()
    require_role(role, ["ClinicVet"])
    record = lookup("prescriptions", prescription_id)
    if record["status"] != "ACTIVE":
        # No dedicated prescription-state error in the catalogue; the only
        # transition is ACTIVE -> REVOKED. Treat a non-ACTIVE revoke as invalid
        # field/state via the closest applicable contract. PRD §3.8 only permits
        # ACTIVE -> REVOKED, so reject re-revoke.
        raise err("ERR_INVALID_FIELD_VALUE", "Prescription is not ACTIVE.")
    record["status"] = "REVOKED"
    touch(record)
    return object_response(prescription_out(record))
