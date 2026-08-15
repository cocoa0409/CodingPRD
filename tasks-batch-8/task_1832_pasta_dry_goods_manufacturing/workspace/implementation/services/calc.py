"""Calculation rules (scaffold §1.3 / PRD §3): grading, settlement pricing,
changeover, drying projection, case plan, shelf-life. All money is integer
cents; scores/moistures are 2dp round-half-up; the index ratio is 4dp
round-half-up. Decimal arithmetic throughout — never float money."""
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from db import dec, num_out, store

# ------------------------------------------------------------ semolina_grade
_PROTEIN_FLOOR = Decimal("10.0")
_PROTEIN_SPAN = Decimal("4.0")
_FALLING_FLOOR_S = Decimal("200.0")
_FALLING_SPAN_S = Decimal("200.0")
_MOISTURE_CEIL = Decimal("16.0")
_MOISTURE_SPAN = Decimal("6.0")
_GRADE_A_MIN = Decimal("70.0")
_GRADE_B_MIN = Decimal("50.0")

_2DP = Decimal("0.01")
_4DP = Decimal("0.0001")


def _clamp(x, lo=Decimal("0"), hi=Decimal("100")):
    return min(max(x, lo), hi)


def semolina_grade(protein_pct, moisture_pct, gluten_index, falling_number_s):
    """Weighted scoring; returns (score: Decimal 2dp, grade: str)."""
    protein_score = _clamp((dec(protein_pct) - _PROTEIN_FLOOR) / _PROTEIN_SPAN * 100)
    gluten_score = _clamp(dec(gluten_index))
    falling_score = _clamp((dec(falling_number_s) - _FALLING_FLOOR_S) / _FALLING_SPAN_S * 100)
    moisture_score = _clamp((_MOISTURE_CEIL - dec(moisture_pct)) / _MOISTURE_SPAN * 100)
    score = (Decimal("0.40") * protein_score
             + Decimal("0.25") * gluten_score
             + Decimal("0.20") * falling_score
             + Decimal("0.15") * moisture_score).quantize(_2DP, rounding=ROUND_HALF_UP)
    if score >= _GRADE_A_MIN:
        grade = "GRADE_A"
    elif score >= _GRADE_B_MIN:
        grade = "GRADE_B"
    else:
        grade = "GRADE_REJECT"
    return score, grade


# -------------------------------------------------- contract_settlement_price
_TIER2_MIN_KG = Decimal("20000")
_TIER3_MIN_KG = Decimal("50000")
_TIER2_DISCOUNT = Decimal("0.02")
_TIER3_DISCOUNT = Decimal("0.05")
_SPOT_BLEND_WINDOW_DAYS = 30
_CENT = Decimal("1")


def _index_ratio(contract, delivery_date):
    readings = [r for r in store.index_readings.values() if r["contract_id"] == contract["id"]]
    reference = dec(contract["reference_index_value"])
    if contract["pricing_method"] == "INDEX_LAGGED":
        month_start = delivery_date.replace(day=1)
        cands = [r for r in readings if r["effective_date"] <= month_start]
        if not cands:
            return Decimal("1.0000")
        best = max(cands, key=lambda r: (r["effective_date"], r.get("_seq", 0)))
        ratio = dec(best["index_value"]) / reference
    else:  # SPOT_BLEND
        window_start = delivery_date - timedelta(days=_SPOT_BLEND_WINDOW_DAYS)
        window = [r for r in readings
                  if window_start <= r["effective_date"] <= delivery_date]
        if window:
            mean = sum(dec(r["index_value"]) for r in window) / Decimal(len(window))
            ratio = mean / reference
        else:
            pre = [r for r in readings if r["effective_date"] < window_start]
            if not pre:
                return Decimal("1.0000")
            best = max(pre, key=lambda r: (r["effective_date"], r.get("_seq", 0)))
            ratio = dec(best["index_value"]) / reference
    return ratio.quantize(_4DP, rounding=ROUND_HALF_UP)


def settlement_price(contract, delivery_date, received_weight_kg):
    """Returns (unit_price_cents, total_price_cents) as ints.

    Pinned evaluation order: ratio (4dp) -> tier from cumulative BEFORE this
    delivery -> unit price (integer cents, half-up) -> total (integer cents,
    half-up). The contract's cumulative is NOT mutated here (caller does that
    after pricing).
    """
    ratio = _index_ratio(contract, delivery_date)
    cumulative = dec(contract["cumulative_delivered_kg"])
    if cumulative < _TIER2_MIN_KG:
        discount = Decimal("0")
    elif cumulative < _TIER3_MIN_KG:
        discount = _TIER2_DISCOUNT
    else:
        discount = _TIER3_DISCOUNT
    unit = (dec(contract["base_price_cents_per_kg"]) * ratio * (Decimal("1") - discount)
            ).quantize(_CENT, rounding=ROUND_HALF_UP)
    total = (unit * dec(received_weight_kg)).quantize(_CENT, rounding=ROUND_HALF_UP)
    return int(unit), int(total)


# ---------------------------------------------------------- changeover_minutes
def _family_of(run):
    recipe = store.recipes.get(run["recipe_id"])
    return recipe["shape_family"] if recipe else None


def _mounted_die(line_id):
    for die in store.extrusion_dies.values():
        if die["status"] == "MOUNTED" and die["mounted_line_id"] == line_id:
            return die
    return None


def changeover_base(pred_family, new_family):
    if pred_family is None:
        return 45
    if pred_family == new_family:
        return 30
    if new_family == "SPECIALTY":
        return 90
    if pred_family == "SPECIALTY":
        return 75
    return 60  # LONG_CUT <-> SHORT_CUT


def compute_changeover(line_id, new_recipe, new_start, exclude_run_id=None):
    """changeover_minutes = base + wear_adder + allergen_adder (integer)."""
    candidates = [r for r in store.production_runs.values()
                  if r["line_id"] == line_id
                  and r["id"] != exclude_run_id
                  and r["production_status"] != "ABORTED"
                  and r["scheduled_end"] <= new_start]
    predecessor = None
    if candidates:
        predecessor = max(candidates, key=lambda r: (r["scheduled_end"],
                                                     r["created_at"],
                                                     r.get("_seq", 0)))
    pred_family = _family_of(predecessor) if predecessor else None
    base = changeover_base(pred_family, new_recipe["shape_family"])

    wear_adder = 0
    die = _mounted_die(line_id)
    if die is not None:
        ratio = dec(die["extruded_kg"]) / dec(die["rated_capacity_kg"])
        if ratio >= Decimal("0.80"):
            wear_adder = 40
        elif ratio >= Decimal("0.50"):
            wear_adder = 15

    allergen_adder = 0
    if (predecessor is not None and predecessor["gluten_free"]
            and not new_recipe["gluten_free"]):
        allergen_adder = 20

    return base + wear_adder + allergen_adder


def line_window_overlaps(line_id, new_start, new_end, new_changeover, exclude_run_id=None):
    """Half-open buffered occupancy intersection; adjacency permitted."""
    new_lo = new_start - timedelta(minutes=new_changeover)
    for other in store.production_runs.values():
        if (other["line_id"] != line_id or other["id"] == exclude_run_id
                or other["production_status"] == "ABORTED"):
            continue
        other_lo = other["scheduled_start"] - timedelta(minutes=other["changeover_minutes"])
        if new_lo < other["scheduled_end"] and other_lo < new_end:
            return True
    return False


def line_has_inflight_run(line_id):
    for run in store.production_runs.values():
        if (run["line_id"] == line_id and run["production_status"]
                in ("MIXING", "EXTRUDING", "DRYING", "PACKAGING")):
            return True
    return False


# ---------------------------------------------------- drying_moisture_projection
REMEDIAL_HOURS = 4
CRACK_RISK_MOISTURE = Decimal("32.0")

CURVE_STAGES = {
    "STANDARD": [(6, Decimal("0.30")), (8, Decimal("0.50")), (4, Decimal("0.20"))],
    "HIGH_TEMP": [(3, Decimal("0.50")), (4, Decimal("0.35")), (2, Decimal("0.15"))],
    "LOW_TEMP": [(9, Decimal("0.25")), (18, Decimal("0.45")), (9, Decimal("0.30"))],
}
CURVE_TOTAL_HOURS = {name: sum(h for h, _ in stages) for name, stages in CURVE_STAGES.items()}


def elapsed_hours(session, now, quantize=True):
    """Fractional hours from drying_started_at to now; 2dp when quantize."""
    seconds = (now - session["drying_started_at"]).total_seconds()
    hours = Decimal(str(seconds)) / Decimal("3600")
    if quantize:
        hours = hours.quantize(_2DP, rounding=ROUND_HALF_UP)
    return hours


def project_moisture(session, now):
    """Piecewise-linear stage projection; 2dp half-up; floored at target."""
    initial = dec(session["initial_moisture_pct"])
    target = dec(session["target_moisture_pct"])
    required = session["required_hours"]
    elapsed = elapsed_hours(session, now, quantize=True)
    if dec(elapsed) >= dec(required):
        return num_out(target.quantize(_2DP, rounding=ROUND_HALF_UP))

    stages = [(Decimal(h), f) for h, f in CURVE_STAGES[session["drying_curve"]]]
    d3 = stages[2][0] + Decimal(REMEDIAL_HOURS * session["redry_count"])
    stages[2] = (d3, stages[2][1])

    cum_removed = Decimal("0")
    cum_hours = Decimal("0")
    fraction = Decimal("1")
    for duration, frac in stages:
        stage_end = cum_hours + duration
        if elapsed < stage_end:
            fraction = cum_removed + frac * (elapsed - cum_hours) / duration
            break
        cum_removed += frac
        cum_hours = stage_end
    else:
        fraction = cum_removed

    projected = initial - (initial - target) * fraction
    if projected < target:
        projected = target
    return num_out(projected.quantize(_2DP, rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ case_plan
PARTIAL_CASE_MIN_UNITS = 6


def case_plan(actual_yield_kg, recipe, brand_type):
    """Pinned per-level floor/ceil before aggregation (PRD §3.7)."""
    unit_weight = dec(recipe["unit_weight_g"])
    total_units = int((dec(actual_yield_kg) * 1000 / unit_weight).to_integral_value(ROUND_FLOOR))
    cap_units = int((dec(recipe["case_weight_limit_kg"]) * 1000 / unit_weight
                     ).to_integral_value(ROUND_FLOOR))
    units_per_case = min(recipe["units_per_case"], cap_units)
    if units_per_case > 0:
        full_case_count = total_units // units_per_case
        remainder_units = total_units - full_case_count * units_per_case
    else:
        full_case_count = 0
        remainder_units = total_units
    partial_case_count = (1 if brand_type == "BRANDED"
                          and remainder_units >= PARTIAL_CASE_MIN_UNITS else 0)
    scrapped_units = remainder_units if partial_case_count == 0 else 0
    case_count = full_case_count + partial_case_count
    per_pallet = dec(recipe["cases_per_pallet"])
    pallet_count = int((dec(case_count) / per_pallet).to_integral_value(ROUND_CEILING)) \
        if case_count > 0 else 0
    unit_count = full_case_count * units_per_case + (remainder_units if partial_case_count else 0)
    return {
        "total_units": total_units,
        "units_per_case": units_per_case,
        "full_case_count": full_case_count,
        "partial_case_count": partial_case_count,
        "scrapped_units": scrapped_units,
        "case_count": case_count,
        "pallet_count": pallet_count,
        "unit_count": unit_count,
    }
