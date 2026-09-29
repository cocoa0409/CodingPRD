"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §2.10, §3.4-3.9).

All precision-sensitive arithmetic runs on decimal.Decimal; rounding modes are
taken verbatim from the specification (half-up unless stated otherwise).
"""

from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from db import db

# --------------------------------------------------------------------------- #
# constants (SCAFFOLD §1.3 / PRD prose)
# --------------------------------------------------------------------------- #
LOAD_WINDOW_SLOTS = 5
MAX_POINTS_PER_SLOT = 10

ENERGY_WEIGHT = Decimal("0.6")
WATER_WEIGHT = Decimal("0.4")
TIER_A_PLUS_MAX = Decimal("0.80")
TIER_A_MAX = Decimal("0.95")
TIER_B_MAX = Decimal("1.00")

SHIFT_MINUTES = 480
OVERTIME_CAP_MINUTES = 120
CHANGEOVER_MINUTES = Decimal("18")
FATIGUE_T1_MAX = Decimal("300")
FATIGUE_T2_MAX = Decimal("450")
FATIGUE_T1 = Decimal("1.00")
FATIGUE_T2 = Decimal("1.05")
FATIGUE_T3 = Decimal("1.12")

PRESENTATION_WINDOW_UNITS = Decimal("20")

SCORE_START = Decimal("100.00")
ON_TIME_BONUS = Decimal("2")
LATE_PENALTY = Decimal("8")
MISS_PENALTY = Decimal("20")
QUALITY_PENALTY = Decimal("10")
SCORE_CAP = Decimal("100.00")
SCORE_FLOOR = Decimal("0.00")
APPROVED_MIN = Decimal("60.00")
PROBATION_MIN = Decimal("40.00")

POSTURE_CONSTRAINED_PCT = Decimal("20.00")

RATE_BASE_UNITS = Decimal("1000")
EXPECTED_ANNUAL_HOURS = Decimal("2000")
WARRANTY_RATE_TRIGGER = Decimal("8.00")

MISS_GRACE_MINUTES = 15
DOCK_BUFFER_MINUTES = 10
SERVICE_OBLIGATION_YEARS = 10
EC_MAX_REVISION_ROUNDS = 3

LIVE_SLOT_STATUSES = ("PLANNED", "SEQUENCED", "RELEASED", "BUILT")
COMMITTED_SLOT_STATUSES = ("SEQUENCED", "RELEASED", "BUILT")
LIVE_CALL_STATUSES = ("SCHEDULED", "ARRIVED_ON_TIME", "ARRIVED_LATE")
LIVE_CHANGE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED")


# --------------------------------------------------------------------------- #
# numeric helpers
# --------------------------------------------------------------------------- #
def d(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def r2(value):
    return d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r4(value):
    return d(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(d(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(d(value).to_integral_value(rounding=ROUND_CEILING))


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def plus_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # 29 Feb -> 28 Feb
        return dt.replace(year=dt.year + years, day=28)


# --------------------------------------------------------------------------- #
# line derived state (calculations.line_posture)
# --------------------------------------------------------------------------- #
def line_stations(line_id):
    stations = [s for s in db.stations.values() if s["line_id"] == line_id]
    stations.sort(key=lambda s: (s["position_index"], s["created_at"], s["id"]))
    return stations


def line_slots(line_id):
    return [s for s in db.build_slots.values() if s["line_id"] == line_id]


def presentation_totals(line_id):
    stations = line_stations(line_id)
    total = sum(s["presentation_slot_capacity"] for s in stations)
    committed = sum(s["presentation_slots_used"] for s in stations)
    return total, committed


def free_slot_pct(line_id):
    total, committed = presentation_totals(line_id)
    if total == 0:
        return Decimal("0.00")
    return r2(Decimal(100) * Decimal(total - committed) / Decimal(total))


def line_posture(line):
    if line["operating_mode"] == "STOPPED":
        return "STOPPED"
    if free_slot_pct(line["id"]) < POSTURE_CONSTRAINED_PCT:
        return "CONSTRAINED"
    for station in line_stations(line["id"]):
        if station["presentation_slot_capacity"] > 0 and \
                station["presentation_slots_used"] == station["presentation_slot_capacity"]:
            return "CONSTRAINED"
    return "OPEN"


def max_released_sequence_index(line_id):
    indexes = [s["sequence_index"] for s in line_slots(line_id)
               if s["status"] in ("RELEASED", "BUILT")]
    return max(indexes) if indexes else 0


# --------------------------------------------------------------------------- #
# effective BOM (calculations.effective_bom_at_sequence)
# --------------------------------------------------------------------------- #
def resolve_bom(model_variant_id, sequence_index, include_superseded=False):
    """Return {bom_position_code: bom_line} governing the variant at an index."""
    allowed = ("ACTIVE", "SUPERSEDED") if include_superseded else ("ACTIVE",)
    winners = {}
    for line in db.bom_lines.values():
        if line["model_variant_id"] != model_variant_id:
            continue
        if line["status"] not in allowed:
            continue
        if line["effective_from_sequence"] > sequence_index:
            continue
        key = (line["effective_from_sequence"], line["created_at"], line["id"])
        current = winners.get(line["bom_position_code"])
        if current is None or key > (current["effective_from_sequence"], current["created_at"], current["id"]):
            winners[line["bom_position_code"]] = line
    return winners


def bom_allocation_order(bom_lines):
    """Ascending station position_index, then ascending bom_position_code."""
    def key(line):
        station = db.stations.get(line["station_id"])
        position = station["position_index"] if station else 10 ** 9
        return (position, line["bom_position_code"], line["id"])
    return sorted(bom_lines, key=key)


# --------------------------------------------------------------------------- #
# option-load window cap (calculations.option_load_window_cap)
# --------------------------------------------------------------------------- #
def option_load_cap(line, plan):
    staffing = min(Decimal(1), d(plan["planned_headcount"]) / d(line["baseline_headcount"]))
    staffing = r4(staffing)
    product = (d(LOAD_WINDOW_SLOTS)
               * (d(line["option_load_limit_pct"]) / Decimal(100))
               * d(MAX_POINTS_PER_SLOT)
               * staffing)
    return floor_int(product)


def option_load_windows_ok(line, plan, sequence_index, candidate_points):
    cap = option_load_cap(line, plan)
    committed = [s for s in line_slots(line["id"]) if s["status"] in COMMITTED_SLOT_STATUSES]
    for start in range(sequence_index - (LOAD_WINDOW_SLOTS - 1), sequence_index + 1):
        end = start + LOAD_WINDOW_SLOTS - 1
        points = 0
        for slot in committed:
            if start <= slot["sequence_index"] <= end:
                points += int(slot["option_points_snapshot"] or 0)
        points += int(candidate_points)
        if points > cap:
            return False
    return True


# --------------------------------------------------------------------------- #
# shift labour (calculations.shift_committed_labor_minutes)
# --------------------------------------------------------------------------- #
def fatigue_tier(gross):
    if gross <= FATIGUE_T1_MAX:
        return FATIGUE_T1
    if gross <= FATIGUE_T2_MAX:
        return FATIGUE_T2
    return FATIGUE_T3


def available_labor_minutes(plan):
    return d(SHIFT_MINUTES) + d(plan["overtime_minutes"])


def plan_figures(plan, extra=None):
    """(unit_labor_minutes, changeover_minutes, committed_labor_minutes).

    `extra` is an optional hypothetical slot (sequence_index, family_code,
    labor_minutes) used by the sequencing pre-check of ladder rule 31.
    """
    line = db.lines.get(plan["line_id"])
    entries = []
    for slot in db.build_slots.values():
        if slot["shift_plan_id"] != plan["id"]:
            continue
        if slot["status"] not in COMMITTED_SLOT_STATUSES:
            continue
        variant = db.model_variants.get(slot["model_variant_id"])
        entries.append((slot["sequence_index"],
                        variant["family_code"] if variant else None,
                        d(slot["labor_minutes_snapshot"])))
    if extra is not None:
        entries.append((extra[0], extra[1], d(extra[2])))
    entries.sort(key=lambda e: e[0])

    unit = sum((e[2] for e in entries), Decimal(0))
    boundaries = 0
    previous = line["current_family_code"] if line else None
    for _, family, _labor in entries:
        if family != previous:
            boundaries += 1
        previous = family
    changeover = CHANGEOVER_MINUTES * boundaries + d(plan.get("_booked_changeover_minutes", 0))
    gross = unit + changeover
    committed = ceil_int(gross * fatigue_tier(gross))
    return unit, changeover, committed


# --------------------------------------------------------------------------- #
# presentation slots (calculations.presentation_slot_allocation)
# --------------------------------------------------------------------------- #
def slot_units_for(bom_line, part, synchronously_covered):
    if part["is_sequenced_module"] and synchronously_covered:
        return 0
    return ceil_int(d(bom_line["qty_per_unit"]) * PRESENTATION_WINDOW_UNITS
                    / d(part["line_side_max_units"]))


# --------------------------------------------------------------------------- #
# supplier score (calculations.supplier_on_time_score)
# --------------------------------------------------------------------------- #
def supplier_score(supplier):
    score = (SCORE_START
             + ON_TIME_BONUS * d(supplier["delivered_on_time_count"])
             - LATE_PENALTY * d(supplier["delivered_late_count"])
             - MISS_PENALTY * d(supplier["missed_count"])
             - QUALITY_PENALTY * d(supplier["quality_penalty_count"]))
    if score > SCORE_CAP:
        score = SCORE_CAP
    if score < SCORE_FLOOR:
        score = SCORE_FLOOR
    return r2(score)


def supplier_status_for(score):
    if score >= APPROVED_MIN:
        return "APPROVED"
    if score >= PROBATION_MIN:
        return "PROBATION"
    return "SUSPENDED"


# --------------------------------------------------------------------------- #
# efficiency index (calculations.efficiency_index)
# --------------------------------------------------------------------------- #
def _recorded_tests(unit_id, test_type):
    tests = [t for t in db.quality_tests.values()
             if t["production_unit_id"] == unit_id
             and t["test_type"] == test_type
             and t["status"] == "RECORDED"]
    tests.sort(key=lambda t: (t["created_at"], t["id"]))
    return tests


def _type_mean(tests):
    ratios = []
    for test in tests:
        limit = test.get("limit_value")
        if limit in (None, 0):
            continue
        ratios.append(r2(d(test["measured_value"]) / d(limit)))
    if not ratios:
        return None
    total = sum(ratios, Decimal(0))
    return r4(total / Decimal(len(ratios)))


def efficiency_index(unit_id, variant):
    """variant: 'AS_TESTED' (latest test per type) or 'CERTIFICATION_AVERAGE'."""
    energy = _recorded_tests(unit_id, "ENERGY")
    water = _recorded_tests(unit_id, "WATER")
    if not energy or not water:
        return None
    if variant == "AS_TESTED":
        energy = [energy[-1]]
        water = [water[-1]]
    energy_mean = _type_mean(energy)
    water_mean = _type_mean(water)
    if energy_mean is None or water_mean is None:
        return None
    weighted = ENERGY_WEIGHT * energy_mean + WATER_WEIGHT * water_mean
    return r2(weighted)


def certification_tier(index):
    if index is None:
        return None
    if index <= TIER_A_PLUS_MAX:
        return "A_PLUS"
    if index <= TIER_A_MAX:
        return "A"
    if index <= TIER_B_MAX:
        return "B"
    return None


# --------------------------------------------------------------------------- #
# warranty failure rate (calculations.warranty_failure_rate)
# --------------------------------------------------------------------------- #
def warranty_metrics(part_id):
    returns = [w for w in db.warranty_returns.values()
               if w["root_cause_part_id"] == part_id
               and w["status"] in ("ANALYZED_DESIGN", "ANALYZED_SUPPLIER", "CLOSED")
               and w["disposition"] in ("DESIGN_DEFECT", "SUPPLIER_DEFECT")]
    failures = len(returns)
    total_field_hours = sum((d(w["field_hours"]) for w in returns), Decimal(0))

    cohort_units = 0
    for unit in db.production_units.values():
        if unit["assembly_status"] != "SHIPPED":
            continue
        slot = db.build_slots.get(unit["build_slot_id"])
        if slot is None:
            continue
        bom = resolve_bom(slot["model_variant_id"], unit["built_at_sequence_index"],
                          include_superseded=True)
        if any(line["part_id"] == part_id for line in bom.values()):
            cohort_units += 1

    if cohort_units > 0:
        cohort_rate = r2(RATE_BASE_UNITS * d(failures) / d(cohort_units))
    else:
        cohort_rate = Decimal("0.00")
    if total_field_hours > 0:
        exposure_rate = r2(RATE_BASE_UNITS * EXPECTED_ANNUAL_HOURS * d(failures) / total_field_hours)
    else:
        exposure_rate = Decimal("0.00")

    return {
        "failure_count": failures,
        "cohort_units": cohort_units,
        "total_field_hours": total_field_hours,
        "cohort_failure_rate_per_1000": cohort_rate,
        "shipped_exposure_rate_per_1000": exposure_rate,
    }


def lateness_minutes(arrived_at, window_end):
    if arrived_at < window_end:
        return 0
    seconds = (arrived_at - window_end).total_seconds()
    return ceil_int(d(seconds) / Decimal(60))


def minutes(count):
    return timedelta(minutes=count)
