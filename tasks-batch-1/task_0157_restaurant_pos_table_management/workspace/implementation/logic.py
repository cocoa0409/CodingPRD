"""Business-logic services: calculations, check recompute, cascades (PRD §3)."""
from decimal import Decimal

import db
from common import round_half_up_bps, floor_bps, touch


# ---------------------------------------------------------------------------
# Lookups across collections
# ---------------------------------------------------------------------------
def modifiers_for_item(order_item_id):
    return [m for m in db.item_modifiers.values()
            if m["order_item_id"] == order_item_id]


def items_for_course(course_id):
    return [oi for oi in db.order_items.values()
            if oi["course_id"] == course_id]


def courses_for_check(check_id):
    return [c for c in db.courses.values() if c["check_id"] == check_id]


def items_for_check(check_rec):
    """All order items belonging to any course of this check."""
    course_ids = {c["id"] for c in courses_for_check(check_rec["id"])}
    return [oi for oi in db.order_items.values() if oi["course_id"] in course_ids]


def checks_for_seating(seating_id):
    return [c for c in db.checks.values() if c["seating_id"] == seating_id]


# ---------------------------------------------------------------------------
# Happy-hour evaluation (PRD §3.1)
# ---------------------------------------------------------------------------
def fired_at_in_window(restaurant_id, fired_at_dt):
    """True if fired_at falls in an active happy-hour window for the restaurant.

    Inside when a window exists with day_of_week == ISO weekday(fired_at),
    start_minute <= minute_of_day(fired_at) < end_minute.
    """
    if fired_at_dt is None:
        return False
    weekday = fired_at_dt.isoweekday()  # 1=Mon .. 7=Sun
    minute_of_day = fired_at_dt.hour * 60 + fired_at_dt.minute
    for w in db.happy_hour_windows.values():
        if w["restaurant_id"] != restaurant_id:
            continue
        if w["day_of_week"] != weekday:
            continue
        if w["start_minute"] <= minute_of_day < w["end_minute"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Line subtotal helpers
# ---------------------------------------------------------------------------
def line_value(oi, unit_price):
    surcharge_sum = sum(m["surcharge_cents"] for m in modifiers_for_item(oi["id"]))
    return oi["quantity"] * unit_price + oi["quantity"] * surcharge_sum


# ---------------------------------------------------------------------------
# Provisional subtotal (PRD §3.6, calculations.provisional_check_subtotal)
# ---------------------------------------------------------------------------
def provisional_subtotal(check_rec):
    total = 0
    for oi in items_for_check(check_rec):
        if oi["status"] in ("FIRED", "SERVED", "COMPED"):
            total += line_value(oi, oi["unit_price_cents"])
    return total


# ---------------------------------------------------------------------------
# Final subtotal (PRD §3.6, calculations.final_check_subtotal)
# ---------------------------------------------------------------------------
def final_subtotal(check_rec):
    total = 0
    fired_courses = [c for c in courses_for_check(check_rec["id"])
                     if c["status"] == "FIRED"]
    # ordered by fired_at ASC, then created_at (== _seq) ASC
    fired_courses.sort(key=lambda c: (c["fired_at"], c["_seq"]))
    for c in fired_courses:
        in_window = fired_at_in_window(check_rec["restaurant_id"], c["fired_at"])
        for oi in items_for_course(c["id"]):
            if oi["status"] not in ("FIRED", "SERVED", "COMPED"):
                continue
            mi = db.menu_items[oi["menu_item_id"]]
            price = mi["happy_hour_price_cents"] if in_window else mi["base_price_cents"]
            total += line_value(oi, price)
    return total


# ---------------------------------------------------------------------------
# Downstream money resolution (PRD §3.6, calculations.auto_gratuity)
# Pinned order: base -> comp_total(capped) -> comped_subtotal -> gratuity -> tax -> total
# ---------------------------------------------------------------------------
def resolve_check_totals(check_rec, base_subtotal):
    rest = db.restaurants[check_rec["restaurant_id"]]

    raw_comp = sum(oi["comp_amount_cents"] for oi in items_for_check(check_rec)
                   if oi["status"] == "COMPED")
    cap = floor_bps(base_subtotal, rest["comp_cap_bps"])
    comp_total = min(raw_comp, cap)

    comped_subtotal = base_subtotal - comp_total

    if check_rec["party_size"] >= rest["large_party_threshold"]:
        auto_gratuity = round_half_up_bps(comped_subtotal, rest["auto_gratuity_bps"])
    else:
        auto_gratuity = 0

    tax = round_half_up_bps(comped_subtotal, rest["tax_rate_bps"])
    total_due = comped_subtotal + tax + auto_gratuity

    check_rec["comp_total_cents"] = comp_total
    check_rec["auto_gratuity_cents"] = auto_gratuity
    check_rec["tax_cents"] = tax
    check_rec["total_due_cents"] = total_due


def recompute_check_open(check_rec):
    """Recompute provisional subtotal + downstream totals while OPEN."""
    sub = provisional_subtotal(check_rec)
    check_rec["provisional_subtotal_cents"] = sub
    resolve_check_totals(check_rec, sub)


def recompute_payment_aggregates(check_rec):
    settled = [p for p in db.payments.values()
               if p["check_id"] == check_rec["id"] and p["status"] == "SETTLED"]
    check_rec["amount_paid_cents"] = sum(p["amount_cents"] for p in settled)
    check_rec["tip_cents"] = sum(p["tip_cents"] for p in settled)


def comp_cap_for_check(check_rec, base_subtotal=None):
    """The comp ceiling in cents = floor(base_subtotal * comp_cap_bps / 10000)."""
    rest = db.restaurants[check_rec["restaurant_id"]]
    if base_subtotal is None:
        base_subtotal = base_subtotal_for_check(check_rec)
    return floor_bps(base_subtotal, rest["comp_cap_bps"])


def base_subtotal_for_check(check_rec):
    """The current base subtotal: provisional while OPEN, locked final once PRESENTED."""
    if check_rec["status"] == "PRESENTED" and check_rec["final_subtotal_cents"] is not None:
        return check_rec["final_subtotal_cents"]
    return check_rec["provisional_subtotal_cents"]
