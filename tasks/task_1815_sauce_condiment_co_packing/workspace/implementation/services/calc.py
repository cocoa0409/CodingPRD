"""Calculation rules (scaffold Table 3 / PRD §3.5-§3.7).

- estimated_run_charge / final_run_charge: dual-variant run charge with
  per-line round-half-up to whole cents before summation (never sum-then-round).
- changeover_fee: predecessor-based, allergen-conditional, locked at confirm.
- hold_deviation_metrics: letter_deviation / statutory_margin, 2dp half-up.
- kettle_line_overlap_check: allergen-conditional 4h/1h buffered intervals.
- pilot_cell_overlap_check: zero-buffer half-open intervals (touch allowed).
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import STORE

STANDARD_CHANGEOVER_FEE_CENTS = 15000
ALLERGEN_CHANGEOVER_FEE_CENTS = 75000
STANDARD_GAP_HOURS = 1
ALLERGEN_CHANGEOVER_BUFFER_HOURS = 4
PH_STATUTORY_CEILING = Decimal("4.6")
AW_STATUTORY_CEILING = Decimal("0.85")

# Kettle-line occupancy states (PLANNED, CANCELLED, DESTROYED excluded).
OCCUPYING_STATUSES = {"CONFIRMED", "COMPLETED", "ON_HOLD", "REWORK", "RELEASED"}

_CENT = Decimal("1")
_TWO_DP = Decimal("0.01")


def _line_cents(quantity_per_unit, units, unit_cost_cents):
    """One extended line, rounded half-up to whole cents (PRD §2.6)."""
    val = Decimal(str(quantity_per_unit)) * Decimal(units) * Decimal(str(unit_cost_cents))
    return int(val.quantize(_CENT, rounding=ROUND_HALF_UP))


def supplies_of(formula_id):
    return [s for s in STORE.supplies.values() if s["formula_id"] == formula_id]


def formula_of(run):
    return STORE.formulas.get(run["formula_id"])


def active_letter_for(formula_id):
    """At most one ACTIVE letter per formula is ever live (activation supersedes)."""
    for letter in STORE.letters.values():
        if letter["formula_id"] == formula_id and letter["status"] == "ACTIVE":
            return letter
    return None


# ---------------------------------------------------------------------------
# Run charge (estimate at confirm, final at each complete)
# ---------------------------------------------------------------------------

def compute_run_charge(run, formula, units_for_billing, units_for_packaging):
    """units_billed = max(billing units, formula.min_run_units); ingredient
    lines extend against units_billed, packaging lines against the physical
    units passed in (planned for estimate, actual for final). The changeover
    fee is the value locked on the run."""
    units_billed = max(units_for_billing, formula["min_run_units"])
    base_cents = units_billed * formula["unit_rate_cents"]
    ingredient_cents = sum(
        _line_cents(s["quantity_per_unit"], units_billed, s["unit_cost_cents"])
        for s in supplies_of(formula["id"])
        if s["sourcing_mode"] == "COPACKER_SUPPLIED"
    )
    packaging_cents = sum(
        _line_cents(
            line["quantity_per_unit"],
            units_for_packaging,
            STORE.components[line["component_id"]]["unit_cost_cents"],
        )
        for line in run["packaging_requirements"]
    )
    return base_cents + run["changeover_fee_cents"] + ingredient_cents + packaging_cents


def compute_estimate(run, formula):
    """Estimate variant: planned_units drive units_billed and every line."""
    return compute_run_charge(run, formula, run["planned_units"], run["planned_units"])


def compute_final(run, formula, actual_units_produced):
    """Final variant: units_billed = max(actual, min_run); packaging lines use
    actual_units_produced; ingredient lines use units_billed."""
    return compute_run_charge(run, formula, actual_units_produced, actual_units_produced)


# ---------------------------------------------------------------------------
# Kettle-line interval rule and changeover fee (PRD §3.5)
# ---------------------------------------------------------------------------

def kettle_occupiers(run):
    return [
        r for r in STORE.runs.values()
        if r["kettle_line_id"] == run["kettle_line_id"]
        and r["id"] != run["id"]
        and r["status"] in OCCUPYING_STATUSES
    ]


def kettle_line_conflict(run):
    """Allergen-conditional buffered intervals. A gap of exactly the required
    size is acceptable (conflict iff strictly smaller); intersecting windows
    always conflict."""
    allergen = formula_of(run)["allergen_class"]
    for other in kettle_occupiers(run):
        other_allergen = formula_of(other)["allergen_class"]
        required = (
            timedelta(hours=ALLERGEN_CHANGEOVER_BUFFER_HOURS)
            if other_allergen != allergen
            else timedelta(hours=STANDARD_GAP_HOURS)
        )
        if other["scheduled_end"] <= run["scheduled_start"]:
            if run["scheduled_start"] - other["scheduled_end"] < required:
                return True
        elif run["scheduled_end"] <= other["scheduled_start"]:
            if other["scheduled_start"] - run["scheduled_end"] < required:
                return True
        else:
            return True
    return False


def changeover_fee(run):
    """Predecessor = latest scheduled_end among same-line occupiers ending at
    or before this run's start (tie-break: latest created_at). Allergen switch
    -> 75000; match or no predecessor -> 15000."""
    candidates = [
        o for o in kettle_occupiers(run)
        if o["scheduled_end"] <= run["scheduled_start"]
    ]
    if not candidates:
        return STANDARD_CHANGEOVER_FEE_CENTS
    predecessor = max(
        candidates,
        key=lambda r: (r["scheduled_end"], r["created_at"], r["_seq"]),
    )
    if formula_of(predecessor)["allergen_class"] != formula_of(run)["allergen_class"]:
        return ALLERGEN_CHANGEOVER_FEE_CENTS
    return STANDARD_CHANGEOVER_FEE_CENTS


# ---------------------------------------------------------------------------
# Pilot-cell interval rule (PRD §3.2): zero buffer, touching windows allowed
# ---------------------------------------------------------------------------

def pilot_cell_conflict(pilot_cell_id, scheduled_start, scheduled_end):
    for t in STORE.trials.values():
        if t["pilot_cell_id"] != pilot_cell_id or t["status"] != "SCHEDULED":
            continue
        if not (t["scheduled_end"] <= scheduled_start or scheduled_end <= t["scheduled_start"]):
            return True
    return False


# ---------------------------------------------------------------------------
# Hold deviation metrics (PRD §3.7): 2 decimal places, round half-up
# ---------------------------------------------------------------------------

def hold_deviation_metrics(reason_category, measured_ph, measured_water_activity, letter):
    """Returns (letter_deviation, statutory_margin); both null when the reason
    is not a deviation category or the formula has no ACTIVE letter."""
    if letter is None:
        return None, None
    if reason_category == "PH_DEVIATION":
        letter_deviation = Decimal(str(measured_ph)) - Decimal(str(letter["max_ph"]))
        statutory_margin = PH_STATUTORY_CEILING - Decimal(str(measured_ph))
    elif reason_category == "AW_DEVIATION":
        letter_deviation = Decimal(str(measured_water_activity)) - Decimal(str(letter["max_water_activity"]))
        statutory_margin = AW_STATUTORY_CEILING - Decimal(str(measured_water_activity))
    else:
        return None, None
    return (
        float(letter_deviation.quantize(_TWO_DP, rounding=ROUND_HALF_UP)),
        float(statutory_margin.quantize(_TWO_DP, rounding=ROUND_HALF_UP)),
    )
