"""EarnestMoneyDeposit service — create / confirm (with funding cascade)."""
from __future__ import annotations

from typing import Any

from clock import CLOCK
from db import DB_INSTANCE, new_id
from errors import (
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    err,
)
from lookup import get_deposit_or_404, get_fk_escrow
from validation import require_enum, require_fields, require_int, require_str


def _recompute_received(agreement_id: str) -> int:
    total = 0
    for d in DB_INSTANCE.earnest_money_deposits.values():
        e = DB_INSTANCE.escrow_accounts.get(d["escrow_account_id"])
        if e is None or e["agreement_id"] != agreement_id:
            continue
        if d["status"] == "CONFIRMED":
            total += d["amount_cents"]
    return total


def _recompute_balance(escrow_id: str) -> int:
    confirmed = 0
    for d in DB_INSTANCE.earnest_money_deposits.values():
        if d["escrow_account_id"] == escrow_id and d["status"] == "CONFIRMED":
            confirmed += d["amount_cents"]
    disbursed = 0
    for d in DB_INSTANCE.disbursements.values():
        if d["escrow_account_id"] == escrow_id and d["status"] == "DISBURSED":
            disbursed += d["amount_cents"]
    return confirmed - disbursed


def create_deposit(body: dict) -> dict:
    require_fields(body, ["escrow_account_id", "amount_cents", "depositor_role"])
    escrow_id = require_str(body, "escrow_account_id")
    amount = require_int(body, "amount_cents")
    depositor_role = require_enum(body, "depositor_role", {"BUYER", "BUYERS_AGENT"})

    # FK check (priority 4).
    e = get_fk_escrow(escrow_id)

    # Priority 18 business constraint: amount_cents must be > 0.
    if amount <= 0:
        raise err(ERR_INVALID_AMOUNT, "amount_cents must be > 0")

    # PRD §3.1: deposits are taken while the agreement is ACTIVE.
    agreement = DB_INSTANCE.purchase_agreements.get(e["agreement_id"])
    if agreement is None or agreement["status"] not in ("ACTIVE", "UNDER_CONTRACT"):
        raise err(ERR_INVALID_STATE, "agreement must be ACTIVE to accept earnest money deposits")

    now = CLOCK.now()
    deposit = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "escrow_account_id": escrow_id,
        "amount_cents": amount,
        "depositor_role": depositor_role,
        "confirmation_reference": None,
        "status": "PENDING",
    }
    DB_INSTANCE.earnest_money_deposits[deposit["id"]] = deposit
    return deposit


def confirm_deposit(deposit_id: str, body: dict) -> dict:
    d = get_deposit_or_404(deposit_id)
    if d["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "deposit is not PENDING")

    confirmation_reference = body.get("confirmation_reference")
    if not isinstance(confirmation_reference, str) or confirmation_reference == "":
        raise err(ERR_INVALID_REQUEST, "confirmation_reference must be a non-empty string")

    d["confirmation_reference"] = confirmation_reference
    d["status"] = "CONFIRMED"
    d["updated_at"] = CLOCK.now()
    d["version"] += 1

    e = DB_INSTANCE.escrow_accounts[d["escrow_account_id"]]
    a = DB_INSTANCE.purchase_agreements[e["agreement_id"]]

    # Cascade: recompute earnest_money_received_cents and bubble status if threshold met.
    a["earnest_money_received_cents"] = _recompute_received(a["id"])
    e["balance_cents"] = _recompute_balance(e["id"])

    if a["status"] == "ACTIVE" and a["earnest_money_received_cents"] >= a["earnest_money_required_cents"]:
        a["status"] = "UNDER_CONTRACT"
        a["version"] += 1
        a["updated_at"] = CLOCK.now()
        e["status"] = "FUNDED"
        e["version"] += 1
        e["updated_at"] = CLOCK.now()

    return d


def list_deposits(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.earnest_money_deposits.values())
    escrow_q = filters.get("escrow_account_id")
    status_q = filters.get("status")
    if escrow_q:
        items = [d for d in items if d["escrow_account_id"] == escrow_q]
    if status_q:
        items = [d for d in items if d["status"] == status_q]
    items.sort(key=lambda d: d["created_at"])
    return items
