"""Adjustment endpoints: apply write-offs, list (PRD §3.10)."""

from flask import Blueprint

from db import store
from errors import (
    ERR_BALANCE_BILLING_NOT_PROTECTED,
    ERR_CHARITY_INCOME_REQUIRED,
    ERR_CHARITY_NOT_QUALIFIED,
    ERR_INVALID_ENUM,
    ERR_INVALID_REQUEST,
    ERR_WRITEOFF_EXCEEDS_BALANCE,
    err,
)
from middleware import authenticate, require_role
from response import success
from services import calc
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    paginate,
    parse_pagination,
    require_fields,
)
from services.ledger import (
    advance_billing_dimension,
    payments_for,
    primary_claim,
    reconcile_transport_ledger,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("adjustments", __name__)

ADJUSTMENT_TYPES = {"CHARITY", "UNCOLLECTIBLE", "BALANCE_BILLING_CAP", "GOODWILL"}


def _is_balance_billing_protected(transport):
    """No Surprises protection test (PRD §3.10).

    Protected when primary payer is MEDICARE/MEDICAID, OR primary payer is
    COMMERCIAL/AUTO AND (plan.allows_balance_billing == false OR
    agency.base_state_is_no_surprises == true).
    """
    pc = primary_claim(transport["id"])
    if pc is None:
        return False
    plan = store.payer_plans.get(pc["payer_plan_id"])
    if plan is None:
        return False
    ptype = plan["payer_type"]
    if ptype in ("MEDICARE", "MEDICAID"):
        return True
    if ptype in ("COMMERCIAL", "AUTO"):
        agency = store.agencies.get(transport["agency_id"])
        agency_protected = bool(agency and agency.get("base_state_is_no_surprises"))
        if (not plan.get("allows_balance_billing", True)) or agency_protected:
            return True
    return False


def _primary_payer_paid(transport):
    pc = primary_claim(transport["id"])
    if pc is None:
        return 0
    return sum(
        p["amount_cents"]
        for p in payments_for(transport["id"])
        if p["source"] == "PAYER" and p.get("claim_id") == pc["id"]
    )


@bp.route("/transports/<transport_id>/adjustments", methods=["POST"])
def post_adjustment(transport_id):
    principal = authenticate()
    require_role(principal, ["ComplianceOfficer", "BillingAdmin"])
    transport = get_or_404(store.transports, transport_id)
    body = get_json_body()

    # priority 5: required fields
    require_fields(body, ["adjustment_type"])
    # priority 6: enum
    adj_type = body["adjustment_type"]
    if adj_type not in ADJUSTMENT_TYPES:
        raise err(ERR_INVALID_ENUM, "Invalid adjustment_type")

    patient_balance = transport["patient_responsibility_cents"]

    if adj_type == "CHARITY":
        patient = store.patients.get(transport["patient_id"])
        income = patient.get("annual_household_income_cents") if patient else None
        if income is None:
            raise err(ERR_CHARITY_INCOME_REQUIRED, "Patient income is required for a charity write-off")
        household_size = patient.get("household_size", 1)
        agency = store.agencies.get(transport["agency_id"])
        threshold = agency.get("charity_fpl_threshold_pct", 200) if agency else 200
        income_pct = calc.charity_income_pct_of_fpl(income, household_size)
        if income_pct > threshold:
            raise err(ERR_CHARITY_NOT_QUALIFIED, "Patient income exceeds the charity FPL threshold")
        amount = patient_balance

    elif adj_type == "BALANCE_BILLING_CAP":
        if not _is_balance_billing_protected(transport):
            raise err(ERR_BALANCE_BILLING_NOT_PROTECTED, "Balance billing is not barred for this patient")
        pc = primary_claim(transport["id"])
        allowed = pc["allowed_amount_cents"] if pc else 0
        cost_share = max(allowed - _primary_payer_paid(transport), 0)
        amount = max(patient_balance - cost_share, 0)

    else:  # UNCOLLECTIBLE / GOODWILL
        requested = body.get("requested_amount_cents")
        if requested is None:
            raise err(ERR_INVALID_REQUEST, "requested_amount_cents is required")
        if not isinstance(requested, int) or isinstance(requested, bool):
            raise err(ERR_INVALID_REQUEST, "requested_amount_cents must be an integer")
        # priority 24: requested <= patient balance
        if requested > patient_balance:
            raise err(ERR_WRITEOFF_EXCEEDS_BALANCE, "Write-off exceeds current patient balance")
        amount = requested

    rec = {
        "transport_id": transport_id,
        "adjustment_type": adj_type,
        "amount_cents": amount,
        "requested_amount_cents": body.get("requested_amount_cents"),
    }
    init_common(rec)
    store.adjustments[rec["id"]] = rec

    reconcile_transport_ledger(transport)
    advance_billing_dimension(transport)

    return success(serialize(rec), 201)


@bp.route("/transports/<transport_id>/adjustments", methods=["GET"])
def list_adjustments(transport_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "ComplianceOfficer", "Biller"])
    get_or_404(store.transports, transport_id)
    limit, offset = parse_pagination()
    items = [a for a in store.adjustments.values() if a["transport_id"] == transport_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)
