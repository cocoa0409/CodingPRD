"""Derived aggregates and their cascades (PRD 3.2, 3.6, 3.8, 3.9)."""

from decimal import Decimal

import db
from util import ratio
from services import calc, lookups

ACTIVE_BID_STATUSES = ("STANDING", "WINNING")
COUNTED_BID_STATUSES = ("STANDING", "WINNING", "WON", "LOST")
OPEN_PAYMENT_STATUSES = ("UNPAID", "PARTIALLY_PAID")
RESOLVED_CLAIM_STATUSES = ("APPROVED", "PARTIALLY_APPROVED")


# ------------------------------------------------------------------- lot side

def recompute_lot_aggregates(lot):
    """The three lot aggregates over ACTIVE lines only."""
    lines = lookups.lines_of_lot(lot["id"], active_only=True)
    lot["manifest_line_count"] = len(lines)
    lot["declared_unit_count"] = sum(int(line["unit_count"]) for line in lines)
    lot["declared_retail_value_cents"] = sum(
        calc.line_extended_cents(line) for line in lines
    )


def recompute_lot_score(lot):
    """Null until a claim against the lot has been approved in whole or part."""
    resolved = [
        row for row in lookups.claims_of_lot(lot["id"])
        if row["claim_status"] in RESOLVED_CLAIM_STATUSES
    ]
    if not resolved:
        lot["manifest_accuracy_score"] = None
        return
    total_verified = sum(int(row["verified_units"] or 0) for row in resolved)
    lot["manifest_accuracy_score"] = calc.accuracy_score(lot, total_verified)


def recompute_line_verified_units(line):
    """Latest non-reversed approving decision touching the line, else null."""
    decided = [
        row for row in lookups.claims_of_line(line["id"])
        if row["claim_status"] in RESOLVED_CLAIM_STATUSES
    ]
    decided.sort(key=lambda row: row.get("_decided_seq") or 0)
    if not decided:
        if line.get("verified_unit_count") is not None:
            line["verified_unit_count"] = None
            db.touch(line)
        return
    latest = decided[-1]
    if line.get("verified_unit_count") != latest["verified_units"]:
        line["verified_unit_count"] = latest["verified_units"]
        db.touch(line)


# ---------------------------------------------------------------- seller side

def assign_commission_tier(seller):
    if seller["account_status"] == "MANIFEST_PROBATION":
        seller["commission_tier"] = "TIER_PROBATION"
        seller["commission_rate_bps"] = calc.TIER_PROBATION_BPS
    elif Decimal(str(seller["gross_recovery_rate"])) >= calc.PREFERRED_GROSS_RECOVERY_THRESHOLD:
        seller["commission_tier"] = "TIER_PREFERRED"
        seller["commission_rate_bps"] = calc.TIER_PREFERRED_BPS
    else:
        seller["commission_tier"] = "TIER_STANDARD"
        seller["commission_rate_bps"] = calc.TIER_STANDARD_BPS


def recompute_seller_recovery(seller):
    """Gross and net recovery, then the commission tier that follows from them."""
    lots = lookups.lots_of_seller(seller["id"])
    orders = lookups.orders_of_seller(seller["id"])

    seller["gross_hammer_cents"] = sum(
        int(order["hammer_price_cents"]) for order in orders
        if order["logistics_status"] != "ABANDONED"
    )
    seller["listed_retail_value_cents"] = sum(
        int(lot["declared_retail_value_cents"]) for lot in lots
        if lot["lot_status"] in ("LISTED", "SOLD", "RELIST_PENDING")
    )
    seller["gross_recovery_rate"] = ratio(
        seller["gross_hammer_cents"], seller["listed_retail_value_cents"], 4
    )

    seller["net_proceeds_cents"] = sum(
        int(order["seller_net_proceeds_cents"] or 0) for order in orders
        if order["settlement_basis"] == "FINAL"
    )
    seller["sold_retail_value_cents"] = sum(
        int(lot["declared_retail_value_cents"]) for lot in lots
        if lot["lot_status"] == "SOLD"
    )
    seller["net_recovery_rate"] = ratio(
        seller["net_proceeds_cents"], seller["sold_retail_value_cents"], 4
    )

    assign_commission_tier(seller)
    db.touch_soft(seller)


def recompute_seller_accuracy(seller):
    """Manifest accuracy average, probation evaluation, then the tier."""
    lots = lookups.lots_of_seller(seller["id"])
    scores = [
        lot["manifest_accuracy_score"] for lot in lots
        if lot.get("manifest_accuracy_score") is not None
    ]
    seller["scored_lot_count"] = len(scores)
    seller["manifest_accuracy_avg"] = calc.average_accuracy(scores)
    if Decimal(str(seller["manifest_accuracy_avg"])) < calc.PROBATION_ACCURACY_THRESHOLD:
        seller["account_status"] = "MANIFEST_PROBATION"
    else:
        seller["account_status"] = "ACTIVE"
    assign_commission_tier(seller)
    db.touch_soft(seller)


# ----------------------------------------------------------------- buyer side

def bid_exposure_cents(bid_rows):
    total = 0
    for bid in bid_rows:
        ceiling = int(bid["ceiling_cents"])
        total += ceiling + calc.buyer_premium_cents(ceiling)
    return total


def order_exposure_cents(order_rows):
    return sum(
        int(order["balance_due_cents"]) for order in order_rows
        if order["payment_status"] in OPEN_PAYMENT_STATUSES
        and order["logistics_status"] != "ABANDONED"
    )


def exposure_of(buyer_id):
    live_bids = [
        bid for bid in lookups.bids_of_buyer(buyer_id)
        if bid["bid_status"] in ACTIVE_BID_STATUSES
    ]
    return bid_exposure_cents(live_bids) + order_exposure_cents(
        lookups.orders_of_buyer(buyer_id)
    )


def recompute_buyer_exposure(buyer):
    buyer["outstanding_exposure_cents"] = exposure_of(buyer["id"])
    db.touch_soft(buyer)
    return buyer["outstanding_exposure_cents"]


def credit_ceiling(buyer):
    return int(buyer["approved_credit_limit_cents"]) + int(buyer["wallet_credit_cents"])


def prospective_exposure_with_bid(buyer, listing_id, new_ceiling):
    """Exposure as it would stand once the new bid supersedes the buyer's own."""
    live_bids = [
        bid for bid in lookups.bids_of_buyer(buyer["id"])
        if bid["bid_status"] in ACTIVE_BID_STATUSES
        and bid["listing_id"] != listing_id
    ]
    total = bid_exposure_cents(live_bids)
    total += int(new_ceiling) + calc.buyer_premium_cents(int(new_ceiling))
    total += order_exposure_cents(lookups.orders_of_buyer(buyer["id"]))
    return total
