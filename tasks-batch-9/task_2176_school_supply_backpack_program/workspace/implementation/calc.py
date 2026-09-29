"""Calculation rules (scaffold §1.3 / PRD §3)."""
import math
from decimal import Decimal

from db import round_half_up

# --- volunteer_assembly_throughput ----------------------------------------
KITS_PER_VOLUNTEER_HOUR_ASSEMBLY = Decimal("6")
KITS_PER_VOLUNTEER_HOUR_SORTING = Decimal("0")
FATIGUE_FREE_HOURS = Decimal("4")
FATIGUE_STEP = Decimal("0.05")
FATIGUE_FLOOR = Decimal("0.70")
BINS_TO_KITS = 12

# --- purchase_order_costing ------------------------------------------------
ADMIN_TIER_1_CENTS = 50000
ADMIN_TIER_2_CENTS = 200000
ADMIN_RATE_LOW = Decimal("0.09")
ADMIN_RATE_MID = Decimal("0.07")
ADMIN_RATE_HIGH = Decimal("0.05")

# --- teacher_supplemental_budget ------------------------------------------
SUPPLEMENTAL_CAP_PCT = Decimal("0.15")
SCHOOL_SHARE_CAP_PCT = Decimal("0.40")
SCHOOL_SUBCAP_MIN_PARTNERS = 3

# --- school_impact_index ---------------------------------------------------
IMPACT_W_SERVED = Decimal("0.55")
IMPACT_W_FILL = Decimal("0.30")
IMPACT_W_EQUITY = Decimal("0.15")
NO_SHOW_PENALTY = Decimal("0.5")

# --- misc ------------------------------------------------------------------
MINORS_PER_SUPERVISOR = 8
SITE_TURNOVER_BUFFER_MINUTES = 45
LEAD_TIME_HOURS = {"BACK_TO_SCHOOL": 48, "YEAR_ROUND": 2}


def kit_unit_cost(lines, items):
    """SUM over every line of qty_per_student * unit_cost_cents."""
    total = 0
    for line in lines:
        item = items.get(line["supply_item_id"])
        if item is None:
            continue
        total += line["qty_per_student"] * item["unit_cost_cents"]
    return total


def fill_projection(lines, avail_for_line, headcount):
    """distribution_fill_projection — shared shape for both variants.

    `avail_for_line(line)` yields the variant's available units.
    Returns a float rounded half-up to 2 decimals.
    """
    if not lines:
        return 0.00
    covers = []
    for line in lines:
        avail = avail_for_line(line)
        covers.append(avail // line["qty_per_student"])
    coverable_students = min(covers)
    served_projection = min(coverable_students, headcount)
    if headcount == 0:
        return 0.00
    value = Decimal(100) * Decimal(served_projection) / Decimal(headcount)
    return float(round_half_up(value, 2))


def impact_index(served_count, target_student_count, fill_values, title_i_pct,
                 penalty_multiplier):
    """school_impact_index — one rounding, applied last, on the 0..100 value."""
    divisor = Decimal(max(1, int(target_student_count)))
    served_ratio = Decimal(served_count) / divisor
    if served_ratio > Decimal(1):
        served_ratio = Decimal(1)
    if not fill_values:
        fill_quality = Decimal(0)
    else:
        total = Decimal(0)
        for pct in fill_values:
            total += Decimal(str(pct)) / Decimal(100)
        fill_quality = total / Decimal(len(fill_values))
    equity_weight = Decimal(str(title_i_pct))
    base = (IMPACT_W_SERVED * served_ratio
            + IMPACT_W_FILL * fill_quality
            + IMPACT_W_EQUITY * equity_weight)
    index = Decimal(100) * base * Decimal(str(penalty_multiplier))
    return float(round_half_up(index, 2))


def audited_penalty_multiplier(no_show_count, served_audited_count):
    denominator = max(1, no_show_count + served_audited_count)
    no_show_rate = Decimal(no_show_count) / Decimal(denominator)
    return Decimal(1) - NO_SHOW_PENALTY * no_show_rate


def volunteer_throughput(event_type, window_start, window_end, volunteer_count,
                         bin_capacity, open_kit_demand):
    seconds = Decimal(str((window_end - window_start).total_seconds()))
    duration_hours = seconds / Decimal(3600)
    base_rate = (KITS_PER_VOLUNTEER_HOUR_ASSEMBLY if event_type == "ASSEMBLY"
                 else KITS_PER_VOLUNTEER_HOUR_SORTING)
    if duration_hours <= FATIGUE_FREE_HOURS:
        fatigue_factor = Decimal(1)
    else:
        excess = duration_hours - FATIGUE_FREE_HOURS
        steps = Decimal(math.ceil(excess))
        computed = Decimal(1) - FATIGUE_STEP * steps
        fatigue_factor = computed if computed > FATIGUE_FLOOR else FATIGUE_FLOOR
    volunteer_cap = int(
        (Decimal(volunteer_count) * base_rate * duration_hours * fatigue_factor)
        .to_integral_value(rounding="ROUND_FLOOR")
    )
    station_cap = bin_capacity * BINS_TO_KITS
    return min(volunteer_cap, station_cap, open_kit_demand)


def admin_rate_for(line_subtotal_cents):
    if line_subtotal_cents <= ADMIN_TIER_1_CENTS:
        return ADMIN_RATE_LOW
    if line_subtotal_cents <= ADMIN_TIER_2_CENTS:
        return ADMIN_RATE_MID
    return ADMIN_RATE_HIGH


def purchase_costing(requested_unit_gap, bulk_pack_size, unit_cost_cents):
    packs = -(-requested_unit_gap // bulk_pack_size)
    ordered_qty = packs * bulk_pack_size
    line_subtotal_cents = ordered_qty * unit_cost_cents
    admin_rate = admin_rate_for(line_subtotal_cents)
    pack_cost_cents = bulk_pack_size * unit_cost_cents
    pack_fee_cents = int(round_half_up(Decimal(pack_cost_cents) * admin_rate, 0))
    admin_fee_cents = packs * pack_fee_cents
    total_cost_cents = line_subtotal_cents + admin_fee_cents
    return {
        "ordered_qty": ordered_qty,
        "line_subtotal_cents": line_subtotal_cents,
        "admin_fee_cents": admin_fee_cents,
        "total_cost_cents": total_cost_cents,
    }


def supplemental_cap(unrestricted_gross_cents):
    return int((Decimal(unrestricted_gross_cents) * SUPPLEMENTAL_CAP_PCT)
               .to_integral_value(rounding="ROUND_FLOOR"))


def school_share_cap(supplemental_cap_cents):
    return int((Decimal(supplemental_cap_cents) * SCHOOL_SHARE_CAP_PCT)
               .to_integral_value(rounding="ROUND_FLOOR"))


def required_supervisors(minor_volunteer_count):
    return -(-minor_volunteer_count // MINORS_PER_SUPERVISOR)
