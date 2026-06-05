"""Disbursement queue (POST /disbursements). Waterfall execution lives in
purchase_agreement.close_agreement."""
from __future__ import annotations

from typing import Any

from clock import CLOCK
from db import DB_INSTANCE, new_id
from errors import (
    ERR_EXCHANGE_ROUTING_REQUIRED,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
    ERR_WIRE_NOT_LOCKED,
    err,
)
from lookup import get_fk_escrow, get_fk_wire
from validation import require_enum, require_fields, require_int, require_str


DISBURSEMENT_PURPOSES = {
    "SELLER_PROCEEDS",
    "LENDER_PAYOFF",
    "TITLE_PREMIUM",
    "EXCHANGE_FUNDS",
    "EARNEST_REFUND",
}


def create_disbursement(body: dict) -> dict:
    require_fields(body, ["escrow_account_id", "wire_instruction_id", "purpose", "amount_cents"])
    escrow_id = require_str(body, "escrow_account_id")
    wire_id = require_str(body, "wire_instruction_id")
    purpose = require_enum(body, "purpose", DISBURSEMENT_PURPOSES)
    amount = require_int(body, "amount_cents")

    # FK checks.
    e = get_fk_escrow(escrow_id)
    w = get_fk_wire(wire_id)

    # Priority 9 (business_safety): wire must be LOCKED.
    if w["status"] != "LOCKED":
        raise err(ERR_WIRE_NOT_LOCKED, "wire instruction is not LOCKED")

    # Priority 17 (business_constraint): SELLER_PROCEEDS rejected if exchange_account_id set.
    a = DB_INSTANCE.purchase_agreements.get(e["agreement_id"])
    if a is not None and a.get("exchange_account_id") is not None and purpose == "SELLER_PROCEEDS":
        raise err(ERR_EXCHANGE_ROUTING_REQUIRED, "SELLER_PROCEEDS requires EXCHANGE_FUNDS routing under 1031")

    # Amount > 0.
    if amount <= 0:
        raise err(ERR_INVALID_AMOUNT, "amount_cents must be > 0")

    now = CLOCK.now()
    disb = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "escrow_account_id": escrow_id,
        "wire_instruction_id": wire_id,
        "purpose": purpose,
        "amount_cents": amount,
        "status": "QUEUED",
    }
    DB_INSTANCE.disbursements[disb["id"]] = disb
    return disb


def list_disbursements(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.disbursements.values())
    if filters.get("escrow_account_id"):
        items = [d for d in items if d["escrow_account_id"] == filters["escrow_account_id"]]
    if filters.get("wire_instruction_id"):
        items = [d for d in items if d["wire_instruction_id"] == filters["wire_instruction_id"]]
    if filters.get("status"):
        items = [d for d in items if d["status"] == filters["status"]]
    items.sort(key=lambda d: d["created_at"])
    return items
