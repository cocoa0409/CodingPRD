"""Reservation calculations and lifecycle helpers (PRD §3.5–§3.7).

Money is integer cents; surge and discount introduce fractional cents and are
rounded half-up (PRD §2.7). Pass discount rounds PER LINE ITEM then sums.
"""
import db
from services.common import round_half_up


QUEUE_PRIORITY = {"VIP": 0, "FAST_PASS": 1, "GA": 2}


def attraction_of_slot(slot):
    return db.attractions.get(slot["attraction_id"])


def select_pricing_rule(attraction_id, tier):
    """The single active PricingRule matching (attraction_id, tier), or None."""
    for rule in db.pricing_rules.values():
        if rule["attraction_id"] == attraction_id and rule["tier"] == tier:
            return rule
    return None


def slot_demand_ratio(slot):
    cap = slot["capacity"]
    if cap == 0:
        return 0.0
    return (slot["reserved_count"] + slot["admitted_count"]) / cap


def dynamic_ticket_price(rule, ratio):
    """Tiered demand pricing (calc dynamic_ticket_price, PRD §3.2).

    ratio == low_demand_max_ratio stays LOW (<=); ratio == high_demand_min_ratio
    is HIGH (>=); strictly between is MID.
    """
    if ratio <= rule["low_demand_max_ratio"]:
        surge_pct = 0
    elif ratio >= rule["high_demand_min_ratio"]:
        surge_pct = rule["high_surge_pct"]
    else:
        surge_pct = rule["mid_surge_pct"]
    return round_half_up(rule["base_price_cents"] * (100 + surge_pct) / 100)


def tickets_of(reservation_id):
    return [t for t in db.tickets.values() if t["reservation_id"] == reservation_id]
