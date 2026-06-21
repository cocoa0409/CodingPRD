"""Cross-cutting business logic: derived-field recomputation, loyalty accrual,
weighted-average cost, drawer math. Each function traces to a PRD §3 sentence.
"""
from decimal import Decimal, ROUND_FLOOR

from db import db
from helpers import round_half_up, g3, bump

# --------------------------------------------------------------------------- #
# Constants (scaffold calculations / PRD §3.7, §3.9)
# --------------------------------------------------------------------------- #
TIER_DISCOUNT_CENTS = {"BRONZE": 0, "SILVER": 3, "GOLD": 5}   # §3.7
MAX_DISCOUNT_CENTS = 10                                        # §3.7
POINTS_PER_GALLON = 10                                         # §3.7
POINTS_PER_DOLLAR = 2                                          # §3.7
TIER_MULTIPLIER = {"BRONZE": 1.0, "SILVER": 1.25, "GOLD": 1.5}  # §3.7
SILVER_THRESHOLD = 2000                                        # §3.7
GOLD_THRESHOLD = 5000                                          # §3.7
WASH_LIST_CENTS = {"BASIC": 800, "DELUXE": 1200, "SUPREME": 1600}  # §3.9
TIER_WASH_DISCOUNT_PCT = {"BRONZE": 0.0, "SILVER": 0.10, "GOLD": 0.20}  # §3.9
CODE_TTL_DAYS = 30                                             # §3.9
REDEEM_CENTS_PER_HUNDRED = 100   # whole hundreds of points -> cents value (§3.7)


# --------------------------------------------------------------------------- #
# Loyalty tier (§3.7)
# --------------------------------------------------------------------------- #
def compute_tier(lifetime_points):
    """GOLD if >= 5000, SILVER if >= 2000 (below gold), else BRONZE (§3.7)."""
    if lifetime_points >= GOLD_THRESHOLD:
        return "GOLD"
    if lifetime_points >= SILVER_THRESHOLD:
        return "SILVER"
    return "BRONZE"


def fuel_discount_per_gal(tier):
    """Per-gallon fuel discount: tier discount capped at MAX (§3.7)."""
    tier_disc = TIER_DISCOUNT_CENTS.get(tier, 0)
    return min(tier_disc, MAX_DISCOUNT_CENTS)


def accrue_points(account, *, gallons=0, store_subtotal_cents=0):
    """Compute and apply loyalty point accrual (§3.7).

    base = floor(gallons * 10) + floor(store_subtotal_cents / 100) * 2
    awarded = floor(base * TIER_MULTIPLIER[tier])  # tier read at accrual time
    Returns awarded points; mutates account balance/lifetime/tier and bumps it.
    """
    gallon_term = int((Decimal(str(gallons)) * POINTS_PER_GALLON).to_integral_value(rounding=ROUND_FLOOR))  # floor(g*10)
    dollar_term = (store_subtotal_cents // 100) * POINTS_PER_DOLLAR    # floor()*2
    base_points = gallon_term + dollar_term
    tier = account["tier"]
    awarded = int((Decimal(str(base_points)) * Decimal(str(TIER_MULTIPLIER[tier]))).to_integral_value(rounding=ROUND_FLOOR))
    account["point_balance"] += awarded
    account["lifetime_points"] += awarded
    account["tier"] = compute_tier(account["lifetime_points"])
    bump(account)
    return awarded


def reverse_points(account, awarded):
    """Subtract previously-accrued points from balance and lifetime; recompute
    tier (§3.6 reverse, §3.8 store reverse)."""
    account["point_balance"] -= awarded
    account["lifetime_points"] -= awarded
    account["tier"] = compute_tier(account["lifetime_points"])
    bump(account)


# --------------------------------------------------------------------------- #
# Tank volume / low_stock (§3.4)
# --------------------------------------------------------------------------- #
def recompute_low_stock(tank):
    """low_stock true when volume_gallons <= reorder_point_gallons (§3.2/§3.4)."""
    tank["low_stock"] = tank["volume_gallons"] <= tank["reorder_point_gallons"]


def add_tank_volume(tank, delta_gallons):
    """Move tank volume by delta and recompute low_stock. Caller bumps version."""
    tank["volume_gallons"] = g3(tank["volume_gallons"] + delta_gallons)
    recompute_low_stock(tank)


# --------------------------------------------------------------------------- #
# Weighted-average cost (§3.4)
# --------------------------------------------------------------------------- #
def recompute_wac(grade):
    """Recompute a grade's weighted_avg_cost_cents across all POSTED deliveries
    to tanks of that grade (§3.4).

    WAC = sum(net_gallons * unit_cost_cents) / sum(net_gallons) over posted lots.
    A grade with no posted deliveries keeps 0 (§3.4).
    """
    grade_id = grade["id"]
    # Tanks belonging to this grade.
    tank_ids = {t["id"] for t in db.tanks.values() if t["fuel_grade_id"] == grade_id}
    total_gallons = Decimal("0")
    total_cost = Decimal("0")
    for d in db.deliveries.values():
        if d["status"] != "POSTED":
            continue
        if d["tank_id"] not in tank_ids:
            continue
        ng = Decimal(str(d["net_gallons"]))
        total_gallons += ng
        total_cost += ng * Decimal(str(d["unit_cost_cents"]))
    if total_gallons == 0:
        grade["weighted_avg_cost_cents"] = 0
    else:
        # Per-gallon weighted average cost in cents. Kept as a number; not
        # rounded to whole cents here (it is a per-gallon rate, applied and
        # rounded when producing cents amounts).
        wac = total_cost / total_gallons
        # Represent cleanly: integer if whole, else float.
        as_float = float(wac)
        grade["weighted_avg_cost_cents"] = as_float
    bump(grade)


# --------------------------------------------------------------------------- #
# Shift drawer (§3.5)
# --------------------------------------------------------------------------- #
def recompute_expected_drawer(shift):
    """expected = opening_float + cash_sales - cash_payouts - cash_drops (§3.5)."""
    shift["expected_drawer_cents"] = (
        shift["opening_float_cents"]
        + shift["cash_sales_cents"]
        - shift["cash_payouts_cents"]
        - shift["cash_drops_cents"]
    )


# --------------------------------------------------------------------------- #
# Car-wash price (§3.9)
# --------------------------------------------------------------------------- #
def car_wash_price(package, tier):
    """list_price * (1 - tier_discount_pct), round half-up (§3.9)."""
    list_price = WASH_LIST_CENTS[package]
    disc = TIER_WASH_DISCOUNT_PCT.get(tier, 0.0)
    return round_half_up(Decimal(str(list_price)) * (Decimal("1") - Decimal(str(disc))))
