"""RemittanceLine endpoints: post adjudication (the cascade), list (PRD §3.7)."""

from flask import Blueprint

from db import store
from errors import (
    ERR_DENIAL_REASON_REQUIRED,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_ENUM,
    ERR_INVALID_REQUEST,
    ERR_PAID_EXCEEDS_ALLOWED,
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
    touch,
)
from services.ledger import (
    advance_billing_dimension,
    charges_for,
    reconcile_transport_ledger,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("remittances", __name__)

OUTCOMES = {"PAID", "PARTIAL", "DENIED"}
DENIAL_REASONS = {
    "NOT_MEDICALLY_NECESSARY",
    "MISSING_PCS",
    "NON_COVERED_DESTINATION",
    "COB_PRIMARY_NOT_BILLED",
    "DUPLICATE",
}


def _base_code_for(transport_id):
    for c in charges_for(transport_id):
        if c["charge_type"] == "BASE_RATE":
            return c["hcpcs_code"]
    return None


@bp.route("/claims/<claim_id>/remittances", methods=["POST"])
def post_remittance(claim_id):
    principal = authenticate()
    require_role(principal, ["Biller"])
    claim = get_or_404(store.claims, claim_id)
    body = get_json_body()

    # priority 5: required fields
    require_fields(body, ["outcome", "paid_cents"])
    # priority 6: enum validity
    outcome = body["outcome"]
    if outcome not in OUTCOMES:
        raise err(ERR_INVALID_ENUM, "Invalid outcome")
    denial_reason = body.get("denial_reason")
    if denial_reason is not None and denial_reason not in DENIAL_REASONS:
        raise err(ERR_INVALID_ENUM, "Invalid denial_reason")

    paid_cents = body["paid_cents"]
    if not isinstance(paid_cents, int) or isinstance(paid_cents, bool):
        raise err(ERR_INVALID_REQUEST, "paid_cents must be an integer")

    # priority 11: claim must be SUBMITTED
    if claim["status"] != "SUBMITTED":
        raise err(ERR_INVALID_CLAIM_STATE, "Remittance can only be posted against a submitted claim")

    # priority 19: denial reason required iff DENIED
    if outcome == "DENIED":
        if denial_reason is None:
            raise err(ERR_DENIAL_REASON_REQUIRED, "DENIED remittance requires a denial_reason")
    else:
        if denial_reason is not None:
            raise err(ERR_DENIAL_REASON_REQUIRED, "PAID/PARTIAL remittance must not carry a denial_reason")

    transport = store.transports.get(claim["transport_id"])
    plan = store.payer_plans.get(claim["payer_plan_id"])

    reported_allowed = body.get("reported_allowed_cents")

    if outcome in ("PAID", "PARTIAL"):
        base_code = _base_code_for(claim["transport_id"])
        allowed = calc.adjudicated_allowed(
            reported_allowed_cents=reported_allowed,
            payer_type=plan["payer_type"],
            qpa_multiplier=plan.get("qpa_multiplier", 1.0),
            base_code=base_code,
            loaded_miles=transport["loaded_miles"],
            is_rural_pickup=transport.get("is_rural_pickup", False),
            total_billed_cents=transport["total_billed_cents"],
            claim_billed_cents=claim["billed_amount_cents"],
            claim_prior_paid_cents=claim["prior_paid_cents"],
        )
        # priority 20: paid_cents <= allowed
        if paid_cents > allowed:
            raise err(ERR_PAID_EXCEEDS_ALLOWED, "paid_cents exceeds the claim's allowed amount")

        contractual = calc.contractual_adjustment(
            payer_type=plan["payer_type"],
            sequence_rank=claim["sequence_rank"],
            billed_cents=claim["billed_amount_cents"],
            allowed_cents=allowed,
            prior_paid_cents=claim["prior_paid_cents"],
        )

        # create the remittance line
        line = {
            "claim_id": claim_id,
            "outcome": outcome,
            "reported_allowed_cents": reported_allowed,
            "paid_cents": paid_cents,
            "denial_reason": None,
            "contractual_adjustment_cents": contractual,
            "_allowed_applied_cents": allowed,
        }
        init_common(line)
        store.remittance_lines[line["id"]] = line

        # set claim adjudicated amounts
        claim["allowed_amount_cents"] = allowed
        claim["paid_amount_cents"] = paid_cents
        claim["status"] = "PAID"
        touch(claim)

        # create payer Payment for paid_cents
        if paid_cents > 0:
            payment = {
                "transport_id": claim["transport_id"],
                "claim_id": claim_id,
                "source": "PAYER",
                "amount_cents": paid_cents,
                "posted_iso": None,
            }
            init_common(payment)
            payment["posted_iso"] = payment["created_at"]
            store.payments[payment["id"]] = payment

    else:  # DENIED
        line = {
            "claim_id": claim_id,
            "outcome": "DENIED",
            "reported_allowed_cents": reported_allowed,
            "paid_cents": paid_cents,
            "denial_reason": denial_reason,
            "contractual_adjustment_cents": 0,
            "_allowed_applied_cents": 0,
        }
        init_common(line)
        store.remittance_lines[line["id"]] = line

        claim["allowed_amount_cents"] = 0
        claim["paid_amount_cents"] = 0
        claim["status"] = "DENIED"
        touch(claim)

    # cascade: reconcile ledger, advance billing dimension if sequence exhausted.
    reconcile_transport_ledger(transport)
    advance_billing_dimension(transport)

    return success(serialize(line), 201)


@bp.route("/claims/<claim_id>/remittances", methods=["GET"])
def list_remittances(claim_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Biller", "ComplianceOfficer"])
    get_or_404(store.claims, claim_id)
    limit, offset = parse_pagination()
    items = [r for r in store.remittance_lines.values() if r["claim_id"] == claim_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)
