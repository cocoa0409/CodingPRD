"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 2.6, 3.x).

Money: integer cents. Doses: integer cGy. BED: gray with 3 decimals, ROUND_HALF_UP.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import store

# --- Fee schedule ---
FRACTION_DELIVERY_RATE_CENTS = {"THREE_DCRT": 18000, "IMRT": 32000, "SBRT": 55000}
IGRT_FEE_CENTS = 7500
FIRST_FRACTION_SETUP_FEE_CENTS = 12000
SIMULATION_FEE_CENTS = 65000
PHYSICS_CHECK_FEE_CENTS = 25000
NO_SHOW_FEE_CENTS = 5000
PLANNING_BASE_CENTS = {"THREE_DCRT": 90000, "IMRT": 210000, "SBRT": 300000}
PLANNING_EXTRA_TARGET_FACTOR = Decimal("0.25")
ADAPTATION_PLANNING_FACTOR = Decimal("0.5")

# --- BED constants ---
ALPHA_BETA_GY = Decimal("10")
REPOPULATION_K_GY_PER_DAY = Decimal("0.6")
REPOPULATION_KICKOFF_DAY = 28

# --- Thresholds ---
WEIGHT_LOSS_THRESHOLD_PCT = 10.0
CHART_REVIEW_FRACTION_LIMIT = 5
DISCOUNT_TIER_THRESHOLD_CENTS = 1500000
DISCOUNT_RATE = Decimal("0.05")
LINAC_TURNOVER_MINUTES = 10
SIM_DAILY_CAPACITY = 8


def rhu_int(x):
    """Round half up to an integer (Decimal-safe)."""
    if not isinstance(x, Decimal):
        x = Decimal(x)
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gy3(x):
    """Round half up to 3 decimal places; returns a float for JSON output."""
    if not isinstance(x, Decimal):
        x = Decimal(x)
    return float(x.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def alloc_base(target_total_cgy, n_fractions):
    """fraction_dose_allocation base: round_half_up(D / n)."""
    return rhu_int(Decimal(target_total_cgy) / Decimal(n_fractions))


def delivered_under_plan(plan_id):
    """(count, dose_sum) of DELIVERED sessions treating under this plan."""
    count = 0
    dose = 0
    for s in store.sessions.values():
        if s["plan_id"] == plan_id and s["status"] == "DELIVERED":
            count += 1
            dose += s["dose_delivered_cGy"] or 0
    return count, dose


def next_delivery_dose(plan):
    """Dose for the plan's next delivery: base for every fraction but the last
    remaining one; the last carries the remainder (target - delivered so far)."""
    delivered_count, delivered_dose = delivered_under_plan(plan["id"])
    remaining_count = plan["planned_fractions"] - delivered_count
    if remaining_count <= 1:
        return plan["target_total_dose_cGy"] - delivered_dose
    return plan["dose_per_fraction_cGy"]


def bed_nominal(course):
    """n * d * (1 + d/10), d = dose_per_fraction_cGy/100 Gy; 3dp half-up."""
    d = Decimal(course["dose_per_fraction_cGy"]) / Decimal(100)
    n = course["planned_fractions"]
    val = Decimal(n) * d * (Decimal(1) + d / ALPHA_BETA_GY)
    return gy3(val)


def bed_actual(course):
    """Sum over DELIVERED sessions of d_i*(1 + d_i/10), minus the repopulation
    penalty 0.6 Gy/day beyond day 28 of the first-to-last delivery span.
    Floored at zero; 3dp half-up."""
    sessions = [s for s in store.sessions.values()
                if s["course_id"] == course["id"] and s["status"] == "DELIVERED"]
    sessions.sort(key=lambda s: (s["_start"], s["_seq"]))
    total = Decimal(0)
    for s in sessions:
        d = Decimal(s["dose_delivered_cGy"] or 0) / Decimal(100)
        total += d * (Decimal(1) + d / ALPHA_BETA_GY)
    if len(sessions) >= 2:
        span_days = int((sessions[-1]["_start"] - sessions[0]["_start"]).total_seconds() // 86400)
    else:
        span_days = 0
    penalty = REPOPULATION_K_GY_PER_DAY * max(0, span_days - REPOPULATION_KICKOFF_DAY)
    val = total - penalty
    if val < 0:
        val = Decimal(0)
    return gy3(val)


def planning_charge_cents(technique, n_target_volumes, is_adaptation):
    """Tiered planning charge: base * (1 + 0.25*(t-1)); adaptation bills half.
    round_half_up applied exactly once at the end."""
    t = max(1, n_target_volumes)
    multiplier = Decimal(1) + PLANNING_EXTRA_TARGET_FACTOR * (t - 1)
    full = Decimal(PLANNING_BASE_CENTS[technique]) * multiplier
    if is_adaptation:
        full = full * ADAPTATION_PLANNING_FACTOR
    return rhu_int(full)


def claim_discount(lines):
    """Pinned waterfall: gross -> tier check (>1.5M cents) -> discount base is
    FRACTION_DELIVERY + IGRT lines only -> 5% half-up -> final = gross - discount."""
    gross = sum(l["amount_cents"] for l in lines)
    if gross > DISCOUNT_TIER_THRESHOLD_CENTS:
        base = sum(l["amount_cents"] for l in lines
                   if l["code"] in ("FRACTION_DELIVERY", "IGRT"))
        discount = rhu_int(DISCOUNT_RATE * Decimal(base))
    else:
        discount = 0
    return gross, discount, gross - discount


def provisional_total(claim, course):
    """Forward-looking estimate: incurred lines + undelivered planned fractions
    times the bare delivery rate. NO_SHOW sessions do not reduce remaining."""
    incurred = sum(l["amount_cents"] for l in store.lines.values()
                   if l["claim_id"] == claim["id"])
    remaining = course["planned_fractions"] - course["delivered_fractions"]
    projected = max(0, remaining) * FRACTION_DELIVERY_RATE_CENTS[course["technique"]]
    return incurred + projected
