"""Per-entity shape checkers and domain invariant helpers."""

import math
from datetime import datetime
from typing import Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    APPROVED_MIN,
    CENT,
    CHANGEOVER_MINUTES,
    ENERGY_WEIGHT,
    FATIGUE_T1,
    FATIGUE_T1_MAX,
    FATIGUE_T2,
    FATIGUE_T2_MAX,
    FATIGUE_T3,
    LOAD_WINDOW_SLOTS,
    MAX_POINTS_PER_SLOT,
    PRESENTATION_WINDOW_UNITS,
    PROBATION_MIN,
    RATE_BASE_UNITS,
    SCORE_CAP,
    SCORE_FLOOR,
    SHIFT_MINUTES,
    TIER_A_MAX,
    TIER_A_PLUS_MAX,
    TIER_B_MAX,
    WATER_WEIGHT,
)
from .types import (
    AssemblyStatus,
    BomLineStatus,
    BuildSlotStatus,
    CertificationTier,
    DeliveryCallStatus,
    LineOperatingMode,
    LinePosture,
    ModelVariantStatus,
    PartLifecycleStatus,
    QualityStatus,
    ShiftPlanStatus,
    SupplierStatus,
)


# =============================================================================
# Generic building blocks
# =============================================================================
def assert_identity(entity: dict) -> None:
    """Every entity carries a bare UUID `id` and an ISO 8601 UTC `created_at`."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be ISO 8601: {entity['created_at']!r}"
    )


def assert_versioned(entity: dict) -> None:
    """Entities other than a quality test also carry `updated_at` and `version`."""
    assert_identity(entity)
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at must be ISO 8601: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"version must be a positive integer: {entity.get('version')!r}"
    )


def assert_two_dp(value: float, label: str = "value") -> None:
    """A quantity carried at two decimal places, as a JSON number."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {type(value).__name__}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{label} must carry at most two decimals: {value!r}"
    )


def assert_number(value, label: str = "value") -> None:
    """Numbers are JSON numbers, never strings."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {type(value).__name__}: {value!r}"
    )


def approx2(expected: float):
    """Comparison helper for two-decimal quantities."""
    return pytest.approx(expected, abs=CENT / 2)


def same_instant(actual: Optional[str], expected: str) -> bool:
    """True when two ISO 8601 UTC renderings denote the same instant.

    Timestamps may legitimately be rendered with or without fractional digits,
    so instants are compared as instants rather than as strings.
    """
    if actual is None:
        return False

    def parse(text: str):
        return datetime.fromisoformat(text.replace("Z", "+00:00"))

    return parse(actual) == parse(expected)


# =============================================================================
# Per-entity shape checkers
# =============================================================================
def assert_line(line: dict) -> dict:
    assert_versioned(line)
    assert isinstance(line["line_code"], str) and line["line_code"]
    assert line["takt_seconds"] >= 1
    assert 0 < float(line["option_load_limit_pct"]) <= 100
    assert line["baseline_headcount"] >= 1
    assert line["operating_mode"] in {m.value for m in LineOperatingMode}
    assert line["posture"] in {p.value for p in LinePosture}
    assert line["changeover_count"] >= 0
    assert line["checkpoint_index"] >= 0
    assert line["max_released_sequence_index"] >= 0
    assert line["presentation_slots_total"] >= 0
    assert line["presentation_slots_committed"] >= 0
    assert_two_dp(line["free_slot_pct"], "free_slot_pct")
    return line


def assert_station(station: dict) -> dict:
    assert_versioned(station)
    assert is_valid_uuid(station["line_id"])
    assert station["position_index"] >= 1
    assert station["presentation_slot_capacity"] >= 0
    assert station["station_cycle_seconds"] >= 1
    assert station["presentation_slots_used"] >= 0
    return station


def assert_model_variant(variant: dict) -> dict:
    assert_versioned(variant)
    assert variant["status"] in {s.value for s in ModelVariantStatus}
    assert isinstance(variant["option_codes"], list)
    assert 0 <= variant["option_content_points"] <= MAX_POINTS_PER_SLOT
    assert variant["labor_minutes"] >= 0
    assert isinstance(variant["requires_leak_test"], bool)
    return variant


def assert_supplier(supplier: dict) -> dict:
    assert_versioned(supplier)
    assert supplier["status"] in {s.value for s in SupplierStatus}
    assert_two_dp(supplier["on_time_score"], "on_time_score")
    assert SCORE_FLOOR <= float(supplier["on_time_score"]) <= SCORE_CAP
    for counter in (
        "delivered_on_time_count",
        "delivered_late_count",
        "missed_count",
        "quality_penalty_count",
    ):
        assert supplier[counter] >= 0, f"{counter} must not go negative"
    assert_supplier_band(supplier)
    return supplier


def assert_part(part: dict) -> dict:
    assert_versioned(part)
    assert part["lifecycle_status"] in {s.value for s in PartLifecycleStatus}
    assert part["line_side_max_units"] >= 1
    assert part["field_failure_count"] >= 0
    assert_two_dp(part["cohort_failure_rate_per_1000"], "cohort_failure_rate_per_1000")
    return part


def assert_bom_line(bom_line: dict) -> dict:
    assert_versioned(bom_line)
    assert bom_line["status"] in {s.value for s in BomLineStatus}
    assert bom_line["qty_per_unit"] >= 1
    assert bom_line["effective_from_sequence"] >= 1
    if bom_line["status"] == BomLineStatus.ACTIVE.value:
        assert bom_line["superseded_by_bom_line_id"] is None, (
            "an ACTIVE bom line must not point at a successor"
        )
    return bom_line


def assert_delivery_call(call: dict) -> dict:
    assert_versioned(call)
    assert call["status"] in {s.value for s in DeliveryCallStatus}
    assert call["sequenced_qty"] >= 1
    assert call["window_start"] < call["window_end"], (
        "window_end must be strictly after window_start"
    )
    return call


def assert_shift_plan(plan: dict) -> dict:
    assert_versioned(plan)
    assert plan["status"] in {s.value for s in ShiftPlanStatus}
    assert 0 <= plan["overtime_minutes"] <= 120
    assert plan["available_labor_minutes"] == SHIFT_MINUTES + plan["overtime_minutes"]
    assert plan["shift_start"] < plan["shift_end"]
    assert plan["unit_labor_minutes"] >= 0
    assert plan["changeover_minutes"] >= 0
    assert plan["committed_labor_minutes"] >= 0
    return plan


def assert_build_slot(slot: dict) -> dict:
    assert_versioned(slot)
    assert slot["status"] in {s.value for s in BuildSlotStatus}
    assert slot["sequence_index"] >= 1
    assert isinstance(slot["presentation_allocations"], list)
    assert slot["allocated_slot_units"] >= 0
    total = sum(a["slot_units"] for a in slot["presentation_allocations"])
    assert total == slot["allocated_slot_units"], (
        "allocated_slot_units must equal the sum of the pinned allocations"
    )
    return slot


def assert_production_unit(unit: dict) -> dict:
    assert_versioned(unit)
    assert unit["assembly_status"] in {s.value for s in AssemblyStatus}
    assert unit["quality_status"] in {s.value for s in QualityStatus}
    assert unit["rework_count"] >= 0
    assert unit["built_at_sequence_index"] >= 1
    if unit["certification_tier"] is not None:
        assert unit["certification_tier"] in {t.value for t in CertificationTier}
    return unit


def assert_quality_test(test: dict) -> dict:
    """A quality test is immutable: it carries no `updated_at` and no `version`."""
    assert_identity(test)
    assert "updated_at" not in test, "a quality test must not carry updated_at"
    assert "version" not in test, "a quality test must not carry version"
    assert_number(test["measured_value"], "measured_value")
    assert float(test["measured_value"]) >= 0, "measured_value must be non-negative"
    return test


def assert_engineering_change(change: dict) -> dict:
    assert_versioned(change)
    assert change["cut_in_sequence_index"] >= 1
    assert change["revision_round"] >= 0
    return change


def assert_warranty_return(wr: dict) -> dict:
    assert_versioned(wr)
    assert_number(wr["field_hours"], "field_hours")
    assert float(wr["field_hours"]) >= 0, "field_hours must be non-negative"
    assert is_iso8601_timestamp(wr["returned_at"])
    return wr


# =============================================================================
# Domain invariants
# =============================================================================
def assert_no_mutation(before: dict, after: dict) -> None:
    """A rejected request writes nothing: the entity is byte-identical."""
    assert before == after, (
        "a rejected request must leave the entity untouched\n"
        f"before={before}\nafter={after}"
    )


def assert_pristine_slot(slot: dict) -> None:
    """A slot that has never been sequenced consumes nothing."""
    assert slot["status"] == BuildSlotStatus.PLANNED.value
    assert slot["shift_plan_id"] is None
    assert slot["sync_delivery_call_id"] is None
    assert slot["option_points_snapshot"] is None
    assert slot["labor_minutes_snapshot"] is None
    assert slot["presentation_allocations"] == []
    assert slot["allocated_slot_units"] == 0


def assert_slot_charges(slot: dict, station_id: str, slot_units: int,
                        labor_minutes: int, option_points: int) -> None:
    """A sequenced slot pins exactly the amounts it charged."""
    assert slot["status"] == BuildSlotStatus.SEQUENCED.value
    assert slot["allocated_slot_units"] == slot_units
    assert slot["labor_minutes_snapshot"] == labor_minutes
    assert slot["option_points_snapshot"] == option_points
    charged = {a["station_id"]: a["slot_units"] for a in slot["presentation_allocations"]}
    if slot_units:
        assert charged.get(station_id) == slot_units, (
            f"expected {slot_units} units charged at {station_id}, got {charged}"
        )


def expected_free_slot_pct(total: int, committed: int) -> float:
    """free_slot_pct is 0.00 whenever the line has no presentation slots at all."""
    if total == 0:
        return 0.00
    return round_half_up(100 * (total - committed) / total, 2)


def assert_line_ledger(line: dict, total: int, committed: int,
                       posture: Optional[str] = None) -> None:
    """The line's slot ledger and the posture derived from it."""
    assert line["presentation_slots_total"] == total
    assert line["presentation_slots_committed"] == committed
    assert float(line["free_slot_pct"]) == approx2(
        expected_free_slot_pct(total, committed)
    )
    if posture is not None:
        assert line["posture"] == posture


def assert_supplier_band(supplier: dict) -> None:
    """The status band is looked up from the clamped score."""
    score = float(supplier["on_time_score"])
    if score >= APPROVED_MIN:
        expected = SupplierStatus.APPROVED.value
    elif score >= PROBATION_MIN:
        expected = SupplierStatus.PROBATION.value
    else:
        expected = SupplierStatus.SUSPENDED.value
    assert supplier["status"] == expected, (
        f"score {score} implies {expected}, got {supplier['status']}"
    )


def assert_certification_tier(index: float, tier: Optional[str]) -> None:
    """The tier bands are read off the two-decimal index."""
    if index <= TIER_A_PLUS_MAX:
        expected = CertificationTier.A_PLUS.value
    elif index <= TIER_A_MAX:
        expected = CertificationTier.A.value
    elif index <= TIER_B_MAX:
        expected = CertificationTier.B.value
    else:
        expected = None
    assert tier == expected, f"index {index} implies tier {expected}, got {tier}"


def assert_serial_number(unit: dict, line_code: str) -> None:
    """The serial is the line code, a hyphen and the six-digit sequence index."""
    expected = f"{line_code}-{unit['built_at_sequence_index']:06d}"
    assert unit["serial_number"] == expected, (
        f"expected serial {expected}, got {unit['serial_number']}"
    )


def assert_fresh_unit(unit: dict) -> None:
    """A newly minted unit's two dimensions and its three efficiency figures."""
    assert unit["assembly_status"] == AssemblyStatus.IN_STATION.value
    assert unit["quality_status"] == QualityStatus.PENDING.value
    assert unit["rework_count"] == 0
    assert unit["provisional_efficiency_index"] is None
    assert unit["efficiency_index"] is None
    assert unit["certification_tier"] is None


# =============================================================================
# Arithmetic mirrors of the PRD's pinned step orders
# =============================================================================
def round_half_up(value: float, digits: int) -> float:
    """Half-up rounding at `digits` decimal places."""
    factor = 10 ** digits
    scaled = float(value) * factor
    # Nudge away from binary representation error before the half-up decision.
    return math.floor(scaled + 0.5 + 1e-9) / factor


def option_load_cap(option_load_limit_pct: float, planned_headcount: int,
                    baseline_headcount: int) -> int:
    """One floor applied once to the whole product of the four factors."""
    staffing = round_half_up(min(1.0, planned_headcount / baseline_headcount), 4)
    product = (
        LOAD_WINDOW_SLOTS
        * (option_load_limit_pct / 100)
        * MAX_POINTS_PER_SLOT
        * staffing
    )
    return math.floor(product + 1e-9)


def fatigue_multiplier(gross_minutes: int) -> float:
    """The tier is chosen on the gross figure, changeover minutes included."""
    if gross_minutes <= FATIGUE_T1_MAX:
        return FATIGUE_T1
    if gross_minutes <= FATIGUE_T2_MAX:
        return FATIGUE_T2
    return FATIGUE_T3


def committed_labor_minutes(unit_minutes: int, changeover_minutes: int) -> int:
    """Gross, then the fatigue multiplier, then a single ceiling at the very end."""
    gross = unit_minutes + changeover_minutes
    return math.ceil(gross * fatigue_multiplier(gross) - 1e-9)


def presentation_slot_units(qty_per_unit: int, line_side_max_units: int) -> int:
    """Ceiling applied to the whole quotient."""
    return math.ceil(
        (qty_per_unit * PRESENTATION_WINDOW_UNITS) / line_side_max_units - 1e-9
    )


def efficiency_index(energy_ratios: list, water_ratios: list) -> float:
    """Each ratio to 2 dp, per-type mean to 4 dp, weighted sum to 2 dp."""
    energy_mean = round_half_up(
        sum(round_half_up(r, 2) for r in energy_ratios) / len(energy_ratios), 4
    )
    water_mean = round_half_up(
        sum(round_half_up(r, 2) for r in water_ratios) / len(water_ratios), 4
    )
    return round_half_up(ENERGY_WEIGHT * energy_mean + WATER_WEIGHT * water_mean, 2)


def cohort_failure_rate(failures: int, cohort_units: int) -> float:
    """Zero denominator yields 0.00."""
    if cohort_units == 0:
        return 0.00
    return round_half_up(RATE_BASE_UNITS * failures / cohort_units, 2)


def changeover_minutes_for(boundaries: int) -> int:
    return boundaries * CHANGEOVER_MINUTES
