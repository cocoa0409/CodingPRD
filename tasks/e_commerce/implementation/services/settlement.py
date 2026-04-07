"""Settlement lifecycle service."""

from datetime import datetime, timezone

import db
from errors import (
    ERR_SETTLEMENT_NOT_APPROVED,
    ERR_SETTLEMENT_NOT_DISPUTED_STATE,
    ERR_SETTLEMENT_NOT_DRAFT,
    ERR_SETTLEMENT_NOT_FOUND,
    ERR_SETTLEMENT_NOT_PENDING,
    ERR_SETTLEMENT_PERIOD_OVERLAP,
    ERR_SETTLEMENT_RECONCILIATION_MISMATCH,
    ERR_SETTLEMENT_ZERO_AMOUNT,
    raise_error,
)
from money import round_money
from services.shop import get_shop


def _normalize_iso_timestamp(ts):
    """Normalize an ISO 8601 timestamp to the format YYYY-MM-DDTHH:MM:SS.mmmZ."""
    if not ts:
        return ts
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (ValueError, AttributeError):
        return ts


def _get_settlement(shop_id, settlement_id):
    settlement = db.find_one("settlements", id=settlement_id, shop_id=shop_id)
    if not settlement:
        raise_error(ERR_SETTLEMENT_NOT_FOUND, f"Settlement {settlement_id} not found.")
    return settlement


def _calculate_period_amounts(shop_id, period_start, period_end):
    """Calculate gross, commission, refunds, and net for a date range."""
    orders, _ = db.find("orders", filters={"shop_id": shop_id})
    # Filter orders completed in the period
    period_orders = [
        o for o in orders
        if o.get("order_status") == "COMPLETED"
        and o.get("created_at", "") >= period_start
        and o.get("created_at", "") <= period_end
    ]

    gross_amount = round_money(sum(o.get("total_amount", 0) for o in period_orders))
    total_commission = round_money(
        sum(o.get("commission_amount", 0) for o in period_orders)
    )

    # Refunds processed in the period
    refunds = db.find_many("refunds", shop_id=shop_id, status="PROCESSED")
    period_refunds = [
        r for r in refunds
        if r.get("created_at", "") >= period_start
        and r.get("created_at", "") <= period_end
    ]
    total_refunds = round_money(sum(r.get("refund_amount", 0) for r in period_refunds))

    net_amount = round_money(gross_amount - total_commission - total_refunds)
    return gross_amount, total_commission, total_refunds, net_amount


# ---------------------------------------------------------------------------
# create_settlement
# ---------------------------------------------------------------------------

def create_settlement(shop_id, data):
    """Create a DRAFT settlement for a period."""
    shop = get_shop(shop_id)
    period_start = _normalize_iso_timestamp(data.get("period_start"))
    period_end = _normalize_iso_timestamp(data.get("period_end"))

    # Check for period overlap with existing settlements
    existing, _ = db.find("settlements", filters={"shop_id": shop_id})
    for s in existing:
        # Overlap: s.start < period_end AND period_start < s.end
        if (s["period_start"] < period_end
                and period_start < s["period_end"]):
            raise_error(
                ERR_SETTLEMENT_PERIOD_OVERLAP,
                "Settlement period overlaps with an existing settlement.",
            )

    gross, commission, refunds, net = _calculate_period_amounts(
        shop_id, period_start, period_end,
    )

    settlement = db.insert("settlements", {
        "shop_id": shop_id,
        "period_start": period_start,
        "period_end": period_end,
        "gross_amount": gross,
        "total_commission": commission,
        "total_refunds": refunds,
        "net_amount": net,
        "status": "DRAFT",
    })
    return settlement


# ---------------------------------------------------------------------------
# submit_settlement
# ---------------------------------------------------------------------------

def submit_settlement(shop_id, settlement_id):
    """Submit a draft settlement for approval."""
    settlement = _get_settlement(shop_id, settlement_id)

    if settlement["status"] != "DRAFT":
        raise_error(ERR_SETTLEMENT_NOT_DRAFT, "Settlement is not in DRAFT state.")

    if settlement["net_amount"] <= 0:
        raise_error(ERR_SETTLEMENT_ZERO_AMOUNT, "Net settlement amount must be positive.")

    # Check for period overlap with non-DRAFT settlements
    existing, _ = db.find("settlements", filters={"shop_id": shop_id})
    for s in existing:
        if s["id"] == settlement_id:
            continue
        if s["status"] in ("DRAFT",):
            continue
        # Overlap: s.start < settlement.end AND settlement.start < s.end
        if (s["period_start"] < settlement["period_end"]
                and settlement["period_start"] < s["period_end"]):
            raise_error(
                ERR_SETTLEMENT_PERIOD_OVERLAP,
                "Settlement period overlaps with an existing settlement.",
            )

    db.update("settlements", settlement_id, {"status": "PENDING_APPROVAL"})
    return db.find_one("settlements", id=settlement_id)


# ---------------------------------------------------------------------------
# approve_settlement
# ---------------------------------------------------------------------------

def approve_settlement(shop_id, settlement_id):
    """Approve a pending settlement after reconciliation check."""
    settlement = _get_settlement(shop_id, settlement_id)

    if settlement["status"] != "PENDING_APPROVAL":
        raise_error(ERR_SETTLEMENT_NOT_PENDING, "Settlement is not pending approval.")

    # Reconciliation: recalculate and verify
    gross, commission, refunds, net = _calculate_period_amounts(
        shop_id, settlement["period_start"], settlement["period_end"],
    )

    if (round_money(gross) != round_money(settlement["gross_amount"])
            or round_money(net) != round_money(settlement["net_amount"])):
        raise_error(
            ERR_SETTLEMENT_RECONCILIATION_MISMATCH,
            "Settlement amounts do not match current data.",
        )

    db.update("settlements", settlement_id, {"status": "APPROVED"})
    return db.find_one("settlements", id=settlement_id)


# ---------------------------------------------------------------------------
# mark_paid
# ---------------------------------------------------------------------------

def mark_paid(shop_id, settlement_id):
    """Mark an approved settlement as paid and decrement shop balance."""
    settlement = _get_settlement(shop_id, settlement_id)

    if settlement["status"] != "APPROVED":
        raise_error(ERR_SETTLEMENT_NOT_APPROVED, "Settlement is not approved.")

    shop = get_shop(shop_id)
    new_balance = round_money(
        shop.get("settlement_balance", 0.0) - settlement["net_amount"]
    )
    db.update("shops", shop_id, {"settlement_balance": new_balance})

    db.update("settlements", settlement_id, {"status": "PAID"})
    return db.find_one("settlements", id=settlement_id)


# ---------------------------------------------------------------------------
# dispute_settlement
# ---------------------------------------------------------------------------

def dispute_settlement(shop_id, settlement_id):
    """Dispute a pending settlement."""
    settlement = _get_settlement(shop_id, settlement_id)

    if settlement["status"] != "PENDING_APPROVAL":
        raise_error(ERR_SETTLEMENT_NOT_PENDING, "Settlement is not pending approval.")

    db.update("settlements", settlement_id, {"status": "DISPUTED"})
    return db.find_one("settlements", id=settlement_id)


# ---------------------------------------------------------------------------
# resolve_dispute
# ---------------------------------------------------------------------------

def resolve_dispute(shop_id, settlement_id):
    """Resolve a disputed settlement: recalculate and move back to PENDING_APPROVAL."""
    settlement = _get_settlement(shop_id, settlement_id)

    if settlement["status"] != "DISPUTED":
        raise_error(ERR_SETTLEMENT_NOT_DISPUTED_STATE, "Settlement is not in DISPUTED state.")

    # Recalculate
    gross, commission, refunds, net = _calculate_period_amounts(
        shop_id, settlement["period_start"], settlement["period_end"],
    )

    db.update("settlements", settlement_id, {
        "status": "PENDING_APPROVAL",
        "gross_amount": gross,
        "total_commission": commission,
        "total_refunds": refunds,
        "net_amount": net,
    })
    return db.find_one("settlements", id=settlement_id)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_settlement(shop_id, settlement_id):
    return _get_settlement(shop_id, settlement_id)


def list_settlements(shop_id, limit, offset):
    return db.find("settlements", filters={"shop_id": shop_id}, limit=limit, offset=offset)
