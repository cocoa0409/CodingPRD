"""The six calculation rules (PRD §3.3-§3.10, SCAFFOLD §1.3).

All money is integer cents. Each rounded component is rounded half-up
independently before summation (PRD §2.7).
"""
import math

from common import round_half_up, hours_floor
from db import db

# Constants (SCAFFOLD §1.3 calculations[].constants, PRD §3.4-§3.10)
GRATUITY_BASE_BPS = 1800
GRATUITY_LARGE_BPS = 2200
GRATUITY_TIER_CENTS = 5000000
GUARANTEE_FLOOR_PCT = 90

DEPOSIT_PCT = 25
DEPOSIT_RUSH_PCT = 50
RUSH_HOURS = 72
DEPOSIT_FLOOR_CENTS = 10000

FULL_REFUND_HOURS = 168
HALF_REFUND_HOURS = 72

CHANGE_FREE_HOURS = 336
CHANGE_TIER_HOURS = 72
CHANGE_BASE_CENTS = 5000
CHANGE_PER_HEAD_CENTS = 150
CHANGE_RUSH_MULT = "1.5"  # Decimal string for exact half-up


# ---------------------------------------------------------------------------
# package_headcount_charge — marginal (step) tiering (PRD §3.4)
# ---------------------------------------------------------------------------
def package_headcount_charge(package, headcount):
    base = package["per_head_cents"]
    # tiers = implicit base tier @0 ++ explicit volume_tiers, sorted by
    # min_headcount ASC.
    tiers = [{"min_headcount": 0, "per_head_cents": base}]
    tiers += sorted(package["volume_tiers"], key=lambda t: t["min_headcount"])

    charge = 0
    for i in range(1, headcount + 1):
        # rate = per_head_cents of the tier with the greatest min_headcount <= i
        rate = base
        for t in tiers:
            if t["min_headcount"] <= i:
                rate = t["per_head_cents"]
            else:
                break
        charge += rate
    return charge


# ---------------------------------------------------------------------------
# effective_headcount — final-count guarantee floor (PRD §3.4)
# ---------------------------------------------------------------------------
def effective_headcount(order):
    floor_count = math.ceil(order["booked_headcount"] * GUARANTEE_FLOOR_PCT / 100)
    return max(order["guaranteed_headcount"], floor_count)


# ---------------------------------------------------------------------------
# order_grand_total — pinned assembly (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
def _addon_effective_quantity(line, variant, eff_headcount):
    if variant == "final" and line["kind"] == "STAFFING" and line["per_head_scaled"]:
        # ceil(effective_headcount / staff_ratio)
        return math.ceil(eff_headcount / line["staff_ratio"])
    return line["quantity"]


def order_grand_total(order, variant):
    package = db.packages[order["package_id"]]
    venue = db.venues[order["venue_id"]]
    client = db.clients[order["client_id"]]

    if variant == "final":
        headcount = effective_headcount(order)
    else:
        headcount = order["booked_headcount"]

    # 1. food
    food = package_headcount_charge(package, headcount)

    # 2. addon_sum — iterated in created_at ASC (id-independent)
    lines = [a for a in db.add_ons.values() if a["order_id"] == order["id"]]
    lines.sort(key=lambda a: (a["created_at"], a["_seq"]))
    addon_sum = 0
    for line in lines:
        qty = _addon_effective_quantity(line, variant, headcount)
        addon_sum += qty * line["unit_cents"]

    # 3. subtotal
    subtotal = food + addon_sum

    # 4. service_fee (round half-up, independent)
    service_fee = round_half_up_bps(subtotal, venue["service_fee_bps"])

    # 5. tax (0 if tax_exempt; else on subtotal only, round half-up)
    if client["tax_exempt"]:
        tax = 0
    else:
        tax = round_half_up_bps(subtotal, venue["tax_rate_bps"])

    # 6. gratuity (0 if OPTIONAL; else tiered bps, round half-up)
    if client["gratuity_policy"] == "OPTIONAL":
        gratuity = 0
    else:
        gratuity_bps = GRATUITY_LARGE_BPS if subtotal >= GRATUITY_TIER_CENTS else GRATUITY_BASE_BPS
        gratuity = round_half_up_bps(subtotal, gratuity_bps)

    # 7. grand_total
    grand_total = subtotal + service_fee + tax + gratuity
    return grand_total


def round_half_up_bps(amount_cents, bps):
    from decimal import Decimal
    return round_half_up(Decimal(amount_cents) * Decimal(bps) / Decimal(10000))


# ---------------------------------------------------------------------------
# deposit_amount — base/rush tier + absolute floor (PRD §3.5)
# ---------------------------------------------------------------------------
def deposit_amount(order):
    from decimal import Decimal
    provisional = order["provisional_total_cents"]
    hours_out = hours_floor((order["event_start"] - db.logical_now()).total_seconds())
    if hours_out < RUSH_HOURS:
        deposit = round_half_up(Decimal(provisional) * Decimal(DEPOSIT_RUSH_PCT) / Decimal(100))
    else:
        deposit = round_half_up(Decimal(provisional) * Decimal(DEPOSIT_PCT) / Decimal(100))
    return max(deposit, DEPOSIT_FLOOR_CENTS)


# ---------------------------------------------------------------------------
# cancellation_settlement — refund tier (PRD §3.9)
# ---------------------------------------------------------------------------
def cancellation_settlement(order):
    from decimal import Decimal
    hours_out = hours_floor((order["event_start"] - db.logical_now()).total_seconds())
    if hours_out >= FULL_REFUND_HOURS:
        fraction = Decimal("1.00")
    elif hours_out >= HALF_REFUND_HOURS:
        fraction = Decimal("0.50")
    else:
        fraction = Decimal("0.00")
    deposit = order["deposit_due_cents"]
    refunded = round_half_up(Decimal(deposit) * fraction)
    forfeited = deposit - refunded  # conserved by subtraction
    return float(fraction), refunded, forfeited


# ---------------------------------------------------------------------------
# change_fee — late/swing threshold (PRD §3.10)
# ---------------------------------------------------------------------------
def change_fee(order, new_headcount):
    from decimal import Decimal
    hours_out = hours_floor((order["event_start"] - db.logical_now()).total_seconds())
    delta = abs(new_headcount - order["booked_headcount"])
    base_plus = CHANGE_BASE_CENTS + delta * CHANGE_PER_HEAD_CENTS
    if hours_out >= CHANGE_FREE_HOURS:
        return 0
    elif hours_out >= CHANGE_TIER_HOURS:
        return base_plus
    else:
        return round_half_up(Decimal(base_plus) * Decimal(CHANGE_RUSH_MULT))


# ---------------------------------------------------------------------------
# route_posture — derived from child leg states (PRD §3.11)
# ---------------------------------------------------------------------------
def route_posture(route_id):
    legs = [l for l in db.delivery_legs.values() if l["route_id"] == route_id]
    statuses = [l["stop_status"] for l in legs]
    if any(s == "FAILED" for s in statuses):
        return "BLOCKED"
    if legs and all(s == "DELIVERED" for s in statuses):
        return "CLOSED"
    if any(s == "DISPATCHED" for s in statuses):
        return "ROLLING"
    return "OPEN"


def dispatched_leg_count(route_id):
    return sum(
        1 for l in db.delivery_legs.values()
        if l["route_id"] == route_id and l["stop_status"] in ("DISPATCHED", "DELIVERED")
    )
