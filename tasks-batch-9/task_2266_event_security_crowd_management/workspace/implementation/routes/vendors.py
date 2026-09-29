"""Subcontractor endpoints (PRD 3.5)."""

from flask import Blueprint

import engine
import serial
import valid
from auth import authenticate, plain_action
from calc import num
from db import db, make_record, now, parse_iso, touch
from errors import ApiError
from response import object_response
from routes._common import get_subcontractor

bp = Blueprint("vendors", __name__)

VENDOR_ACTIONS = ("APPROVE", "SUSPEND", "TERMINATE")


def license_in_use(license_number):
    for vendor in db.subcontractors.values():
        if vendor.get("license_number") == license_number:
            return True
    for guard in db.guards.values():
        if guard.get("license_number") == license_number:
            return True
    return False


@bp.post("/subcontractors")
def create_subcontractor():
    authenticate({"StaffingCoordinator", "CredentialAuditor"})
    payload = valid.body()
    company_name = valid.req_string(payload, "company_name")
    license_number = valid.req_string(payload, "license_number")
    insurance_expires_on = valid.req_datetime(payload, "insurance_expires_on")
    markup_pct = valid.req_number(payload, "markup_pct", minimum=0, maximum="0.60", places=2)

    if license_in_use(license_number):
        raise ApiError("ERR_DUPLICATE_LICENSE_NUMBER")

    record = make_record(
        {
            "company_name": company_name,
            "license_number": license_number,
            "insurance_expires_on": insurance_expires_on[0],
            "markup_pct": num(markup_pct),
            "status": "PENDING",
            "verified_guard_count": 0,
        }
    )
    db.subcontractors[record["id"]] = record
    return object_response(serial.subcontractor(record), 201)


@bp.get("/subcontractors/<subcontractor_id>")
def read_subcontractor(subcontractor_id):
    authenticate(
        {"SecurityDirector", "StaffingCoordinator", "CredentialAuditor", "SubcontractorLiaison"}
    )
    vendor = get_subcontractor(subcontractor_id)
    return object_response(serial.subcontractor(vendor))


@bp.post("/subcontractors/<subcontractor_id>/decision")
def subcontractor_decision(subcontractor_id):
    authenticate({"CredentialAuditor"})
    payload = valid.body()
    action = plain_action(payload, VENDOR_ACTIONS)

    vendor = get_subcontractor(subcontractor_id)
    status = vendor.get("status")

    if action == "APPROVE":
        if status not in ("PENDING", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE", "Only a PENDING or SUSPENDED vendor may be approved.")
        expires = parse_iso(vendor.get("insurance_expires_on"))
        if expires is None or expires <= now():
            raise ApiError("ERR_SUBCONTRACTOR_NOT_ELIGIBLE")
        vendor["status"] = "APPROVED"
        engine.recompute_vendor_guard_count(vendor)
        touch(vendor)

    elif action == "SUSPEND":
        if status != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Only an APPROVED vendor may be suspended.")
        vendor["status"] = "SUSPENDED"
        engine.vendor_suspension_cascade(vendor)
        engine.recompute_vendor_guard_count(vendor)
        touch(vendor)

    else:  # TERMINATE
        if status not in ("PENDING", "APPROVED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE", "A terminated vendor is terminal.")
        if status == "APPROVED":
            engine.vendor_suspension_cascade(vendor)
        vendor["status"] = "TERMINATED"
        engine.recompute_vendor_guard_count(vendor)
        touch(vendor)

    return object_response(serial.subcontractor(vendor))
