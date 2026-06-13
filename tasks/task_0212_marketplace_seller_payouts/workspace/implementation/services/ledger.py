"""Ledger postings, balance reconciliation, and risk-score recompute.

PRD §2.6 (reconciliation), §3.10 (risk score / tiers).
A LedgerEntry carries only id + created_at (PRD §2.4: append-only fact records,
no updated_at, no version).
"""
from common import round_half_up
from db import db

# source_type enum (SCAFFOLD LedgerEntry.source_type)
SOURCE_TYPES = {
    "ORDER_PROCEEDS",
    "REFUND_CLAWBACK",
    "CHARGEBACK_CLAWBACK",
    "CHARGEBACK_FEE",
    "RESERVE_HOLD",
    "RESERVE_RELEASE",
    "PAYOUT",
}

# hold_state enum
HOLD_PENDING = "PENDING"
HOLD_AVAILABLE = "AVAILABLE"
HOLD_REVERSED = "REVERSED"


def post_ledger_entry(seller_id, source_type, source_id, amount_cents, hold_state, memo):
    """Append an immutable ledger entry. Returns the created entry."""
    entry_id = db.new_id()
    entry = {
        "id": entry_id,
        "seller_id": seller_id,
        "source_type": source_type,
        "source_id": source_id,
        "amount_cents": amount_cents,
        "hold_state": hold_state,
        "memo": memo,
        "created_at": db.now_iso(),
    }
    db.ledger_entries[entry_id] = entry
    return entry


def seller_ledger_entries(seller_id):
    return [e for e in db.ledger_entries.values() if e["seller_id"] == seller_id]


def sum_available_ledger(seller_id):
    """Sum of AVAILABLE-hold ledger amounts for the seller (PRD §2.6, §3.9)."""
    return sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["seller_id"] == seller_id and e["hold_state"] == HOLD_AVAILABLE
    )


def sum_pending_ledger(seller_id):
    return sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["seller_id"] == seller_id and e["hold_state"] == HOLD_PENDING
    )


def reconcile_balances(seller):
    """Recompute and persist the seller's derived balances (PRD §2.6).

    available_balance_cents = sum(AVAILABLE ledger amounts) - reserve_held_cents
    pending_balance_cents   = sum(PENDING ledger amounts)
    reserve_held_cents      = sum of held_amount_cents over OPEN reserves
    May be negative."""
    seller_id = seller["id"]
    reserve_held = sum(
        r["held_amount_cents"]
        for r in db.reserves.values()
        if r["seller_id"] == seller_id and r["reserve_status"] == "OPEN"
    )
    seller["reserve_held_cents"] = reserve_held
    seller["available_balance_cents"] = sum_available_ledger(seller_id) - reserve_held
    seller["pending_balance_cents"] = sum_pending_ledger(seller_id)


# ---- Risk score & tier (PRD §3.10) --------------------------------------
W_CB = 0.6
W_REF = 0.25
W_DISP = 0.15


def recompute_risk(seller):
    """Recompute seller_risk_score and risk_tier (PRD §3.10).

    Each rate = count / max(1, order count). raw = 100 * weighted sum.
    score = round_half_up(min(100, raw)) — rounded once at the end."""
    seller_id = seller["id"]
    order_count = sum(1 for o in db.orders.values() if o["seller_id"] == seller_id)
    denom = max(1, order_count)

    cb_count = sum(
        1 for c in db.chargebacks.values()
        if c["seller_id"] == seller_id
        and c["chargeback_status"] in ("RECEIVED", "REPRESENTED", "LOST")
    )
    ref_count = sum(
        1 for r in db.refunds.values()
        if r["seller_id"] == seller_id and r["refund_status"] == "APPLIED"
    )
    disp_count = sum(
        1 for d in db.disputes.values()
        if d["seller_id"] == seller_id and d["dispute_status"] == "GRANTED"
    )

    chargeback_rate = cb_count / denom
    refund_rate = ref_count / denom
    dispute_rate = disp_count / denom

    raw = 100 * (W_CB * chargeback_rate + W_REF * refund_rate + W_DISP * dispute_rate)
    score = round_half_up(min(100, raw))
    seller["seller_risk_score"] = score

    # risk_tier thresholds (PRD §3.10): <20 STANDARD; 20..<50 ELEVATED; >=50 HIGH
    if score < 20:
        seller["risk_tier"] = "STANDARD"
    elif score < 50:
        seller["risk_tier"] = "ELEVATED"
    else:
        seller["risk_tier"] = "HIGH"


def recompute_ytd(seller):
    """Year-to-date settled gross & count on the seller record (PRD §3.11).

    Sum of Order.gross_amount_cents for AVAILABLE/PAID settlement orders in the
    tax year. We track the current logical year."""
    seller_id = seller["id"]
    year = db.now().year
    orders = [
        o for o in db.orders.values()
        if o["seller_id"] == seller_id
        and o["settlement_status"] in ("AVAILABLE", "PAID")
        and o.get("settled_at")
        and o["settled_at"][:4] == str(year)
    ]
    seller["ytd_gross_cents"] = sum(o["gross_amount_cents"] for o in orders)
    seller["ytd_transaction_count"] = len(orders)
