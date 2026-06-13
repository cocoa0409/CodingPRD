"""Pricing & selection calculations (PRD §3.2-§3.5, §3.7; SCAFFOLD §1.3)."""
from db import store
from helpers import round_half_up
from services import clock

LOYALTY_PCT = {"STANDARD": 0.00, "SILVER": 0.05, "GOLD": 0.10}
COMBINED_DISCOUNT_CAP = 0.30
REASON_PCT = {"WILTED": 0.50, "WRONG_ITEM": 1.00, "LATE": 0.25, "DAMAGED": 0.75}
REASON_FLOOR_CENTS = {"WILTED": 500, "WRONG_ITEM": 0, "LATE": 300, "DAMAGED": 1000}
SILVER_THRESHOLD = 5
GOLD_THRESHOLD = 15
TIER_ORDER = {"STANDARD": 0, "SILVER": 1, "GOLD": 2}
TIER_BY_RANK = {0: "STANDARD", 1: "SILVER", 2: "GOLD"}


def find_holiday_window(delivery_date):
    """Locate the HolidayWindow whose inclusive [start_date, end_date] contains
    delivery_date. At most one applies; on overlap choose earliest start_date,
    tie-break earliest created_at."""
    matches = []
    for w in store.holiday_windows.values():
        if w["start_date"] <= delivery_date <= w["end_date"]:
            matches.append(w)
    if not matches:
        return None
    matches.sort(key=lambda w: (w["start_date"], w["created_at"], w.get("_seq", 0)))
    return matches[0]


def _surged_subtotal(arrangement, delivery_date):
    """Surge step: surged subtotal and the matching window (if any)."""
    base = arrangement["base_price_cents"]
    window = find_holiday_window(delivery_date)
    surge_applies = window is not None and (
        arrangement["premium_tier"] == "PREMIUM" or window["applies_to_standard"]
    )
    if surge_applies:
        surged = round_half_up(base * window["surge_multiplier"])
    else:
        surged = base
    return surged


def _discount_pct(customer, order):
    """Combined loyalty + recurring discount fraction, capped at 0.30."""
    loyalty_pct = LOYALTY_PCT[customer["loyalty_tier"]]
    recurring_pct = 0.00
    parent_id = order.get("parent_recurrence_id")
    if parent_id:
        sched = store.recurring_schedules.get(parent_id)
        if sched is not None:
            recurring_pct = sched["recurring_discount_pct"]
    return min(loyalty_pct + recurring_pct, COMBINED_DISCOUNT_CAP)


def compute_quote_estimate(order, customer, arrangement, zone):
    """Quote-time estimate. Returns dict with pre_credit and discount inputs.
    Evaluation order pinned: surge -> discount -> delivery -> wallet credit."""
    surged = _surged_subtotal(arrangement, order["delivery_date"])
    discount_pct = _discount_pct(customer, order)
    discounted = round_half_up(surged * (1 - discount_pct))
    delivery = zone["base_delivery_fee_cents"]
    pre_credit = discounted + delivery  # wire surcharge NOT known at quote time
    return {"pre_credit": pre_credit, "discount_pct": discount_pct}


def compute_final_total(order, customer, arrangement, zone, wire, subs):
    """Fulfillment-time final total. Reuses the same surge/discount/delivery
    skeleton, then adds wire surcharge and accepted substitution deltas; finally
    subtracts the wallet credit snapshot and floors at 0."""
    surged = _surged_subtotal(arrangement, order["delivery_date"])
    discount_pct = _discount_pct(customer, order)
    discounted = round_half_up(surged * (1 - discount_pct))
    delivery = zone["base_delivery_fee_cents"]
    wire_surcharge = wire["florist_surcharge_cents"] if wire else 0
    subs_sum = 0
    for s in subs:
        if s.get("accepted"):
            subs_sum += s["price_delta_cents"]
    pre_credit = discounted + delivery + wire_surcharge + subs_sum
    final = pre_credit - order.get("wallet_credit_applied_cents", 0)
    return max(0, final)


def substitution_cap_cents(arrangement):
    """Cap for FLORIST_CHOICE: base_price_cents * substitution_cap_pct, rounded."""
    return round_half_up(
        arrangement["base_price_cents"] * arrangement["substitution_cap_pct"]
    )


def compute_claim_refund(claim, order):
    """Reason-weighted fraction of captured final_total_cents, floored per
    reason, capped at the captured amount."""
    captured = order["final_total_cents"]
    reason = claim["reason"]
    raw = round_half_up(captured * REASON_PCT[reason])
    floored = max(raw, REASON_FLOOR_CENTS[reason])
    return min(floored, captured)


def select_fulfilling_florist(order):
    """Wire-service selector. Candidate set: in-zone, accepting, with daily
    capacity headroom for the delivery date. Rank quality_rating DESC, then
    wire_surcharge_cents ASC, tie-break created_at ASC (never id). Returns the
    chosen florist dict or None when the candidate set is empty."""
    zone_id = order["zone_id"]
    delivery_date = order["delivery_date"]
    candidates = []
    for f in store.florists.values():
        if f["covered_zone_id"] != zone_id:
            continue
        if not f["accepting"]:
            continue
        load = florist_daily_load(f["id"], delivery_date)
        if load < f["daily_capacity"]:
            candidates.append(f)
    if not candidates:
        return None
    candidates.sort(
        key=lambda f: (
            -f["quality_rating"],
            f["wire_surcharge_cents"],
            f["created_at"],
            f.get("_seq", 0),
        )
    )
    return candidates[0]


def florist_daily_load(florist_id, delivery_date):
    """Count of non-released WireFulfillments this florist holds for a date."""
    count = 0
    for wf in store.wire_fulfillments.values():
        if wf["florist_id"] != florist_id:
            continue
        if wf["status"] == "RELEASED":
            continue
        if wf["assigned_delivery_date"] == delivery_date:
            count += 1
    return count


def zone_window_bookings(zone_id, slot_date, start_minute, end_minute):
    """Count non-released DeliverySlots sharing the exact same zone, date, and
    half-open [start,end) window."""
    count = 0
    for s in store.delivery_slots.values():
        if s["released"]:
            continue
        if s["zone_id"] != zone_id:
            continue
        if s["slot_date"] != slot_date:
            continue
        if s["slot_start_minute"] == start_minute and s["slot_end_minute"] == end_minute:
            count += 1
    return count


def promote_loyalty_tier(customer):
    """Recompute loyalty_tier from lifetime_delivered_count (already incremented);
    monotonic non-decreasing."""
    n = customer["lifetime_delivered_count"]
    if n >= GOLD_THRESHOLD:
        earned = "GOLD"
    elif n >= SILVER_THRESHOLD:
        earned = "SILVER"
    else:
        earned = "STANDARD"
    current = customer["loyalty_tier"]
    best_rank = max(TIER_ORDER[current], TIER_ORDER[earned])
    customer["loyalty_tier"] = TIER_BY_RANK[best_rank]
