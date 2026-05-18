"""Transaction routes: POST /transactions (purchase OR refund) and GETs."""
from __future__ import annotations

from flask import Blueprint, g, request

from auth import is_cardholder, require_roles
from constants import ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN
from errors import err
from response import ok_object
from serializers import transaction_view
from services.account import (
    ownership_check,
    upgrade_tier_if_needed,
)
from services.earn import compute_points
from services.ledger import append_entry, recompute_balance
from services.signup_bonus import evaluate_qualification
from services.touch import touch_versioned
from store import store
from utils import fmt_iso, get_body, opt_int, parse_iso, require_int, require_str

bp = Blueprint("transactions", __name__)


_VALID_TXN_TYPES = {"PURCHASE", "REFUND"}


def _get_account_or_404(account_id: str) -> dict:
    a = store.accounts.get(account_id)
    if a is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "account_id does not resolve")
    return a


@bp.post("/transactions")
@require_roles(ROLE_CARDHOLDER)
def post_transaction():
    body = get_body(request)
    account_id = require_str(body, "account_id")
    category_id = require_str(body, "category_id")
    txn_type = require_str(body, "txn_type")
    amount_cents = require_int(body, "amount_cents")

    if txn_type not in _VALID_TXN_TYPES:
        raise err("ERR_VALIDATION", f"txn_type must be one of {sorted(_VALID_TXN_TYPES)}")
    if amount_cents < 1:
        raise err("ERR_VALIDATION", "amount_cents must be >= 1")

    original_transaction_id = body.get("original_transaction_id")

    # Body FK existence (priority 4) — account and category.
    account = _get_account_or_404(account_id)
    category = store.cashback_categories.get(category_id)
    if category is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "category_id does not resolve")

    # Ownership (priority 5)
    ownership_check(account, g.user_id)

    # State: account not CLOSED (priority 6)
    if account["lifecycle_state"] == "CLOSED":
        raise err("ERR_ACCOUNT_CLOSED", "Account is closed")

    with store.lock:
        if txn_type == "PURCHASE":
            return _post_purchase(account, category, amount_cents)
        else:
            return _post_refund(account, category, amount_cents, original_transaction_id)


def _post_purchase(account: dict, category: dict, amount_cents: int):
    now = store.now()
    iso = fmt_iso(now)

    # Step 1: compute provisional points (with current tier).
    points = compute_points(
        account=account,
        category=category,
        amount_cents=amount_cents,
        posted_at=now,
    )

    # Create the Transaction record.
    tid = store.new_id()
    txn = {
        "id": tid,
        "account_id": account["id"],
        "category_id": category["id"],
        "txn_type": "PURCHASE",
        "amount_cents": amount_cents,
        "posted_at": iso,
        "status": "POSTED",
        "points_provisional": points,
        "points_final": 0,
        "original_transaction_id": None,
        "created_at": iso,
        "updated_at": iso,
        "version": 1,
    }
    store.transactions[tid] = txn

    # Side effect: EARN ledger entry (write even when delta is 0 — PRD §3.4).
    append_entry(
        account_id=account["id"],
        entry_type="EARN",
        delta_points=points,
        source_entity_type="Transaction",
        source_entity_id=tid,
    )

    # Side effect: ytd_qualifying_spend_cents += amount_cents
    account["ytd_qualifying_spend_cents"] = (
        int(account["ytd_qualifying_spend_cents"]) + amount_cents
    )

    # Side effect: last_qualifying_activity_at := now (purchase only)
    account["last_qualifying_activity_at"] = iso

    # Side effect: tier upgrade (with backfill cascade) if a threshold crossed
    upgrade_tier_if_needed(account)

    # Side effect: signup-bonus qualification check inside the window
    deadline = parse_iso(account["signup_bonus_deadline_at"])
    opened_at = parse_iso(account["opened_at"])
    if opened_at <= now < deadline:
        evaluate_qualification(account)

    # Final balance recompute
    recompute_balance(account)

    # One overall account version bump per the PRD §2.11 cascade rule.
    touch_versioned(account)

    return ok_object(transaction_view(txn), status=201)


def _post_refund(account: dict, category: dict, amount_cents: int, original_transaction_id):
    if not original_transaction_id or not isinstance(original_transaction_id, str):
        raise err("ERR_VALIDATION", "original_transaction_id is required for REFUND")
    original = store.transactions.get(original_transaction_id)
    if original is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "original_transaction_id does not resolve")

    # State: original.status must be POSTED (priority 7) — INVALID_STATE
    if original["status"] != "POSTED":
        raise err(
            "ERR_INVALID_STATE",
            "Original transaction is not in POSTED state",
        )

    # Business referential: original must be PURCHASE on this account (priority 16)
    if original["txn_type"] != "PURCHASE" or original["account_id"] != account["id"]:
        raise err(
            "ERR_REFUND_MISMATCH",
            "original_transaction_id must refer to a PURCHASE on this account",
        )

    # Business constraint: amount parity (priority 17)
    if amount_cents != int(original["amount_cents"]):
        raise err(
            "ERR_PARTIAL_REFUND_DISALLOWED",
            "Refund amount must equal the original purchase amount",
        )

    now = store.now()
    iso = fmt_iso(now)

    # Flip the original transaction to REVERSED.
    original["status"] = "REVERSED"
    touch_versioned(original)

    # Create the refund row.
    tid = store.new_id()
    refund = {
        "id": tid,
        "account_id": account["id"],
        "category_id": category["id"],
        "txn_type": "REFUND",
        "amount_cents": amount_cents,
        "posted_at": iso,
        "status": "POSTED",
        "points_provisional": 0,
        "points_final": 0,
        "original_transaction_id": original_transaction_id,
        "created_at": iso,
        "updated_at": iso,
        "version": 1,
    }
    store.transactions[tid] = refund

    # EARN_ADJUST ledger entry of -original.points_provisional
    append_entry(
        account_id=account["id"],
        entry_type="EARN_ADJUST",
        delta_points=-int(original["points_provisional"]),
        source_entity_type="Transaction",
        source_entity_id=original["id"],
    )

    # Decrement ytd_qualifying_spend_cents by original.amount_cents
    account["ytd_qualifying_spend_cents"] = (
        int(account["ytd_qualifying_spend_cents"]) - int(original["amount_cents"])
    )

    # last_qualifying_activity_at left unchanged

    # Recompute signup-bonus qualifying spend if still inside the window.
    deadline = parse_iso(account["signup_bonus_deadline_at"])
    opened_at = parse_iso(account["opened_at"])
    if opened_at <= now < deadline:
        # Re-evaluate qualification status (might unwind a PENDING near-miss
        # but cannot claw back an AWARDED).
        from services.signup_bonus import recompute_qualifying_spend
        recompute_qualifying_spend(account)

    recompute_balance(account)
    touch_versioned(account)

    return ok_object(transaction_view(refund), status=201)


@bp.get("/transactions/<transaction_id>")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def get_transaction(transaction_id: str):
    t = store.transactions.get(transaction_id)
    if t is None:
        raise err("ERR_NOT_FOUND", "Transaction not found")

    if is_cardholder():
        account = store.accounts.get(t["account_id"])
        if account is None or account["cardholder_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "Cardholder does not own this transaction")

    return ok_object(transaction_view(t))
