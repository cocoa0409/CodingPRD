"""/pbm/copay-cards — Copay card lifecycle."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_roles
from ..envelope import success
from ..errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
    ERR_VALIDATION,
)
from ..store import STORE
from ..validation import (
    as_nonneg_int,
    check_version,
    get_json_body,
    require_field,
)

bp = Blueprint("copay_cards", __name__)


def serialize_card(c: dict) -> dict:
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "drug_id": c["drug_id"],
        "max_benefit_cents": c["max_benefit_cents"],
        "per_claim_cap_cents": c["per_claim_cap_cents"],
        "used_cents": c["used_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/pbm/copay-cards")
@require_roles("PBMAdmin")
def create_card():
    body = get_json_body()
    member_id = require_field(body, "member_id")
    drug_id = require_field(body, "drug_id")
    max_benefit = as_nonneg_int(require_field(body, "max_benefit_cents"), "max_benefit_cents")
    per_claim_cap = as_nonneg_int(require_field(body, "per_claim_cap_cents"), "per_claim_cap_cents")
    if per_claim_cap > max_benefit:
        raise APIError(ERR_VALIDATION, "per_claim_cap_cents must be <= max_benefit_cents", 422)

    with STORE.lock:
        if member_id not in STORE.members:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Member {member_id} not found", 404)
        if drug_id not in STORE.drugs:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Drug {drug_id} not found", 404)
        card = STORE.init_common_fields({
            "member_id": member_id,
            "drug_id": drug_id,
            "max_benefit_cents": max_benefit,
            "per_claim_cap_cents": per_claim_cap,
            "used_cents": 0,
            "status": "ACTIVE",
        })
        STORE.copay_cards[card["id"]] = card
    return success(serialize_card(card), status=201)


@bp.get("/pbm/copay-cards/<cid>")
@require_roles("PBMAdmin", "ClaimsAdjudicator")
def get_card(cid: str):
    with STORE.lock:
        card = STORE.copay_cards.get(cid)
    if card is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, f"CopayCard {cid} not found", 404)
    return success(serialize_card(card))


@bp.post("/pbm/copay-cards/<cid>/terminate")
@require_roles("PBMAdmin")
def terminate_card(cid: str):
    body = get_json_body()
    with STORE.lock:
        card = STORE.copay_cards.get(cid)
        if card is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"CopayCard {cid} not found", 404)
        if card["status"] not in ("ACTIVE", "EXHAUSTED"):
            raise APIError(
                ERR_INVALID_STATE,
                f"Card must be ACTIVE or EXHAUSTED to terminate; current={card['status']}",
                409,
            )
        check_version(body, card)
        card["status"] = "TERMINATED"
        STORE.bump(card)
        return success(serialize_card(card))
