"""ExemptionApplication endpoints."""

from decimal import Decimal

from flask import Blueprint, g

from config import DEFERRAL_DISABILITY_MIN_PCT, DISABILITY_MIN_PCT, SENIOR_AGE
from db import store
from errors import raise_error
from middleware import require_owner_of_property, require_roles
from response import success
from routes._helpers import (
    bump,
    check_version,
    get_json_body,
    require_exemption_application,
    require_field,
    require_property,
)
from services.calculations import (
    compute_exemption_stack,
    compute_tax_bill_fields,
    owner_age_on_jan1,
)
from services.serializers import serialize_exemption_application
from utils import new_uuid

exemptions_bp = Blueprint("exemption_applications", __name__)

VALID_EXEMPTION_TYPES = {"HOMESTEAD", "SENIOR", "VETERAN", "DISABILITY"}
VALID_REVOKED_REASONS = {"OWNERSHIP_CHANGE", "INELIGIBLE", "WITHDRAWN"}


def _recompute_bill_if_present(property_id, roll_year):
    """Recompute non-terminal bills for the (property, roll_year)."""
    for bill in store.tax_bills.values():
        if bill["property_id"] != property_id:
            continue
        if bill["roll_year"] != roll_year:
            continue
        if bill["status"] in ("PAID",):
            continue
        old_payments = bill.get("total_payments_applied") or Decimal("0")
        old_status = bill["status"]
        compute_tax_bill_fields(bill, recompute_stack=True)
        # Adjust status given recompute
        if old_status in ("ISSUED", "PARTIALLY_PAID"):
            if bill["total_payments_applied"] >= bill["base_tax_amount"] and bill["amount_due"] == Decimal("0"):
                # Could become fully paid via reduction; but spec says revocation may make underpaid
                # If was already paid: shouldn't happen here (we skip PAID)
                if old_status == "PARTIALLY_PAID" and bill["amount_due"] == Decimal("0"):
                    bill["status"] = "PAID"
            else:
                if bill["total_payments_applied"] > Decimal("0") and bill["amount_due"] > Decimal("0"):
                    bill["status"] = "PARTIALLY_PAID"
        bump(bill)


@exemptions_bp.post("/properties/<property_id>/exemption_applications")
def submit_exemption(property_id):
    require_roles({"Owner"})
    require_property(property_id)
    require_owner_of_property(property_id)
    body = get_json_body()
    et = require_field(body, "exemption_type")
    if et not in VALID_EXEMPTION_TYPES:
        raise_error("ERR_VALIDATION_FAILED", "exemption_type is invalid")
    roll_year = require_field(body, "effective_roll_year")
    if not isinstance(roll_year, int) or isinstance(roll_year, bool):
        raise_error("ERR_VALIDATION_FAILED", "effective_roll_year must be an integer")

    now = store.clock.now()
    rec = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "property_id": property_id,
        "owner_id": g.user_id,
        "exemption_type": et,
        "effective_roll_year": roll_year,
        "status": "SUBMITTED",
        "approved_amount": None,
        "approved_at": None,
        "revoked_reason": None,
    }
    with store.lock:
        store.exemption_applications[rec["id"]] = rec
    return success(serialize_exemption_application(rec), status_code=201)


@exemptions_bp.post("/properties/<property_id>/exemption_applications/<app_id>/approve")
def approve_exemption(property_id, app_id):
    require_roles({"Assessor"})
    rec = require_exemption_application(property_id, app_id)
    body = get_json_body()

    if rec["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE", "application is not SUBMITTED")

    prop = store.properties[property_id]
    if prop["owner_id"] != rec["owner_id"]:
        raise_error("ERR_OWNERSHIP_MISMATCH")

    # Exemption uniqueness
    for other in store.exemption_applications.values():
        if other["id"] == rec["id"]:
            continue
        if other["property_id"] != property_id:
            continue
        if other["effective_roll_year"] != rec["effective_roll_year"]:
            continue
        if other["exemption_type"] != rec["exemption_type"]:
            continue
        if other["status"] == "APPROVED":
            raise_error("ERR_EXEMPTION_DUPLICATE")

    # Eligibility
    owner = store.owners.get(rec["owner_id"])
    if owner is None:
        raise_error("ERR_NOT_FOUND", "owner record missing")
    et = rec["exemption_type"]
    if et == "HOMESTEAD":
        if prop["owner_id"] != owner["id"]:
            raise_error("ERR_EXEMPTION_INELIGIBLE")
    elif et == "SENIOR":
        age = owner_age_on_jan1(owner, rec["effective_roll_year"])
        if age < SENIOR_AGE:
            raise_error("ERR_EXEMPTION_INELIGIBLE")
    elif et == "VETERAN":
        if not owner.get("veteran_status", False):
            raise_error("ERR_EXEMPTION_INELIGIBLE")
    elif et == "DISABILITY":
        if owner.get("disability_rating", 0) < DISABILITY_MIN_PCT:
            raise_error("ERR_EXEMPTION_INELIGIBLE")

    check_version(rec, body)

    with store.lock:
        now = store.clock.now()
        rec["status"] = "APPROVED"
        rec["approved_at"] = now
        bump(rec)
        # Recompute exemption stack for this (property, year)
        # which writes approved_amount on this app and any siblings.
        # Need the assessment's capped_value
        assessment_capped = Decimal("0")
        for a in store.assessments.values():
            if a["property_id"] != property_id:
                continue
            if a["roll_year"] != rec["effective_roll_year"]:
                continue
            if a.get("capped_value") is not None:
                assessment_capped = Decimal(str(a["capped_value"]))
                break
        compute_exemption_stack(property_id, rec["effective_roll_year"], assessment_capped, mutate=True)
        # Cascade: bills in non-terminal status
        _recompute_bill_if_present(property_id, rec["effective_roll_year"])

    return success(serialize_exemption_application(rec))


@exemptions_bp.post("/properties/<property_id>/exemption_applications/<app_id>/deny")
def deny_exemption(property_id, app_id):
    require_roles({"Assessor"})
    rec = require_exemption_application(property_id, app_id)
    body = get_json_body()
    if rec["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE", "application is not SUBMITTED")
    check_version(rec, body)
    with store.lock:
        rec["status"] = "DENIED"
        bump(rec)
    return success(serialize_exemption_application(rec))


@exemptions_bp.post("/properties/<property_id>/exemption_applications/<app_id>/revoke")
def revoke_exemption(property_id, app_id):
    require_roles({"Assessor"})
    rec = require_exemption_application(property_id, app_id)
    body = get_json_body()
    if rec["status"] != "APPROVED":
        raise_error("ERR_INVALID_STATE", "application is not APPROVED")
    reason = require_field(body, "revoked_reason")
    if reason not in VALID_REVOKED_REASONS:
        raise_error("ERR_VALIDATION_FAILED", "revoked_reason is invalid")
    check_version(rec, body)
    with store.lock:
        rec["status"] = "REVOKED"
        rec["revoked_reason"] = reason
        bump(rec)
        # Recompute stack and bill
        assessment_capped = Decimal("0")
        for a in store.assessments.values():
            if a["property_id"] != property_id:
                continue
            if a["roll_year"] != rec["effective_roll_year"]:
                continue
            if a.get("capped_value") is not None:
                assessment_capped = Decimal(str(a["capped_value"]))
                break
        compute_exemption_stack(property_id, rec["effective_roll_year"], assessment_capped, mutate=True)
        _recompute_bill_if_present(property_id, rec["effective_roll_year"])

    return success(serialize_exemption_application(rec))
