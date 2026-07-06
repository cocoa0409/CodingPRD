"""Business logic: calculations and state transitions."""

import math
from decimal import Decimal
from datetime import timedelta

import db
import errors
import models
from util import round_half_up_cents


REORDER_WINDOW_DAYS = 365
REORDER_DISCOUNT_PCT = Decimal("0.10")
RUSH_MIN_DAYS = 3
RUSH_MAX_DAYS = 14  # strictly less than
RUSH_TIER_15D_PCT = Decimal("0.15")  # 7 <= days < 14
RUSH_TIER_7D_PCT = Decimal("0.30")  # 3 <= days < 7
ADDRESSING_LEAD_DAYS = 3
RUSH_LEAD_DAY_SPEEDUP = 4
DAILY_ADDRESSING_CAPACITY = 500
REVISION_FEE_CENTS = 2500
REVISION_FREE_LIMIT = 3

QUANTITY_TIERS = [
    (1, 49, Decimal("1.00")),
    (50, 99, Decimal("1.00")),
    (100, 199, Decimal("0.90")),
    (200, 499, Decimal("0.80")),
    (500, 999999, Decimal("0.70")),
]


def pick_tier(qty: int) -> Decimal:
    for lo, hi, mult in QUANTITY_TIERS:
        if lo <= qty <= hi:
            return mult
    # fallthrough: qty > 999999 use last tier
    return QUANTITY_TIERS[-1][2]


# --------------------------------------------------------------------------
# Pricing calculations
# --------------------------------------------------------------------------

def compute_line_item_price(qty: int, captured_base_cents: int, captured_finish_cents: int) -> int:
    tier = pick_tier(qty)
    paper_component = round_half_up_cents(Decimal(captured_base_cents) * Decimal(qty) * tier)
    finish_component = int(captured_finish_cents) * int(qty)
    return paper_component + finish_component


def recompute_order_subtotal(order: dict):
    lines = models.order_line_items(order["id"])
    order["subtotal_cents"] = sum(li["line_price_cents"] for li in lines)


def recompute_reorder_discount(order: dict):
    prior_id = order.get("prior_order_id")
    if not prior_id:
        order["reorder_discount_cents"] = 0
        return
    prior = db.orders.get(prior_id)
    if not prior:
        order["reorder_discount_cents"] = 0
        return
    if prior.get("customer_id") != order.get("customer_id"):
        order["reorder_discount_cents"] = 0
        return
    if prior.get("status") != "DELIVERED":
        order["reorder_discount_cents"] = 0
        return
    try:
        cur = db.parse_iso(order["created_at"])
        prev = db.parse_iso(prior["created_at"])
    except Exception:
        order["reorder_discount_cents"] = 0
        return
    days = (cur.date() - prev.date()).days
    if days <= REORDER_WINDOW_DAYS:
        order["reorder_discount_cents"] = round_half_up_cents(
            Decimal(order["subtotal_cents"]) * REORDER_DISCOUNT_PCT
        )
    else:
        order["reorder_discount_cents"] = 0


def recompute_order_total(order: dict):
    """Order.total = subtotal - reorder_discount + rush_surcharge + proof.revision_fee (if any)."""
    proof = models.order_active_proof(order["id"])
    revision_fee = int(proof["revision_fee_cents"]) if proof else 0
    order["total_cents"] = (
        int(order.get("subtotal_cents", 0))
        - int(order.get("reorder_discount_cents", 0))
        + int(order.get("rush_surcharge_cents", 0))
        + revision_fee
    )
    order["balance_due_cents"] = max(0, order["total_cents"] - int(order.get("deposit_paid_cents", 0)))


def recompute_expected_lead_days(order: dict):
    lines = models.order_line_items(order["id"])
    if not lines:
        order["expected_lead_days"] = 0
        return
    paper_max = 0
    finish_max = 0
    for li in lines:
        ps = db.paper_stocks.get(li["paper_stock_id"])
        fo = db.finish_options.get(li["finish_option_id"])
        if ps:
            paper_max = max(paper_max, int(ps.get("lead_days", 0)))
        if fo:
            finish_max = max(finish_max, int(fo.get("additional_lead_days", 0)))
    aj = models.order_addressing_jobs(order["id"])
    # Include only non-cancelled addressing jobs when determining lead days
    active_aj = [a for a in aj if a["status"] != "CANCELLED"]
    add_days = ADDRESSING_LEAD_DAYS if active_aj else 0
    rush_speedup = RUSH_LEAD_DAY_SPEEDUP if order.get("rush_requested") else 0
    order["expected_lead_days"] = max(1, paper_max + finish_max + add_days - rush_speedup)


# --------------------------------------------------------------------------
# Proof expiry calculation
# --------------------------------------------------------------------------

def compute_proof_expires_at(proof: dict, order: dict) -> str:
    pkg = db.event_packages.get(order["event_package_id"])
    days = int(pkg["proof_expiry_days"])
    if order.get("rush_requested"):
        days = math.ceil(days / 2)
    now = db.get_now()
    return db.format_iso(now + timedelta(days=days))


# --------------------------------------------------------------------------
# Rush surcharge
# --------------------------------------------------------------------------

def compute_rush_surcharge_pct(rush_deadline_dt, now_dt) -> Decimal:
    days = (rush_deadline_dt.date() - now_dt.date()).days
    if days >= RUSH_MAX_DAYS or days < RUSH_MIN_DAYS:
        errors.raise_error(errors.ERR_RUSH_INFEASIBLE, "rush deadline out of feasible range")
    if 7 <= days < RUSH_MAX_DAYS:
        return RUSH_TIER_15D_PCT
    # 3 <= days < 7
    return RUSH_TIER_7D_PCT


def apply_rush(order: dict, rush_deadline_dt):
    now = db.get_now()
    pct = compute_rush_surcharge_pct(rush_deadline_dt, now)
    base = int(order["subtotal_cents"]) - int(order["reorder_discount_cents"])
    order["rush_surcharge_cents"] = round_half_up_cents(Decimal(base) * pct)
    order["rush_requested"] = True
    order["rush_deadline"] = db.format_iso(rush_deadline_dt)


# --------------------------------------------------------------------------
# Deposit calculation
# --------------------------------------------------------------------------

def compute_deposit_due(order: dict) -> int:
    pkg = db.event_packages.get(order["event_package_id"])
    base = int(order["subtotal_cents"]) - int(order["reorder_discount_cents"])
    pct = Decimal(str(pkg["deposit_pct"]))
    return round_half_up_cents(Decimal(base) * pct)


# --------------------------------------------------------------------------
# Paper reservations
# --------------------------------------------------------------------------

def add_reservations(order: dict):
    for li in models.order_line_items(order["id"]):
        ps = db.paper_stocks.get(li["paper_stock_id"])
        if ps:
            ps["reserved_units"] = int(ps.get("reserved_units", 0)) + int(li["quantity"])
            models.bump(ps)


def remove_reservations(order: dict):
    for li in models.order_line_items(order["id"]):
        ps = db.paper_stocks.get(li["paper_stock_id"])
        if ps:
            ps["reserved_units"] = max(0, int(ps.get("reserved_units", 0)) - int(li["quantity"]))
            models.bump(ps)


# --------------------------------------------------------------------------
# Cascade helpers
# --------------------------------------------------------------------------

def try_cascade_deposit_and_approval(order: dict):
    """If deposit fully paid AND proof approved, cascade to IN_PRODUCTION.

    Idempotent — only fires when order is currently DEPOSIT_PENDING.
    Creates a WorkOrder with appropriate initial states.
    """
    if order["status"] != "DEPOSIT_PENDING":
        return
    proof = models.order_active_proof(order["id"])
    if not proof or proof["status"] != "APPROVED":
        return
    if not order.get("deposit_paid_at"):
        return
    # Transition
    order["status"] = "IN_PRODUCTION"
    models.bump(order)
    # Spawn WorkOrder
    addressing_status = "PENDING" if any(
        a["status"] != "CANCELLED" for a in models.order_addressing_jobs(order["id"])
    ) else "NOT_APPLICABLE"
    wo = models.make_common({
        "order_id": order["id"],
        "press_id": None,
        "press_slot_start": None,
        "press_slot_end": None,
        "production_status": "NOT_STARTED",
        "addressing_status": addressing_status,
    })
    db.work_orders[wo["id"]] = wo


def try_cascade_ready_to_ship(order: dict, work_order: dict):
    """If WorkOrder complete on both dimensions, cascade order to READY_TO_SHIP and spawn shipment."""
    if order["status"] != "IN_PRODUCTION":
        return
    if work_order["production_status"] != "COMPLETED":
        return
    if work_order["addressing_status"] not in ("NOT_APPLICABLE", "COMPLETED"):
        return
    order["status"] = "READY_TO_SHIP"
    models.bump(order)
    ship = models.make_common({
        "order_id": order["id"],
        "tracking_number": "TRK-" + db.new_id()[:12].upper(),
        "dispatched_at": None,
        "delivered_at": None,
        "status": "PREPARING",
    })
    db.shipments[ship["id"]] = ship


# --------------------------------------------------------------------------
# Proof expiry check (system observation on read)
# --------------------------------------------------------------------------

def check_proof_expiry_on_read(proof: dict):
    """If proof is SUBMITTED and current UTC has passed expires_at, expire and cascade."""
    if proof["status"] != "SUBMITTED":
        return
    if not proof.get("expires_at"):
        return
    now = db.get_now()
    try:
        exp = db.parse_iso(proof["expires_at"])
    except Exception:
        return
    if now > exp:
        # Cascade to EXPIRED
        proof["status"] = "EXPIRED"
        models.bump(proof)
        # Find the order that references this proof
        for o in db.orders.values():
            if o.get("proof_id") == proof["id"]:
                if o["status"] not in ("CANCELLED", "DELIVERED"):
                    # Release reservations if in DEPOSIT_PENDING/IN_PRODUCTION/READY_TO_SHIP
                    if o["status"] in ("DEPOSIT_PENDING", "IN_PRODUCTION", "READY_TO_SHIP"):
                        remove_reservations(o)
                    o["status"] = "CANCELLED"
                    models.bump(o)
                # Archive design
                d = db.designs.get(o["design_id"])
                if d:
                    d["status"] = "ARCHIVED"
                    models.bump(d)
                # Cascade addressing jobs
                for a in models.order_addressing_jobs(o["id"]):
                    if a["status"] not in ("COMPLETED", "CANCELLED"):
                        a["status"] = "CANCELLED"
                        models.bump(a)
                # Cascade shipment if PREPARING
                for s in models.order_shipments(o["id"]):
                    if s["status"] == "PREPARING":
                        s["status"] = "CANCELLED"
                        models.bump(s)
                break
