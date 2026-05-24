"""RepaymentPlan endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PLAN_FIELDS_INVALID,
    ERR_STALE_VERSION,
)
from middleware import current_role, current_user_id, require_roles
from response import success, success_list
from routes._common import (
    get_field,
    must_get,
    paginate_sorted,
    parse_json_body,
    parse_pagination,
)
from services import calc, loan_ops, serializer

bp = Blueprint("repayment_plans", __name__)

VALID_PLAN_TYPES = {"STANDARD_10YR", "IBR", "PAYE", "SAVE"}
VALID_STATES = {"CONTIGUOUS", "AK", "HI"}
IDR_PLANS = {"IBR", "PAYE", "SAVE"}

POSTABLE_LOAN_STATES_FOR_PLAN_CREATE = {"GRACE", "REPAYMENT", "DEFERMENT", "FORBEARANCE", "DELINQUENT"}


def _validate_idr_fields(plan_type, agi_cents, family_size, state_of_residence):
    if state_of_residence not in VALID_STATES:
        raise APIError(ERR_PLAN_FIELDS_INVALID, "Invalid state_of_residence")
    if plan_type == "STANDARD_10YR":
        if agi_cents is not None or family_size is not None:
            raise APIError(ERR_PLAN_FIELDS_INVALID, "STANDARD_10YR must have null agi_cents and family_size")
    elif plan_type in IDR_PLANS:
        if not isinstance(agi_cents, int) or isinstance(agi_cents, bool) or agi_cents <= 0:
            raise APIError(ERR_PLAN_FIELDS_INVALID, "agi_cents must be a positive integer for IDR plans")
        if not isinstance(family_size, int) or isinstance(family_size, bool) or family_size < 1 or family_size > 20:
            raise APIError(ERR_PLAN_FIELDS_INVALID, "family_size must be 1..20 for IDR plans")


def _clock_plus_365() -> str:
    today = datetime.strptime(db.get_clock_date(), "%Y-%m-%d").date()
    return (today + timedelta(days=365)).strftime("%Y-%m-%d")


@bp.post("/v1/repayment-plans")
@require_roles({"LoanServicer", "Borrower"})
def create_plan():
    body = parse_json_body()
    loan_id = get_field(body, "loan_id")
    plan_type = get_field(body, "plan_type")
    state_of_residence = get_field(body, "state_of_residence")
    expected_loan_version = get_field(body, "expected_loan_version")
    agi_cents = body.get("agi_cents")
    family_size = body.get("family_size")

    # Existence (priority 20) first
    loan = must_get(db.loans, loan_id, "Loan")

    # Ownership for Borrower role
    if current_role() == "Borrower":
        if loan["borrower_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this loan")

    if plan_type not in VALID_PLAN_TYPES:
        raise APIError(ERR_PLAN_FIELDS_INVALID, "Invalid plan_type")

    # Priority 21: state precondition — loan must be in postable state
    if loan["status"] not in POSTABLE_LOAN_STATES_FOR_PLAN_CREATE:
        raise APIError(ERR_INVALID_STATE, "Loan not in plan-createable state")

    # Priority 25: field validations
    _validate_idr_fields(plan_type, agi_cents, family_size, state_of_residence)

    # OCC (priority 40) — last gate
    if not isinstance(expected_loan_version, int) or isinstance(expected_loan_version, bool):
        raise APIError(ERR_INVALID_REQUEST, "expected_loan_version must be int")
    if expected_loan_version != loan["version"]:
        raise APIError(ERR_STALE_VERSION, "expected_loan_version mismatch")

    # Compute monthly_payment_cents
    monthly = calc.plan_monthly_payment(
        plan_type,
        loan["outstanding_principal_cents"],
        loan["interest_rate_bps"],
        agi_cents,
        family_size,
        state_of_residence,
    )

    # Supersede any existing ACTIVE plan
    prior = serializer.active_plan_for_loan(loan_id)
    if prior:
        prior["status"] = "SUPERSEDED"
        prior["terminated_on_clock"] = db.get_clock_date()
        serializer.bump_plan(prior)

    pid = db.new_id()
    now = db.now_iso()
    cert_expires = _clock_plus_365() if plan_type in IDR_PLANS else None
    plan = {
        "id": pid,
        "loan_id": loan_id,
        "plan_type": plan_type,
        "agi_cents": agi_cents,
        "family_size": family_size,
        "state_of_residence": state_of_residence,
        "monthly_payment_cents": monthly,
        "status": "ACTIVE",
        "certification_expires_on": cert_expires,
        "created_at": now,
        "updated_at": now,
        # Simulation-clock activation date — used by PSLF qualifying-payment date checks
        # and by clock-advance delinquency-cycle generation. Not exposed in serialized form.
        "activated_on_clock": db.get_clock_date(),
        "terminated_on_clock": None,
        "version": 1,
    }
    db.repayment_plans[pid] = plan
    # Plan creation bumps the loan's version (side effect per scaffold §1.5)
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])

    return success(serializer.serialize_plan(plan), status=201)


@bp.post("/v1/repayment-plans/<plan_id>/recertify")
@require_roles({"LoanServicer", "Borrower"})
def recertify_plan(plan_id):
    plan = must_get(db.repayment_plans, plan_id, "RepaymentPlan")
    loan = must_get(db.loans, plan["loan_id"], "Loan")
    if current_role() == "Borrower":
        if loan["borrower_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this loan")
    body = parse_json_body()
    agi_cents = get_field(body, "agi_cents")
    family_size = get_field(body, "family_size")

    # Only IDR plans can be recertified meaningfully
    if plan["plan_type"] not in IDR_PLANS:
        raise APIError(ERR_INVALID_STATE, "Only IDR plans can be recertified")
    if plan["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "Plan is not ACTIVE")

    _validate_idr_fields(plan["plan_type"], agi_cents, family_size, plan["state_of_residence"])

    monthly = calc.plan_monthly_payment(
        plan["plan_type"],
        loan["outstanding_principal_cents"],
        loan["interest_rate_bps"],
        agi_cents,
        family_size,
        plan["state_of_residence"],
    )
    plan["agi_cents"] = agi_cents
    plan["family_size"] = family_size
    plan["monthly_payment_cents"] = monthly
    plan["certification_expires_on"] = _clock_plus_365()
    serializer.bump_plan(plan)
    return success(serializer.serialize_plan(plan), status=200)


@bp.get("/v1/repayment-plans/<plan_id>")
@require_roles({"LoanServicer", "PSLFAdjudicator", "Borrower"})
def get_plan(plan_id):
    plan = must_get(db.repayment_plans, plan_id, "RepaymentPlan")
    if current_role() == "Borrower":
        loan = db.loans.get(plan["loan_id"])
        if not loan or loan["borrower_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this plan")
    return success(serializer.serialize_plan(plan), status=200)


@bp.get("/v1/repayment-plans")
@require_roles({"LoanServicer", "PSLFAdjudicator", "Borrower"})
def list_plans():
    limit, offset = parse_pagination()
    loan_filter = request.args.get("loan_id")
    status_filter = request.args.get("status")
    items = list(db.repayment_plans.values())
    if current_role() == "Borrower":
        own_loan_ids = {l["id"] for l in db.loans.values() if l["borrower_id"] == current_user_id()}
        items = [p for p in items if p["loan_id"] in own_loan_ids]
    if loan_filter:
        items = [p for p in items if p["loan_id"] == loan_filter]
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: p["created_at"])
    page, total = paginate_sorted(items, limit, offset)
    return success_list([serializer.serialize_plan(p) for p in page], limit, offset, total)
