"""Deferral agreement endpoints: open, enroll-bill, accrue, payments, default.

Implements PRD §3.9: declining-balance interest, interest-first payment
waterfall, OCC on agreement version (§2.7), and the auto SATISFIED transition.
"""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import object_response, array_response
from routes.exemptions import _age_in_years
from services.calc import period_interest_cents, payment_waterfall
from services.common import (
    get_body, require_fields, lookup, parse_pagination, paginate, is_number,
    is_int, recompute_outstanding,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("deferrals", __name__)

# PRD §3.9 requires the deferral owner be "senior- or disability-eligible".
# A DeferralAgreement is not tied to a tax roll, so there is no per-roll
# senior_age_threshold in scope; the default threshold (65, per §3.1) is used
# for the standalone senior test. Disability-eligible == disability_pct >= 1.
DEFAULT_SENIOR_AGE = 65


@bp.post("/deferrals")
def create_deferral():
    require_roles(["Assessor"])
    body = get_body()
    require_fields(body, ["parcel_id", "owner_id", "annual_interest_rate"])
    parcel_id = body["parcel_id"]
    owner_id = body["owner_id"]
    rate = body["annual_interest_rate"]
    if not isinstance(parcel_id, str) or not isinstance(owner_id, str):
        raise err("ERR_INVALID_REQUEST", "parcel_id/owner_id must be strings")
    if not is_number(rate) or rate < 0 or rate > 1:
        raise err("ERR_INVALID_REQUEST", "annual_interest_rate must be between 0 and 1")

    with db.LOCK:
        lookup(db.parcels, parcel_id)
        owner = lookup(db.owners, owner_id)

        age = _age_in_years(owner["birth_date"])
        senior_eligible = age is not None and age >= DEFAULT_SENIOR_AGE
        disability_eligible = owner["disability_pct"] >= 1
        if not (senior_eligible or disability_eligible):
            raise err("ERR_EXEMPTION_INELIGIBLE",
                      "Owner is neither senior- nor disability-eligible")

        record = {
            "parcel_id": parcel_id,
            "owner_id": owner_id,
            "annual_interest_rate": rate,
            "deferred_principal_cents": 0,
            "accrued_interest_cents": 0,
            "outstanding_balance_cents": 0,
            "total_paid_cents": 0,
            "status": "ACTIVE",
            # Internal waterfall bookkeeping (not serialized):
            "interest_paid_cents": 0,
            "principal_paid_cents": 0,
        }
        db.init_common(record)
        db.deferral_agreements[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/deferrals")
def list_deferrals():
    require_roles(["Assessor", "Reviewer", "Taxpayer"])
    limit, offset = parse_pagination()
    parcel_id = request.args.get("parcel_id")
    owner_id = request.args.get("owner_id")
    items = list(db.deferral_agreements.values())
    if parcel_id is not None:
        items = [d for d in items if d["parcel_id"] == parcel_id]
    if owner_id is not None:
        items = [d for d in items if d["owner_id"] == owner_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


@bp.get("/deferrals/<deferral_id>")
def get_deferral(deferral_id):
    require_roles(["Assessor", "Reviewer", "Taxpayer"])
    return object_response(serialize(lookup(db.deferral_agreements, deferral_id)), 200)


@bp.post("/deferrals/<deferral_id>/enroll-bill")
def enroll_bill(deferral_id):
    require_roles(["Assessor"])
    body = get_body()
    require_fields(body, ["tax_bill_id"])
    tax_bill_id = body["tax_bill_id"]
    if not isinstance(tax_bill_id, str):
        raise err("ERR_INVALID_REQUEST", "tax_bill_id must be a string")

    with db.LOCK:
        agreement = lookup(db.deferral_agreements, deferral_id)
        bill = lookup(db.tax_bills, tax_bill_id)
        if agreement["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Deferral is not ACTIVE")
        if bill["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Bill is not ISSUED")

        bill["status"] = "DEFERRED"
        bill["is_deferred"] = True
        db.touch(bill)

        agreement["deferred_principal_cents"] += bill["tax_amount_cents"]
        recompute_outstanding(agreement)
        db.touch(agreement)
    return object_response(serialize(agreement), 200)


@bp.post("/deferrals/<deferral_id>/accrue-interest")
def accrue_interest(deferral_id):
    require_roles(["Assessor"])
    with db.LOCK:
        agreement = lookup(db.deferral_agreements, deferral_id)
        if agreement["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Deferral is not ACTIVE")
        period = period_interest_cents(
            agreement["deferred_principal_cents"],
            agreement["principal_paid_cents"],
            agreement["annual_interest_rate"],
        )
        agreement["accrued_interest_cents"] += period
        recompute_outstanding(agreement)
        db.touch(agreement)
    return object_response(serialize(agreement), 200)


@bp.post("/deferrals/<deferral_id>/payments")
def apply_payment(deferral_id):
    user_id, role = require_roles(["Assessor", "Taxpayer"])
    body = get_body()
    require_fields(body, ["amount_cents", "expected_deferral_version"])
    amount_cents = body["amount_cents"]
    expected_version = body["expected_deferral_version"]
    if not is_int(amount_cents) or amount_cents < 1:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be an integer >= 1")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err("ERR_INVALID_REQUEST", "expected_deferral_version must be an integer")

    with db.LOCK:
        agreement = lookup(db.deferral_agreements, deferral_id)

        # Taxpayer resource ownership (priority 5): a paying Taxpayer must be
        # the agreement's owner. Assessor may pay on their behalf.
        if role == "Taxpayer" and user_id != agreement["owner_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Taxpayer is not the deferral owner")

        # OCC (priority 6) — before any state/business check.
        if expected_version != agreement["version"]:
            raise err("ERR_STALE_VERSION", "Deferral version has advanced")

        if agreement["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Deferral is not ACTIVE")

        # Overpayment beyond the full outstanding balance is rejected.
        if amount_cents > agreement["outstanding_balance_cents"]:
            raise err("ERR_PAYMENT_EXCEEDS_BALANCE",
                      "Payment exceeds outstanding balance")

        to_interest, to_principal = payment_waterfall(
            amount_cents,
            agreement["accrued_interest_cents"],
            agreement["interest_paid_cents"],
            agreement["deferred_principal_cents"],
            agreement["principal_paid_cents"],
        )

        agreement["interest_paid_cents"] += to_interest
        agreement["principal_paid_cents"] += to_principal
        agreement["total_paid_cents"] += to_interest + to_principal
        recompute_outstanding(agreement)

        payment = {
            "deferral_agreement_id": deferral_id,
            "amount_cents": amount_cents,
            "applied_to_interest_cents": to_interest,
            "applied_to_principal_cents": to_principal,
        }
        db.init_event(payment)
        db.deferral_payments[payment["id"]] = payment

        # Auto SATISFIED when balance reaches exactly 0.
        if agreement["outstanding_balance_cents"] == 0:
            agreement["status"] = "SATISFIED"
        db.touch(agreement)
    return object_response(serialize(payment), 201)


@bp.post("/deferrals/<deferral_id>/default")
def default_deferral(deferral_id):
    require_roles(["Assessor"])
    with db.LOCK:
        agreement = lookup(db.deferral_agreements, deferral_id)
        if agreement["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Deferral is not ACTIVE")
        parcel = db.parcels[agreement["parcel_id"]]
        if parcel["status"] != "SOLD":
            raise err("ERR_INVALID_STATE", "Parcel is not SOLD")
        agreement["status"] = "DEFAULTED"
        db.touch(agreement)
    return object_response(serialize(agreement), 200)


@bp.get("/deferrals/<deferral_id>/payments")
def list_payments(deferral_id):
    require_roles(["Assessor", "Reviewer", "Taxpayer"])
    lookup(db.deferral_agreements, deferral_id)
    limit, offset = parse_pagination()
    items = [p for p in db.deferral_payments.values()
             if p["deferral_agreement_id"] == deferral_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)
