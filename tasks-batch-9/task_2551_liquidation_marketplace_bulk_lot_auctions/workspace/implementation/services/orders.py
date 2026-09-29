"""Sale-order creation, the settlement waterfall and the seller payout."""

import db
from util import bps_of, clock, plus_days
from services import aggregates, calc, lookups


def recompute_money(order):
    """PRD 3.6 waterfall. Freight follows the settlement basis."""
    if order["settlement_basis"] == "FINAL":
        freight = int(order["actual_freight_cents"] or 0)
    else:
        freight = int(order["estimated_freight_cents"] or 0)
    pre_fee = (
        int(order["hammer_price_cents"])
        + int(order["buyer_premium_cents"])
        + freight
    )
    order["pre_fee_total_cents"] = pre_fee
    total_due = pre_fee + int(order["late_fee_cents"]) - int(order["claim_credit_cents"])
    order["total_due_cents"] = total_due
    order["balance_due_cents"] = max(0, total_due - int(order["amount_paid_cents"]))


def create_sale_order(listing, buyer_id, sale_source, hammer_cents):
    lot = lookups.lot_of_listing(listing)
    bps = calc.premium_bps(hammer_cents)
    pallets = calc.pallet_count(lot["declared_unit_count"])
    order = db.new_row(
        listing_id=listing["id"],
        buyer_id=buyer_id,
        sale_source=sale_source,
        hammer_price_cents=int(hammer_cents),
        buyer_premium_bps=bps,
        buyer_premium_cents=calc.buyer_premium_cents(hammer_cents, bps),
        pallet_count=pallets,
        estimated_freight_cents=calc.freight_cents(pallets),
        actual_freight_cents=None,
        claim_credit_cents=0,
        late_fee_cents=0,
        amount_paid_cents=0,
        paid_at=None,
        picked_up_at=None,
        abandoned_at=None,
        settlement_basis="PROVISIONAL",
        payment_status="UNPAID",
        logistics_status="AWAITING_APPOINTMENT",
        claim_window_closes_at=None,
        seller_commission_rate_bps=None,
        seller_commission_cents=None,
        seller_debranding_fee_cents=None,
        seller_net_proceeds_cents=None,
    )
    order["payment_due_at"] = plus_days(order["created_at"], calc.PAYMENT_TERM_DAYS)
    order["pickup_deadline_at"] = plus_days(order["created_at"], calc.PICKUP_TERM_DAYS)
    recompute_money(order)
    db.sale_orders[order["id"]] = order
    return order


def freeze_seller_payout(order):
    """Per-line commission, de-branding fee and net proceeds, at pickup."""
    lot = lookups.lot_of_order(order)
    seller = lookups.seller_of_order(order)
    rate = int(seller["commission_rate_bps"])
    order["seller_commission_rate_bps"] = rate

    commission_total = 0
    for line in lookups.lines_of_lot(lot["id"], active_only=True):
        share = calc.line_share_cents(
            order["hammer_price_cents"], line, lot["declared_retail_value_cents"]
        )
        commission_total += bps_of(share, rate)
    order["seller_commission_cents"] = commission_total

    debranding = 0
    if lot.get("de_branding_required"):
        policy = lookups.policy_of_lot(lot)
        per_unit = int(policy["debranding_fee_cents_per_unit"]) if policy else 0
        debranding = int(lot["declared_unit_count"]) * per_unit
    order["seller_debranding_fee_cents"] = debranding
    order["seller_net_proceeds_cents"] = (
        int(order["hammer_price_cents"]) - commission_total - debranding
    )


def settle_final(order, actual_freight_cents):
    """Move the order to FINAL settlement and freeze the seller payout."""
    seller = lookups.seller_of_order(order)
    order["actual_freight_cents"] = int(actual_freight_cents)
    order["settlement_basis"] = "FINAL"
    recompute_money(order)
    # The commission rate in force is read after this request's recovery pass.
    aggregates.recompute_seller_recovery(seller)
    freeze_seller_payout(order)
    aggregates.recompute_seller_recovery(seller)


def apply_late_fee(order):
    order["late_fee_cents"] = calc.late_fee_cents(order["pre_fee_total_cents"])
    recompute_money(order)


def late_fee_due(order):
    return (
        int(order["balance_due_cents"]) > 0
        and int(order["late_fee_cents"]) == 0
        and order["payment_due_at"] is not None
        and order["payment_due_at"] < clock.now()
    )


def pickup_overdue(order):
    return (
        order["logistics_status"] in ("AWAITING_APPOINTMENT", "APPOINTMENT_SCHEDULED")
        and order["pickup_deadline_at"] is not None
        and clock.now() > order["pickup_deadline_at"]
    )
