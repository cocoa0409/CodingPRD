"""Calculation rules (scaffold §1.3 / PRD §3). All rounding is round-half-up
at the pinned rounding points only (PRD §2.5)."""

import math
from datetime import timedelta

from decimal import Decimal

import constants as C
from util import dec, round0, round2


# ---------------------------------------------------------------------------
# wear_index + recommended_path (assessment creation)
# ---------------------------------------------------------------------------
def compute_wear_index(pd, sr, bl):
    raw = (
        dec(C.W_PD) * (dec(pd) / dec(C.PD_REF))
        + dec(C.W_SR) * (dec(sr) / dec(C.SR_REF))
        + dec(C.W_BL) * (dec(bl) / dec(C.BL_REF))
    )
    clamped = min(raw, dec(C.WEAR_CLAMP))
    return round2(clamped * 100)


def recommended_path_for(wear_index):
    """wear_index is a Decimal rounded to 2 places. Boundaries inclusive."""
    if wear_index >= dec(C.FULL_THRESHOLD):
        return "FULL_REBUILD"
    if wear_index >= dec(C.MECH_THRESHOLD):
        return "MECHANICAL_REBUILD"
    return "RETROFIT_ONLY"


# ---------------------------------------------------------------------------
# Part line snapshot (line creation): per-line rounding pinned here
# ---------------------------------------------------------------------------
def compute_line_total(quantity, unit_price_cents, obs_multiplier):
    return round0(dec(quantity) * dec(unit_price_cents) * dec(obs_multiplier))


# ---------------------------------------------------------------------------
# Quote computation (pinned evaluation order: per-line sum -> labor -> base
# -> subtotal -> tier discount on subtotal -> trade-in credit last)
# ---------------------------------------------------------------------------
def compute_quote(project, lines, assessment):
    parts_total = sum(
        line["line_total_cents"] for line in lines if line["status"] != "CANCELLED"
    )
    labor_hours = C.BASE_HOURS[project["decision"]] + math.floor(
        float(assessment["wear_index"])
    )
    labor_cents = labor_hours * C.LABOR_RATE_CENTS
    base_price = C.BASE_PRICE_CENTS[project["decision"]]
    subtotal = base_price + parts_total + labor_cents
    if subtotal >= C.TIER2_MIN:
        discount = round0(dec(subtotal) * dec(C.TIER2_RATE))
    elif subtotal >= C.TIER1_MIN:
        discount = round0(dec(subtotal) * dec(C.TIER1_RATE))
    else:
        discount = 0
    quote_price = subtotal - discount - project["applied_trade_in_credit_cents"]
    return {
        "base_price_cents": base_price,
        "parts_total_cents": parts_total,
        "labor_cents": labor_cents,
        "discount_cents": discount,
        "quote_price_cents": quote_price,
    }


# ---------------------------------------------------------------------------
# Residual valuation (trade-in offer creation); both variants always computed
# ---------------------------------------------------------------------------
def compute_valuations(machine, latest_assessment, clock_now):
    age_years = clock_now.year - machine["year_of_manufacture"]
    if latest_assessment is not None:
        condition_factor = max(
            dec("0.25"), dec(1) - dec(latest_assessment["wear_index"]) / dec("200.0")
        )
    else:
        condition_factor = dec("0.50")

    market_value = round0(
        dec(C.MARKET_BASE_CENTS[machine["machine_type"]])
        * (dec(1) - dec(C.DEPRECIATION)) ** age_years
        * condition_factor
    )

    remaining_life_fraction = max(dec(0), dec(25 - age_years) / dec(25))
    if latest_assessment is not None:
        rebuild_cost = C.BASE_PRICE_CENTS[latest_assessment["recommended_path"]]
    else:
        rebuild_cost = C.BASE_PRICE_CENTS["MECHANICAL_REBUILD"]
    cost_value = max(
        C.SCRAP_FLOOR,
        round0(
            dec(C.REPLACEMENT_COST_CENTS[machine["machine_type"]])
            * remaining_life_fraction
            - dec(rebuild_cost)
        ),
    )
    return market_value, cost_value


# ---------------------------------------------------------------------------
# Acceptance evaluation (dual variant; boundaries inclusive on both checks)
# ---------------------------------------------------------------------------
def evaluate_acceptance(samples, repeatability_microns, decision):
    max_abs = round2(max(abs(dec(s)) for s in samples))
    if decision == "FULL_REBUILD":
        variant = "ISO_STATISTICAL"
        values = [float(dec(s)) for s in samples]
        mean = sum(values) / len(values)
        variance = sum((s - mean) ** 2 for s in values) / len(values)
        std = math.sqrt(variance)
        statistic = round2(abs(mean) + 2 * std)
    else:
        variant = "WORST_CASE"
        statistic = max_abs
    passed = statistic <= dec(C.TOL_POS) and dec(repeatability_microns) <= dec(C.TOL_REP)
    return variant, max_abs, statistic, passed


# ---------------------------------------------------------------------------
# Warranty drift (temporal gate first, then strictly-greater drift gate)
# ---------------------------------------------------------------------------
def compute_drift(measured_positioning_microns, accepted_positioning_microns):
    return round2(
        dec(measured_positioning_microns) - dec(accepted_positioning_microns)
    )


# ---------------------------------------------------------------------------
# Rework surcharges
# ---------------------------------------------------------------------------
def fail_surcharge(quote_price_cents):
    return round0(dec(quote_price_cents) * dec(C.FAIL_RATE))


def escalation_surcharge(quote_price_cents):
    return round0(dec(quote_price_cents) * dec(C.ESCALATION_RATE))


# ---------------------------------------------------------------------------
# Downtime window overlap: half-open [s, e) intervals; adjacency allowed
# ---------------------------------------------------------------------------
def windows_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


# ---------------------------------------------------------------------------
# Shipment stage tiling: closed-bounds containment + MIN_GAP_DAYS sibling gap
# ---------------------------------------------------------------------------
def stage_contained(window, ship, ret):
    return window["_starts_dt"] <= ship and ret <= window["_ends_dt"]


def stage_gap_ok(ship, ret, other_ship, other_ret):
    gap = timedelta(days=C.MIN_GAP_DAYS)
    return ship >= other_ret + gap or other_ship >= ret + gap
