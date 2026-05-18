"""TaxBill and Payment endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from config import DEFAULT_MILL_RATE, DUE_WINDOW_DAYS
from db import store
from errors import raise_error
from middleware import require_owner_of_property, require_roles
from response import paginate, parse_pagination, success
from routes._helpers import (
    bump,
    check_version,
    get_json_body,
    parse_number,
    require_field,
    require_property,
    require_tax_bill,
)
from services.calculations import compute_accrued_interest, compute_tax_bill_fields
from services.serializers import serialize_payment, serialize_tax_bill
from utils import new_uuid, round_half_up

tax_bills_bp = Blueprint("tax_bills", __name__)


@tax_bills_bp.post("/properties/<property_id>/tax_bills")
def create_tax_bill(property_id):
    require_roles({"Treasurer"})
    require_property(property_id)
    body = get_json_body()
    roll_year = require_field(body, "roll_year")
    if not isinstance(roll_year, int) or isinstance(roll_year, bool):
        raise_error("ERR_VALIDATION_FAILED", "roll_year must be an integer")

    # Locate FINALIZED Assessment
    assessment = None
    for a in store.assessments.values():
        if a["property_id"] != property_id:
            continue
        if a["roll_year"] != roll_year:
            continue
        assessment = a
        break
    if assessment is None:
        raise_error("ERR_NOT_FOUND", "no assessment for this property/roll_year")
    if assessment["status"] != "FINALIZED":
        raise_error("ERR_ASSESSMENT_NOT_FINALIZED")

    # Duplicate bill
    for tb in store.tax_bills.values():
        if tb["property_id"] == property_id and tb["roll_year"] == roll_year:
            raise_error("ERR_DUPLICATE_BILL")

    mill_rate = DEFAULT_MILL_RATE
    if "mill_rate" in body and body["mill_rate"] is not None:
        mr = parse_number(body["mill_rate"], "mill_rate")
        if mr < Decimal("0"):
            raise_error("ERR_VALIDATION_FAILED", "mill_rate must be non-negative")
        mill_rate = mr

    now = store.clock.now()
    rec = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "property_id": property_id,
        "assessment_id": assessment["id"],
        "roll_year": roll_year,
        "mill_rate": mill_rate,
        "status": "PENDING",
        "issued_at": None,
        "due_date": None,
        "taxable_value": None,
        "total_exemption_amount": None,
        "base_tax_amount": None,
        "amount_due": None,
        "total_payments_applied": None,
    }
    with store.lock:
        store.tax_bills[rec["id"]] = rec
        compute_tax_bill_fields(rec, recompute_stack=True)
    return success(serialize_tax_bill(rec), status_code=201)


@tax_bills_bp.get("/properties/<property_id>/tax_bills/<tax_bill_id>")
def get_tax_bill(property_id, tax_bill_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    rec = require_tax_bill(property_id, tax_bill_id)
    # Refresh accrued interest into amount_due before returning
    compute_tax_bill_fields(rec, recompute_stack=False)
    return success(serialize_tax_bill(rec))


@tax_bills_bp.post("/properties/<property_id>/tax_bills/<tax_bill_id>/issue")
def issue_tax_bill(property_id, tax_bill_id):
    require_roles({"Treasurer"})
    rec = require_tax_bill(property_id, tax_bill_id)
    body = get_json_body()
    if rec["status"] != "PENDING":
        raise_error("ERR_INVALID_STATE", "bill is not PENDING")
    # Linked assessment FINALIZED
    assessment = store.assessments.get(rec["assessment_id"])
    if assessment is None or assessment["status"] != "FINALIZED":
        raise_error("ERR_ASSESSMENT_NOT_FINALIZED")
    # Exemptions pending guard
    for app in store.exemption_applications.values():
        if app["property_id"] != property_id:
            continue
        if app["effective_roll_year"] != rec["roll_year"]:
            continue
        if app["status"] == "SUBMITTED":
            raise_error("ERR_EXEMPTIONS_PENDING")
    check_version(rec, body)

    with store.lock:
        now = store.clock.now()
        # Recompute first (in case exemptions changed)
        compute_tax_bill_fields(rec, recompute_stack=True)
        rec["status"] = "ISSUED"
        rec["issued_at"] = now
        rec["due_date"] = now + timedelta(days=DUE_WINDOW_DAYS)
        # amount_due locked to base_tax_amount
        rec["amount_due"] = rec["base_tax_amount"]
        bump(rec)
    return success(serialize_tax_bill(rec))


@tax_bills_bp.post("/properties/<property_id>/tax_bills/<tax_bill_id>/payments")
def apply_payment(property_id, tax_bill_id):
    require_roles({"Owner"})
    rec = require_tax_bill(property_id, tax_bill_id)
    require_owner_of_property(property_id)
    body = get_json_body()

    # State: must be in a payable status
    if rec["status"] not in ("ISSUED", "PARTIALLY_PAID", "IN_DEFERRAL", "DELINQUENT"):
        raise_error("ERR_INVALID_STATE", "bill is not in a payable state")

    amount = parse_number(require_field(body, "amount"), "amount")
    amount = round_half_up(amount, 2)
    if amount <= Decimal("0"):
        raise_error("ERR_OVERPAYMENT")

    with store.lock:
        # Refresh amount_due (accrued interest in deferral case)
        compute_tax_bill_fields(rec, recompute_stack=False)

        if rec["status"] == "IN_DEFERRAL":
            # Find ACTIVE deferral plan
            plan = None
            for d in store.deferral_plans.values():
                if d["tax_bill_id"] != rec["id"]:
                    continue
                if d["status"] == "ACTIVE":
                    plan = d
                    break
            if plan is None:
                raise_error("ERR_INVALID_STATE", "no active deferral plan")
            now = store.clock.now()
            accrued = compute_accrued_interest(plan, now)
            plan["accrued_interest"] = accrued
            payoff = round_half_up(Decimal(str(plan["principal_deferred"])) + accrued, 2)
            if amount != payoff:
                raise_error("ERR_OVERPAYMENT")
            # Apply payment
            payment = {
                "id": new_uuid(),
                "created_at": now,
                "tax_bill_id": rec["id"],
                "amount": amount,
                "applied_at": now,
                "status": "APPLIED",
                "refund_reason": None,
            }
            store.payments[payment["id"]] = payment
            # Close plan and bill
            plan["status"] = "COMPLETED"
            plan["closed_at"] = now
            bump(plan)
            rec["status"] = "PAID"
            compute_tax_bill_fields(rec, recompute_stack=False)
            bump(rec)
            return success(serialize_payment(payment), status_code=201)

        # Standard path (ISSUED, PARTIALLY_PAID, DELINQUENT)
        current_due = Decimal(str(rec["amount_due"]))
        if amount > current_due:
            raise_error("ERR_OVERPAYMENT")

        now = store.clock.now()
        payment = {
            "id": new_uuid(),
            "created_at": now,
            "tax_bill_id": rec["id"],
            "amount": amount,
            "applied_at": now,
            "status": "APPLIED",
            "refund_reason": None,
        }
        store.payments[payment["id"]] = payment

        # Recompute
        compute_tax_bill_fields(rec, recompute_stack=False)
        if rec["amount_due"] == Decimal("0"):
            rec["status"] = "PAID"
        else:
            # Stay/become PARTIALLY_PAID — even from DELINQUENT, the PRD focuses
            # on the ISSUED/PARTIALLY_PAID → PAID/PARTIALLY_PAID transitions;
            # a partial payment on a DELINQUENT bill keeps it DELINQUENT but
            # reduces amount_due. For simplicity, if any payments exist and
            # amount_due > 0, mark PARTIALLY_PAID (except DELINQUENT stays).
            if rec["status"] != "DELINQUENT":
                rec["status"] = "PARTIALLY_PAID"
        bump(rec)
        return success(serialize_payment(payment), status_code=201)


@tax_bills_bp.get("/properties/<property_id>/tax_bills/<tax_bill_id>/payments")
def list_payments(property_id, tax_bill_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    require_tax_bill(property_id, tax_bill_id)
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ("APPLIED", "REFUNDED"):
        raise_error("ERR_VALIDATION_FAILED", "status filter must be APPLIED or REFUNDED")

    items = [
        p for p in store.payments.values()
        if p["tax_bill_id"] == tax_bill_id
    ]
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: p["created_at"])

    page, pagination = paginate(items, limit, offset)
    return success([serialize_payment(p) for p in page], pagination=pagination)
