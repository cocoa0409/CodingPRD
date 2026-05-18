"""DeferralPlan endpoints."""

from datetime import date
from decimal import Decimal

from flask import Blueprint

from config import DEFERRAL_DISABILITY_MIN_PCT, DEFERRAL_INTEREST_RATE, SENIOR_AGE
from db import store
from errors import raise_error
from middleware import require_owner_of_property, require_roles
from response import success
from routes._helpers import (
    bump,
    check_version,
    get_json_body,
    require_deferral_plan,
    require_tax_bill,
)
from services.calculations import (
    compute_accrued_interest,
    compute_tax_bill_fields,
    owner_age_today,
)
from services.serializers import serialize_deferral_plan
from utils import new_uuid

deferrals_bp = Blueprint("deferral_plans", __name__)


@deferrals_bp.post("/properties/<property_id>/tax_bills/<tax_bill_id>/deferral_plans")
def request_deferral(property_id, tax_bill_id):
    require_roles({"Owner"})
    bill = require_tax_bill(property_id, tax_bill_id)
    require_owner_of_property(property_id)

    now = store.clock.now()
    rec = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "tax_bill_id": tax_bill_id,
        "property_id": property_id,
        "principal_deferred": None,
        "annual_interest_rate": None,
        "accrued_interest": None,
        "started_at": None,
        "closed_at": None,
        "status": "REQUESTED",
    }
    with store.lock:
        store.deferral_plans[rec["id"]] = rec
    return success(serialize_deferral_plan(rec), status_code=201)


@deferrals_bp.post("/properties/<property_id>/tax_bills/<tax_bill_id>/deferral_plans/<plan_id>/activate")
def activate_deferral(property_id, tax_bill_id, plan_id):
    require_roles({"Treasurer"})
    rec = require_deferral_plan(property_id, tax_bill_id, plan_id)
    body = get_json_body()
    bill = store.tax_bills[tax_bill_id]

    if rec["status"] != "REQUESTED":
        raise_error("ERR_INVALID_STATE", "deferral plan is not REQUESTED")

    if bill["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise_error("ERR_INVALID_STATE", "bill is not in ISSUED/PARTIALLY_PAID")

    # Eligibility check
    prop = store.properties[property_id]
    owner = store.owners.get(prop["owner_id"])
    if owner is None:
        raise_error("ERR_NOT_FOUND", "owner not found")
    eligible = False
    if owner.get("disability_rating", 0) >= DEFERRAL_DISABILITY_MIN_PCT:
        eligible = True
    else:
        try:
            age = owner_age_today(owner, store.clock.now().date())
            if age >= SENIOR_AGE:
                eligible = True
        except Exception:
            pass
    if not eligible:
        raise_error("ERR_DEFERRAL_NOT_ELIGIBLE")

    check_version(rec, body)

    with store.lock:
        now = store.clock.now()
        # Refresh bill amount_due
        compute_tax_bill_fields(bill, recompute_stack=False)
        rec["status"] = "ACTIVE"
        rec["started_at"] = now
        rec["principal_deferred"] = Decimal(str(bill["amount_due"]))
        rec["annual_interest_rate"] = DEFERRAL_INTEREST_RATE
        rec["accrued_interest"] = Decimal("0.00")
        bump(rec)
        bill["status"] = "IN_DEFERRAL"
        bump(bill)
    return success(serialize_deferral_plan(rec))


@deferrals_bp.post("/properties/<property_id>/tax_bills/<tax_bill_id>/deferral_plans/<plan_id>/cancel")
def cancel_deferral(property_id, tax_bill_id, plan_id):
    require_roles({"Owner"})
    rec = require_deferral_plan(property_id, tax_bill_id, plan_id)
    require_owner_of_property(property_id)
    body = get_json_body()
    if rec["status"] != "REQUESTED":
        raise_error("ERR_INVALID_STATE", "deferral plan is not REQUESTED")
    check_version(rec, body)
    with store.lock:
        rec["status"] = "DEFAULTED"
        rec["closed_at"] = store.clock.now()
        bump(rec)
    return success(serialize_deferral_plan(rec))


@deferrals_bp.get("/properties/<property_id>/tax_bills/<tax_bill_id>/deferral_plans/<plan_id>")
def get_deferral(property_id, tax_bill_id, plan_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    rec = require_deferral_plan(property_id, tax_bill_id, plan_id)
    # Recompute accrued_interest live
    if rec["status"] == "ACTIVE":
        rec["accrued_interest"] = compute_accrued_interest(rec, store.clock.now())
    return success(serialize_deferral_plan(rec))
