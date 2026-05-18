"""Claim endpoints."""

from flask import Blueprint, g

from middleware import require_auth, parse_json_body
from response import success
from services.case_engine import (
    create_claim,
    disallow_claim,
    get_case_or_404,
    get_claim_scoped_or_404,
    check_occ,
)
from services.serializers import serialize_claim
from db import store


claims_bp = Blueprint("claims", __name__)


@claims_bp.post("/cases/<case_id>/claims")
@require_auth(allowed_roles=["Creditor"])
def create_claim_route(case_id: str):
    body = parse_json_body(required_fields=["creditor_id", "claim_class", "amount_cents", "is_dischargeable"])
    with store.lock:
        case = get_case_or_404(case_id)
        claim = create_claim(
            case,
            creditor_id=body["creditor_id"],
            claim_class=body["claim_class"],
            amount_cents=body["amount_cents"],
            is_dischargeable=body["is_dischargeable"],
            acting_user_id=g.user_id,
        )
    return success(serialize_claim(claim), status=201)


@claims_bp.get("/cases/<case_id>/claims/<claim_id>")
@require_auth(allowed_roles=["Debtor", "Trustee", "Creditor", "Judge"])
def get_claim_route(case_id: str, claim_id: str):
    claim = get_claim_scoped_or_404(case_id, claim_id)
    return success(serialize_claim(claim))


@claims_bp.post("/cases/<case_id>/claims/<claim_id>/disallow")
@require_auth(allowed_roles=["Trustee"])
def disallow_claim_route(case_id: str, claim_id: str):
    body = parse_json_body()
    with store.lock:
        case = get_case_or_404(case_id)
        claim = get_claim_scoped_or_404(case_id, claim_id)
        check_occ(claim, body.get("version"))
        claim = disallow_claim(case, claim)
    return success(serialize_claim(claim))
