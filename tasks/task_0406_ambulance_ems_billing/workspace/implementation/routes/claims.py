"""Claim endpoints: submit (primary / secondary / tertiary / rebill with OCC),
appeal, resubmit, fetch, list (PRD §3.6, §3.8)."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_DOCUMENTATION_INCOMPLETE,
    ERR_INVALID_BILLING_STATE,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_REQUEST,
    ERR_MEDICAL_NECESSITY_NOT_MET,
    ERR_PAYER_PLAN_INACTIVE,
    ERR_PAYER_SEQUENCE_MISMATCH,
    ERR_PCS_MISSING,
    ERR_PRIOR_CLAIM_NOT_ADJUDICATED,
    ERR_STALE_TRANSPORT_VERSION,
    err,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    paginate,
    parse_pagination,
    require_fields,
    resolve_fk,
    touch,
)
from services.ledger import claims_for
from services.serialize import serialize, serialize_list
from services.transport import pcs_requirement

bp = Blueprint("claims", __name__)


def _cob_prior_paid(transport_id, new_rank):
    """Sum paid_amount_cents over PAID claims with sequence_rank < new_rank."""
    return sum(
        c["paid_amount_cents"]
        for c in claims_for(transport_id)
        if c["status"] == "PAID" and c["sequence_rank"] < new_rank
    )


@bp.route("/transports/<transport_id>/claims", methods=["POST"])
def submit_claim(transport_id):
    principal = authenticate()
    require_role(principal, ["Biller"])
    # priority 3: path existence
    transport = get_or_404(store.transports, transport_id)
    body = get_json_body()

    # priority 4: body FK existence
    if body.get("payer_plan_id") is not None:
        plan = resolve_fk(store.payer_plans, body["payer_plan_id"])
    else:
        plan = None
    prior_claim = None
    if body.get("prior_claim_id") is not None:
        prior_claim = resolve_fk(store.claims, body["prior_claim_id"])

    # priority 5: required fields
    require_fields(body, ["payer_plan_id", "expected_transport_version"])
    if not isinstance(body["expected_transport_version"], int) or isinstance(
        body["expected_transport_version"], bool
    ):
        raise err(ERR_INVALID_REQUEST, "expected_transport_version must be an integer")

    is_primary = body.get("prior_claim_id") is None
    existing_claims = claims_for(transport_id)
    rank1_claims = [c for c in existing_claims if c["sequence_rank"] == 1]
    rank1_live = [c for c in rank1_claims if c["status"] != "CLOSED"]
    has_higher_rank = any(c["sequence_rank"] > 1 for c in existing_claims)

    # priority 10: billing state admissibility
    if is_primary:
        if transport["billing_status"] == "UNBILLED":
            mode = "first_primary"
        elif transport["billing_status"] == "BILLING_IN_PROGRESS":
            mode = "primary_rebill"
        else:
            raise err(ERR_INVALID_BILLING_STATE, "Billing status does not admit a new primary claim")
    else:
        # secondary/tertiary requires an in-progress billing dimension
        if transport["billing_status"] != "BILLING_IN_PROGRESS":
            raise err(ERR_INVALID_BILLING_STATE, "Billing status does not admit a downstream claim")
        mode = "downstream"

    # priority 11: claim state admissibility (primary rebill)
    if mode == "primary_rebill":
        target = rank1_live[-1] if rank1_live else None
        if target is None or target["status"] not in ("SUBMITTED", "DENIED"):
            raise err(ERR_INVALID_CLAIM_STATE, "Primary claim cannot be rebilled in its current state")
        if has_higher_rank:
            raise err(ERR_INVALID_CLAIM_STATE, "Primary cannot be rebilled once a secondary exists")

    # priority 13: documentation complete (cross-dimension guard)
    if transport["documentation_status"] != "DOCUMENTATION_COMPLETE":
        raise err(ERR_DOCUMENTATION_INCOMPLETE, "Documentation is not complete")

    # priority 14: medical necessity
    if not transport["medical_necessity_met"]:
        raise err(ERR_MEDICAL_NECESSITY_NOT_MET, "Medical necessity not met")

    # priority 15: PCS missing when required
    if pcs_requirement(transport) == "REQUIRED" and not transport["pcs_signed"]:
        raise err(ERR_PCS_MISSING, "PCS signature required but not recorded")

    # priority 16: named payer plan ACTIVE
    if plan["status"] != "ACTIVE":
        raise err(ERR_PAYER_PLAN_INACTIVE, "Named payer plan is inactive")

    # Determine sequence rank.
    if is_primary:
        sequence_rank = 1
    else:
        sequence_rank = prior_claim["sequence_rank"] + 1

    # priority 17: prior claim adjudicated (downstream only)
    if not is_primary:
        if prior_claim["transport_id"] != transport_id or prior_claim["status"] not in ("PAID", "DENIED"):
            raise err(ERR_PRIOR_CLAIM_NOT_ADJUDICATED, "Prior claim is not an adjudicated claim of this transport")

    # priority 18: payer sequence match (downstream only)
    if not is_primary:
        patient = store.patients.get(transport["patient_id"])
        coverages = (patient.get("coverages") if patient else None) or []
        match = next((cov for cov in coverages if cov.get("policy_rank") == sequence_rank), None)
        if match is None or match.get("payer_plan_id") != body["payer_plan_id"]:
            raise err(ERR_PAYER_SEQUENCE_MISMATCH, "Payer does not match coverage at this policy rank")

    # priority 25: OCC stale version
    if body["expected_transport_version"] != transport["version"]:
        raise err(ERR_STALE_TRANSPORT_VERSION, "expected_transport_version does not match current version")

    # ---- All checks passed: create the claim ----
    if mode == "primary_rebill":
        # supersede the prior primary
        target = rank1_live[-1]
        target["status"] = "CLOSED"
        touch(target)

    prior_paid = _cob_prior_paid(transport_id, sequence_rank)
    claim = {
        "transport_id": transport_id,
        "payer_plan_id": body["payer_plan_id"],
        "prior_claim_id": body.get("prior_claim_id"),
        "sequence_rank": sequence_rank,
        "billed_amount_cents": transport["total_billed_cents"],
        "prior_paid_cents": prior_paid,
        "allowed_amount_cents": 0,
        "paid_amount_cents": 0,
        "status": "SUBMITTED",
    }
    init_common(claim)
    store.claims[claim["id"]] = claim

    if mode == "first_primary":
        transport["billing_status"] = "BILLING_IN_PROGRESS"
    # increment transport version by 1 (primary create + rebill).
    if is_primary:
        touch(transport)

    return success(serialize(claim), 201)


@bp.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Biller", "ComplianceOfficer"])
    rec = get_or_404(store.claims, claim_id)
    return success(serialize(rec), 200)


@bp.route("/transports/<transport_id>/claims", methods=["GET"])
def list_transport_claims(transport_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Biller", "ComplianceOfficer"])
    get_or_404(store.transports, transport_id)
    limit, offset = parse_pagination()
    items = claims_for(transport_id)
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)


@bp.route("/claims", methods=["GET"])
def list_claims():
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Biller", "ComplianceOfficer"])
    limit, offset = parse_pagination()
    prior_claim_id = request.args.get("prior_claim_id")
    payer_plan_id = request.args.get("payer_plan_id")
    items = list(store.claims.values())
    if prior_claim_id is not None:
        items = [c for c in items if c.get("prior_claim_id") == prior_claim_id]
    if payer_plan_id is not None:
        items = [c for c in items if c["payer_plan_id"] == payer_plan_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)


@bp.route("/claims/<claim_id>/appeal", methods=["POST"])
def appeal_claim(claim_id):
    principal = authenticate()
    require_role(principal, ["Biller"])
    claim = get_or_404(store.claims, claim_id)
    # admitted only when DENIED and a resolvable denial reason exists.
    if claim["status"] != "DENIED":
        raise err(ERR_INVALID_CLAIM_STATE, "Only a denied claim may be appealed")
    has_denied_line = any(
        r["claim_id"] == claim_id and r["outcome"] == "DENIED"
        for r in store.remittance_lines.values()
    )
    if not has_denied_line:
        raise err(ERR_INVALID_CLAIM_STATE, "No resolvable denial reason for this claim")
    claim["status"] = "APPEALED"
    touch(claim)
    return success(serialize(claim), 200)


@bp.route("/claims/<claim_id>/resubmit", methods=["POST"])
def resubmit_claim(claim_id):
    principal = authenticate()
    require_role(principal, ["Biller"])
    claim = get_or_404(store.claims, claim_id)
    if claim["status"] != "APPEALED":
        raise err(ERR_INVALID_CLAIM_STATE, "Only an appealed claim may be resubmitted")
    claim["allowed_amount_cents"] = 0
    claim["paid_amount_cents"] = 0
    claim["status"] = "SUBMITTED"
    touch(claim)
    return success(serialize(claim), 200)
