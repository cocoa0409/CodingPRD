"""Business logic: calculations, reservations, stock reconciliation, cascades.

Every routine here traces to a PRD §2 / §3 sentence or a scaffold calculation.
"""
import math

import db
from helpers import touch, round_half_up


# ---------------------------------------------------------------------------
# calc sku_available_units (scaffold §1.3; PRD §2.6)
# ---------------------------------------------------------------------------
def reconcile_sku(sku):
    """reserved = SUM(qty) over ACTIVE reservations on this sku. available derived."""
    total = 0
    for r in db.reservations.values():
        if r["sku_id"] == sku["id"] and r["status"] == "ACTIVE":
            total += r["qty"]
    sku["reserved"] = total
    sku["available"] = sku["on_hand"] - sku["reserved"]


def available_units(sku):
    reconcile_sku(sku)
    return sku["on_hand"] - sku["reserved"]


def create_reservation(sku_id, holder_type, holder_id, qty):
    from helpers import stamp_create
    res = {
        "sku_id": sku_id,
        "holder_type": holder_type,
        "holder_id": holder_id,
        "qty": qty,
        "status": "ACTIVE",
    }
    stamp_create(res)
    db.reservations[res["id"]] = res
    reconcile_sku(db.skus[sku_id])
    return res


def active_reservations_for(holder_type, holder_id):
    return [r for r in db.reservations.values()
            if r["holder_type"] == holder_type and r["holder_id"] == holder_id
            and r["status"] == "ACTIVE"]


def commit_reservation(res):
    """ACTIVE -> COMMITTED: decrement Sku.on_hand AND Sku.reserved by qty."""
    res["status"] = "COMMITTED"
    touch(res)
    sku = db.skus[res["sku_id"]]
    sku["on_hand"] -= res["qty"]
    reconcile_sku(sku)


def release_reservation(res):
    """ACTIVE -> RELEASED: row leaves ACTIVE set, reserved drops."""
    res["status"] = "RELEASED"
    touch(res)
    reconcile_sku(db.skus[res["sku_id"]])


# ---------------------------------------------------------------------------
# Recall safety overlay (PRD §2.9)
# ---------------------------------------------------------------------------
def has_mandatory_recall(sku_id):
    for rn in db.recall_notices.values():
        if rn["sku_id"] == sku_id and rn["severity"] == "MANDATORY":
            return True
    return False


# ---------------------------------------------------------------------------
# calc order_total (scaffold §1.3; PRD §3.5)
# ---------------------------------------------------------------------------
def recompute_order_total(order):
    subtotal = 0
    for line in db.order_lines.values():
        if line["order_id"] == order["id"]:
            subtotal += line["qty"] * line["unit_price_cents"]
    order["subtotal_cents"] = subtotal
    # store_credit_applied_cents is set only at delivery; before that it is 0.
    order["total_due_cents"] = subtotal - order.get("store_credit_applied_cents", 0)
    paid = 0
    for p in db.payments.values():
        if (p["target_type"] == "SALES_ORDER" and p["target_id"] == order["id"]
                and p["status"] == "CAPTURED"):
            paid += p["amount_cents"]
    order["amount_paid_cents"] = paid
    total_due = order["total_due_cents"]
    if paid >= total_due and paid > 0:
        order["payment_status"] = "PAID"
    elif 0 < paid < total_due:
        order["payment_status"] = "PARTIALLY_PAID"
    else:
        order["payment_status"] = "UNPAID"


def recompute_order_total_zero_safe(order):
    """Variant used at delivery: a zero total_due counts as PAID even with paid==0.

    PRD §3.6: 'a zero total counts as PAID only when amount_paid_cents, which is
    at least 0, is at least total_due_cents.'
    """
    paid = 0
    for p in db.payments.values():
        if (p["target_type"] == "SALES_ORDER" and p["target_id"] == order["id"]
                and p["status"] == "CAPTURED"):
            paid += p["amount_cents"]
    order["amount_paid_cents"] = paid
    total_due = order["total_due_cents"]
    if paid >= total_due:
        order["payment_status"] = "PAID"
    elif 0 < paid < total_due:
        order["payment_status"] = "PARTIALLY_PAID"
    else:
        order["payment_status"] = "UNPAID"


# ---------------------------------------------------------------------------
# calc apply_store_credit (scaffold §1.3; PRD §3.6)
# ---------------------------------------------------------------------------
def apply_store_credit(order):
    """Single waterfall bucket at delivery; runs BEFORE the PAID precondition."""
    customer = db.customers[order["customer_id"]]
    subtotal = order["subtotal_cents"]
    applied = min(customer["store_credit_cents"], subtotal)
    order["store_credit_applied_cents"] = applied
    order["total_due_cents"] = subtotal - applied
    customer["store_credit_cents"] -= applied
    if applied > 0:
        touch(customer)


# ---------------------------------------------------------------------------
# calc ticket_quote (scaffold §1.3; PRD §3.3)
# ---------------------------------------------------------------------------
def compute_ticket_quote(ticket):
    tier = db.tune_up_tiers[ticket["tier_id"]]
    effective_base = tier["base_labor_cents"]
    if ticket["is_rush"]:
        effective_base = round_half_up(
            tier["base_labor_cents"] * (10000 + tier["rush_multiplier_bps"]), 10000)
    labor_sum = 0
    for ll in db.labor_lines.values():
        if ll["ticket_id"] == ticket["id"]:
            labor_sum += ll["labor_cents"]
    ticket["labor_subtotal_cents"] = effective_base + labor_sum

    effective_turnaround = tier["turnaround_hours"]
    if ticket["is_rush"]:
        effective_turnaround = math.ceil(tier["turnaround_hours"] / 2)
    ready = db.current_utc() + _hours(effective_turnaround)
    ticket["promised_ready_at"] = db.format_dt(ready)

    if ticket["warranty_claim_id"] is not None:
        ticket["customer_owes_cents"] = 0
    else:
        ticket["customer_owes_cents"] = ticket["labor_subtotal_cents"]


def _hours(n):
    from datetime import timedelta
    return timedelta(hours=n)


# ---------------------------------------------------------------------------
# calc layaway_settlement (scaffold §1.3; PRD §3.7)
# ---------------------------------------------------------------------------
FORFEIT_PCT_BPS = 1500
FORFEIT_FLOOR_CENTS = 2000


def layaway_settle_forfeit(plan):
    pct_term = round_half_up(plan["price_cents"] * FORFEIT_PCT_BPS, 10000)
    raw_fee = max(FORFEIT_FLOOR_CENTS, pct_term)
    fee = min(raw_fee, plan["deposit_cents"])
    plan["forfeit_fee_cents"] = fee
    plan["refund_cents"] = plan["deposit_cents"] - fee


def layaway_settle_cancel(plan):
    plan["forfeit_fee_cents"] = 0
    plan["refund_cents"] = plan["deposit_cents"]


# ---------------------------------------------------------------------------
# calc tradein_offer (scaffold §1.3; PRD §3.11)
# ---------------------------------------------------------------------------
GRADE_BPS = {"A": 8500, "B": 7000, "C": 5000}
HANDLING_DEDUCTION_CENTS = 1500


def tradein_offer(tradein):
    haircut_bps = GRADE_BPS[tradein["condition_grade"]]
    after_haircut = round_half_up(tradein["appraised_value_cents"] * haircut_bps, 10000)
    tradein["offer_cents"] = max(0, after_haircut - HANDLING_DEDUCTION_CENTS)


# ---------------------------------------------------------------------------
# calc build_fee (scaffold §1.3; PRD §3.9) — marginal tiered
# ---------------------------------------------------------------------------
BASE_FEE_CENTS = 5000
TIER1_PER_PART_CENTS = 1200
TIER2_PER_PART_CENTS = 900
TIER3_PER_PART_CENTS = 600


def build_fee(n):
    fee = BASE_FEE_CENTS
    fee += min(n, 5) * TIER1_PER_PART_CENTS
    if n > 5:
        fee += (min(n, 10) - 5) * TIER2_PER_PART_CENTS
    if n > 10:
        fee += (n - 10) * TIER3_PER_PART_CENTS
    return fee


# ---------------------------------------------------------------------------
# calc special_order_deposit (scaffold §1.3; PRD §3.8)
# ---------------------------------------------------------------------------
DEPOSIT_PCT_BPS = 3000
DEPOSIT_MIN_CENTS = 5000


def special_order_deposit(line_value):
    pct_term = round_half_up(line_value * DEPOSIT_PCT_BPS, 10000)
    return min(line_value, max(DEPOSIT_MIN_CENTS, pct_term))


# ---------------------------------------------------------------------------
# calc build_readiness (scaffold §1.3; PRD §3.9)
# ---------------------------------------------------------------------------
def reserved_part_count(build):
    """Count ACTIVE BUILD_JOB reservations pointing at this build."""
    n = 0
    for r in db.reservations.values():
        if (r["holder_type"] == "BUILD_JOB" and r["holder_id"] == build["id"]
                and r["status"] == "ACTIVE"):
            n += 1
    return n


def frame_reservation_active(build):
    for r in db.reservations.values():
        if (r["holder_type"] == "BUILD_JOB" and r["holder_id"] == build["id"]
                and r["sku_id"] == build["frame_sku_id"] and r["status"] == "ACTIVE"):
            return True
    return False


# ---------------------------------------------------------------------------
# calc customer_open_recall_count (scaffold §1.3; PRD §3.1)
# ---------------------------------------------------------------------------
def customer_open_recall_count(customer):
    # sku_ids on DELIVERED order lines of this customer's orders
    purchased_skus = set()
    for order in db.sales_orders.values():
        if (order["customer_id"] == customer["id"]
                and order["fulfillment_status"] == "DELIVERED"):
            for line in db.order_lines.values():
                if line["order_id"] == order["id"]:
                    purchased_skus.add(line["sku_id"])
    open_count = 0
    for rn in db.recall_notices.values():
        if rn["sku_id"] in purchased_skus:
            acked = any(ra["recall_id"] == rn["id"] and ra["customer_id"] == customer["id"]
                        for ra in db.recall_acks.values())
            if not acked:
                open_count += 1
    customer["open_recall_count"] = open_count
    return open_count


def deposit_sum(target_type, target_id):
    total = 0
    for p in db.payments.values():
        if (p["target_type"] == target_type and p["target_id"] == target_id
                and p["status"] == "CAPTURED"):
            total += p["amount_cents"]
    return total
