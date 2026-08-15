"""Business logic services: ledger, derived recomputation, prize evaluation,
final settlement, and cascading side effects.

All money math uses Decimal with ROUND_HALF_UP per PRD §2.6.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import clock, _parse_iso
import helpers

# Constants
BOUNCE_FEE_CENTS = 2500
RESTOCK_FEE_BPS = 1000
RETURN_WINDOW_DAYS = 7

COUNTED_ORDER_STATUSES = ("SUBMITTED", "LOCKED", "COMPLETED")


def round_half_up_cents(value):
    """Round a Decimal (or numeric) to integer cents, half away from zero."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Ledger (append-only)
# ---------------------------------------------------------------------------

def post_ledger_entry(group_id, campaign_id, entry_type, amount_cents,
                      reference_type, reference_id, memo):
    """Append a ProceedsLedgerEntry; seq is per-group monotonic from 1;
    balance_after = previous entry's balance_after + amount (0 baseline)."""
    group_entries = [e for e in db.ledger_entries.values() if e["group_id"] == group_id]
    prev_seq = max((e["seq"] for e in group_entries), default=0)
    prev_balance = 0
    if group_entries:
        latest = max(group_entries, key=lambda e: (e["created_at"], e["seq"]))
        prev_balance = latest["balance_after_cents"]
    seq = prev_seq + 1
    balance_after = prev_balance + amount_cents
    entry = {
        "id": helpers.new_id(),
        "group_id": group_id,
        "campaign_id": campaign_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "seq": seq,
        "balance_after_cents": balance_after,
        "memo": memo,
        "created_at": helpers.now_iso(),
    }
    db.ledger_entries[entry["id"]] = entry
    # Group balance mirrors the latest entry; group record itself is mutated.
    group = db.groups[group_id]
    group["proceeds_balance_cents"] = balance_after
    helpers.touch(group)
    return entry


def recompute_group_provisional(group_id):
    """provisional_proceeds_cents = sum(PROVISIONAL_CREDIT) - sum(SALE_REVERSAL_DEBIT magnitudes).

    SALE_REVERSAL_DEBIT entries carry negative signed amounts, so the formula is
    sum(credits) + sum(reversal amounts)."""
    credits = 0
    reversals = 0
    for e in db.ledger_entries.values():
        if e["group_id"] != group_id:
            continue
        if e["entry_type"] == "PROVISIONAL_CREDIT":
            credits += e["amount_cents"]
        elif e["entry_type"] == "SALE_REVERSAL_DEBIT":
            reversals += e["amount_cents"]  # negative values
    return credits + reversals


# ---------------------------------------------------------------------------
# Order payment-status derivation (PRD §3.2)
# ---------------------------------------------------------------------------

def recompute_order_payment(order):
    cleared = 0
    for p in db.payments.values():
        if p["order_id"] == order["id"] and p["status"] == "CLEARED":
            cleared += p["amount_cents"] - p["refunded_amount_cents"]
    order["cleared_cents"] = cleared
    total = order["total_cents"]
    if cleared == 0:
        new_status = "UNPAID"
    elif total > 0 and cleared == total:
        new_status = "PAID"
    else:
        new_status = "PARTIALLY_PAID"
    order["payment_status"] = new_status
    helpers.touch(order)
    return new_status


def recompute_order_fulfillment(order):
    """Derive fulfillment_status from line-level returned/refunded quantities
    (only for orders already at or past DISTRIBUTED)."""
    if order["fulfillment_status"] not in ("DISTRIBUTED", "PARTIALLY_RETURNED"):
        return order["fulfillment_status"]
    lines = [ln for ln in db.order_lines.values() if ln["order_id"] == order["id"]]
    if not lines:
        return order["fulfillment_status"]
    all_full = all(
        ln["returned_qty"] + ln["claim_resolved_refund_qty"] >= ln["quantity"]
        for ln in lines
    )
    if all_full:
        order["fulfillment_status"] = "RETURNED"
    else:
        any_reduced = any(
            (ln["returned_qty"] + ln["claim_resolved_refund_qty"]) > 0
            for ln in lines
        )
        if any_reduced:
            order["fulfillment_status"] = "PARTIALLY_RETURNED"
    helpers.touch(order)
    return order["fulfillment_status"]


# ---------------------------------------------------------------------------
# Seller metrics (PRD §3.8)
# ---------------------------------------------------------------------------

def recompute_seller_metrics(seller):
    units = 0
    orders_count = 0
    revenue = 0
    for o in db.orders.values():
        if o["seller_id"] != seller["id"]:
            continue
        if o["status"] in COUNTED_ORDER_STATUSES:
            orders_count += 1
            for ln in db.order_lines.values():
                if ln["order_id"] == o["id"]:
                    units += ln["quantity"] - ln["returned_qty"] - ln["claim_resolved_refund_qty"]
        if o["status"] != "CANCELLED":
            for p in db.payments.values():
                if p["order_id"] == o["id"] and p["status"] == "CLEARED":
                    revenue += p["amount_cents"] - p["refunded_amount_cents"]
    seller["units_sold"] = units
    seller["revenue_cents"] = revenue
    seller["orders_count"] = orders_count
    helpers.touch(seller)


# ---------------------------------------------------------------------------
# Prize evaluation (PRD §3.8)
# ---------------------------------------------------------------------------

def _prize_remaining(prize):
    used = sum(
        1 for a in db.prize_awards.values()
        if a["prize_id"] == prize["id"] and a["status"] in ("AWARDED", "FULFILLED")
    )
    return prize["stock_quantity"] - used


def _seller_metric_for(seller, tier_type):
    if tier_type == "UNITS_SOLD":
        return seller["units_sold"]
    if tier_type == "REVENUE_CENTS":
        return seller["revenue_cents"]
    return seller["orders_count"]  # ORDERS_COUNT


def evaluate_prizes_for_seller(seller):
    """Run prize tier evaluation for one seller (PRD §3.8).

    - Newly qualifying seller with no award for (seller, tier_type) in
      {QUEUED, AWARDED, FULFILLED}: create AWARDED (stock > 0, post
      PRIZE_COST_DEBIT) or QUEUED (stock == 0).
    - Seller no longer qualifying with award in {QUEUED, AWARDED}: FORFEITED;
      AWARDED forfeiture posts PRIZE_COST_REVERSAL, restores stock, and
      promotes the head of the QUEUED queue if the head still qualifies.
    """
    campaign_prizes = [p for p in db.prizes.values() if p["campaign_id"] == seller["campaign_id"]]
    # Deterministic evaluation order: prize created_at ASC.
    campaign_prizes.sort(key=lambda p: p["created_at"])
    for prize in campaign_prizes:
        metric = _seller_metric_for(seller, prize["tier_type"])
        qualifies = metric >= prize["threshold_value"]
        existing = None
        for a in db.prize_awards.values():
            if (
                a["seller_id"] == seller["id"]
                and a["status"] in ("QUEUED", "AWARDED", "FULFILLED")
                and db.prizes[a["prize_id"]]["tier_type"] == prize["tier_type"]
            ):
                existing = a
                break
        if qualifies and existing is None:
            _create_award(seller, prize, metric)
        elif not qualifies and existing is not None and existing["status"] in ("QUEUED", "AWARDED"):
            _forfeit_award(existing, prize)


def _create_award(seller, prize, metric):
    award = {
        "id": helpers.new_id(),
        "seller_id": seller["id"],
        "prize_id": prize["id"],
        "campaign_id": seller["campaign_id"],
        "status": None,
        "qualifying_metric_value": metric,
        "qualified_at": helpers.now_iso(),
        "created_at": helpers.now_iso(),
        "updated_at": helpers.now_iso(),
        "version": 1,
    }
    if _prize_remaining(prize) > 0:
        award["status"] = "AWARDED"
        db.prize_awards[award["id"]] = award
        post_ledger_entry(
            group_id=seller["group_id"],
            campaign_id=seller["campaign_id"],
            entry_type="PRIZE_COST_DEBIT",
            amount_cents=-prize["prize_cost_cents"],
            reference_type="PRIZE_AWARD",
            reference_id=award["id"],
            memo=f"Prize cost chargeback for prize {prize['id']} awarded to seller {seller['id']}",
        )
    else:
        award["status"] = "QUEUED"
        db.prize_awards[award["id"]] = award
    _sync_prize_remaining(prize)
    return award


def _forfeit_award(award, prize):
    was_awarded = award["status"] == "AWARDED"
    award["status"] = "FORFEITED"
    helpers.touch(award)
    if was_awarded:
        seller = db.sellers[award["seller_id"]]
        post_ledger_entry(
            group_id=seller["group_id"],
            campaign_id=award["campaign_id"],
            entry_type="PRIZE_COST_REVERSAL",
            amount_cents=prize["prize_cost_cents"],
            reference_type="PRIZE_AWARD",
            reference_id=award["id"],
            memo=f"Prize cost reversal for forfeited award {award['id']}",
        )
        _sync_prize_remaining(prize)
        _promote_queue_head(prize)
    else:
        _sync_prize_remaining(prize)


def _promote_queue_head(prize):
    """Promote the head of the prize's QUEUED queue while stock is available
    and the head still qualifies. Queue order: qualified_at ASC, tie by seller
    created_at ASC."""
    while _prize_remaining(prize) > 0:
        queued = [
            a for a in db.prize_awards.values()
            if a["prize_id"] == prize["id"] and a["status"] == "QUEUED"
        ]
        if not queued:
            break
        queued.sort(key=lambda a: (a["qualified_at"], db.sellers[a["seller_id"]]["created_at"]))
        head = queued[0]
        seller = db.sellers[head["seller_id"]]
        metric = _seller_metric_for(seller, prize["tier_type"])
        if metric < prize["threshold_value"]:
            break
        head["status"] = "AWARDED"
        helpers.touch(head)
        post_ledger_entry(
            group_id=seller["group_id"],
            campaign_id=head["campaign_id"],
            entry_type="PRIZE_COST_DEBIT",
            amount_cents=-prize["prize_cost_cents"],
            reference_type="PRIZE_AWARD",
            reference_id=head["id"],
            memo=f"Prize cost chargeback for prize {prize['id']} promoted to seller {seller['id']}",
        )
        _sync_prize_remaining(prize)


def _sync_prize_remaining(prize):
    prize["remaining_quantity"] = _prize_remaining(prize)
    helpers.touch(prize)


def full_prize_sweep(campaign_id):
    """Full prize-evaluation sweep across all sellers of the campaign."""
    campaign_sellers = [s for s in db.sellers.values() if s["campaign_id"] == campaign_id]
    campaign_sellers.sort(key=lambda s: s["created_at"])
    for seller in campaign_sellers:
        evaluate_prizes_for_seller(seller)


# ---------------------------------------------------------------------------
# Campaign computed totals (PRD §3.7)
# ---------------------------------------------------------------------------

def recompute_campaign_totals(campaign):
    gross = 0
    for o in db.orders.values():
        if o["campaign_id"] == campaign["id"] and o["status"] in COUNTED_ORDER_STATUSES:
            gross += o["total_cents"]
    campaign["gross_sales_cents"] = gross

    family_credits = 0
    for c in db.claims.values():
        if c["campaign_id"] == campaign["id"] and c["status"] == "RESOLVED_REFUND":
            family_credits += c["credit_cents"]
    for r in db.return_requests.values():
        if r["campaign_id"] == campaign["id"] and r["status"] in ("RECEIVED_RESTOCKED", "RECEIVED_WRITTEN_OFF"):
            family_credits += r["refund_cents"] or 0
    campaign["family_credits_cents"] = family_credits

    active_sos = [
        so for so in db.supplier_orders.values()
        if so["campaign_id"] == campaign["id"] and so["status"] != "CANCELLED"
    ]
    if active_sos:
        so = active_sos[0]
        campaign["estimated_supplier_cost_cents"] = so["estimated_cost_cents"] or 0
        if so["status"] == "DELIVERED":
            campaign["actual_supplier_cost_cents"] = so["actual_cost_cents"] or 0
        else:
            campaign["actual_supplier_cost_cents"] = 0
    else:
        campaign["estimated_supplier_cost_cents"] = 0
        campaign["actual_supplier_cost_cents"] = 0
    helpers.touch(campaign)


# ---------------------------------------------------------------------------
# Final settlement (PRD §3.7)
# ---------------------------------------------------------------------------

def run_final_settlement(campaign):
    """Pinned evaluation order for campaign close (PRD §3.7)."""
    campaign_id = campaign["id"]

    # (3) actual unit costs from the campaign's DELIVERED supplier order
    delivered_so = None
    for so in db.supplier_orders.values():
        if so["campaign_id"] == campaign_id and so["status"] == "DELIVERED":
            delivered_so = so
            break
    actual_cost_by_product = {}
    if delivered_so is not None:
        for ln in db.supplier_order_lines.values():
            if ln["supplier_order_id"] == delivered_so["id"]:
                actual_cost_by_product[ln["product_id"]] = ln["unit_cost_actual_cents"]

    # (4) per-group final share: sum unrounded per-line shares, round once
    campaign_groups = [g for g in db.groups.values() if g["campaign_id"] == campaign_id]
    campaign_groups.sort(key=lambda g: g["created_at"])
    group_finals = {}
    total_net_unrounded = Decimal(0)

    # All non-CANCELLED orders of the campaign (for total_net)
    def _line_set_for_group(group_id):
        rows = []
        for o in db.orders.values():
            if o["campaign_id"] != campaign_id or o["status"] == "CANCELLED":
                continue
            if o["group_id"] != group_id:
                continue
            for ln in db.order_lines.values():
                if ln["order_id"] == o["id"]:
                    rows.append((o, ln))
        return rows

    def _line_share(order, line):
        product = db.products[line["product_id"]]
        actual_cost = actual_cost_by_product.get(line["product_id"], line["unit_cost_cents"])
        eff_qty = (
            line["quantity"]
            - line["returned_qty"]
            - line["claim_resolved_refund_qty"]
            - line["sort_shortage_qty"]
        )
        net = (line["unit_price_cents"] - actual_cost)
        share = (Decimal(eff_qty) * Decimal(net) * Decimal(product["profit_share_bps"])) / Decimal(10000)
        return share, eff_qty * net

    for g in campaign_groups:
        share_unrounded = Decimal(0)
        for (o, ln) in _line_set_for_group(g["id"]):
            share, _ = _line_share(o, ln)
            share_unrounded += share
        group_final = round_half_up_cents(share_unrounded)
        group_finals[g["id"]] = group_final

    # total_net over the same line set (all non-CANCELLED orders of the campaign)
    for o in db.orders.values():
        if o["campaign_id"] != campaign_id or o["status"] == "CANCELLED":
            continue
        for ln in db.order_lines.values():
            if ln["order_id"] != o["id"]:
                continue
            _, net_units = _line_share(o, ln)
            total_net_unrounded += Decimal(net_units)

    # (5) true-up per group
    for g in campaign_groups:
        group_final = group_finals[g["id"]]
        provisional = recompute_group_provisional(g["id"])
        true_up = group_final - provisional
        if true_up > 0:
            post_ledger_entry(
                group_id=g["id"], campaign_id=campaign_id,
                entry_type="FINAL_TRUE_UP_CREDIT", amount_cents=true_up,
                reference_type="CAMPAIGN", reference_id=campaign_id,
                memo="Final settlement true-up credit",
            )
        elif true_up < 0:
            post_ledger_entry(
                group_id=g["id"], campaign_id=campaign_id,
                entry_type="FINAL_TRUE_UP_DEBIT", amount_cents=true_up,
                reference_type="CAMPAIGN", reference_id=campaign_id,
                memo="Final settlement true-up debit",
            )
        g["final_proceeds_cents"] = group_final
        g["provisional_proceeds_cents"] = provisional
        helpers.touch(g)

    # (6) general fund absorbs rounding remainder
    total_net = round_half_up_cents(total_net_unrounded)
    campaign["general_fund_cents"] = (
        total_net
        - sum(group_finals.values())
        - (campaign["family_credits_cents"] or 0)
    )
    helpers.touch(campaign)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_order(order, post_reversal):
    """Cancel an order; when it was SUBMITTED/LOCKED, post the sale reversal."""
    was_submitted = order["status"] in ("SUBMITTED", "LOCKED")
    order["status"] = "CANCELLED"
    helpers.touch(order)
    if post_reversal and was_submitted and order["provisional_credit_cents"]:
        post_ledger_entry(
            group_id=order["group_id"], campaign_id=order["campaign_id"],
            entry_type="SALE_REVERSAL_DEBIT",
            amount_cents=-order["provisional_credit_cents"],
            reference_type="ORDER", reference_id=order["id"],
            memo=f"Sale reversal for cancelled order {order['id']}",
        )
    seller = db.sellers[order["seller_id"]]
    recompute_seller_metrics(seller)
    evaluate_prizes_for_seller(seller)
    campaign = db.campaigns[order["campaign_id"]]
    recompute_campaign_totals(campaign)
