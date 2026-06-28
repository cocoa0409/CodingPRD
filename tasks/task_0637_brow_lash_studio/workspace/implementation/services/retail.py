"""Retail order total calculation (PRD §3.9 / calculations.retail_order_total).

Pinned rounding order: discount + round PER LINE, THEN sum. Peak surcharge is a
combinatorial conditional over (tech same-day load, premium-ness)."""
from common import round_half_up
from db import store

PEAK_LOAD_THRESHOLD = 3
PEAK_SURCHARGE_PCT = 0.15


def loyalty_discount_for_member(member_id):
    """The member's plan loyalty_discount_pct if they hold an ACTIVE or PAST_DUE
    membership, else 0 (PRD §3.9)."""
    best = None
    for ms in store.memberships.values():
        if ms["member_id"] != member_id:
            continue
        if ms["status"] in ("ACTIVE", "PAST_DUE"):
            plan = store.membership_plans.get(ms["plan_id"])
            if plan:
                # If multiple qualifying memberships exist, use the discount of
                # an ACTIVE/PAST_DUE one. Pick the first by creation order.
                if best is None or ms.get("_seq", 0) < best[0]:
                    best = (ms.get("_seq", 0), plan["loyalty_discount_pct"])
    return best[1] if best else 0.0


def compute_totals(member_id, lines, linked_appointment):
    loyalty = loyalty_discount_for_member(member_id)
    subtotal = 0
    for line in lines:
        unit = line["unit_price_cents"]
        qty = line["quantity"]
        line_cents = round_half_up(unit * qty * (1 - loyalty))
        subtotal += line_cents

    # Peak surcharge.
    tech_id = linked_appointment["lash_tech_id"]
    appt_date = linked_appointment["start_utc"].date()
    tech_load = 0
    for appt in store.appointments.values():
        if appt["lash_tech_id"] != tech_id:
            continue
        if appt["status"] != "BOOKED":
            continue
        if appt["start_utc"].date() == appt_date:
            tech_load += 1

    st = store.service_types.get(linked_appointment["service_type_id"])
    is_premium = bool(st and st["category"] == "PREMIUM")

    if tech_load >= PEAK_LOAD_THRESHOLD and is_premium:
        peak = round_half_up(subtotal * PEAK_SURCHARGE_PCT)
    else:
        peak = 0
    total = subtotal + peak
    return subtotal, peak, total
