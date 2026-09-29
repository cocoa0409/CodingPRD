"""
Reference arithmetic and shape assertions.

Every rounding discipline of PRD 2.6 is implemented once here — half-up to a
named decimal count, ceiling to the next whole cent, and flooring to a whole
cent — so a test can state an expected figure either as a literal or as the
formula the PRD gives and have the two agree. The engineering, capability,
quoting and amortization rules are then transcribed in the order the PRD pins,
because several of them are order-sensitive: the stress split is taken from
unrounded stresses, the wire reservation starts from the design's *stored*
six-decimal mass, and the quote's discount tier is keyed on a subtotal computed
before any discount while its amortization cap is keyed on the price after it.
"""

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Dict, Sequence, Tuple

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C
from .types import Json

PI = 3.141592653589793


# ── The rounding disciplines (PRD 2.6) ───────────────────────────────────────
def round_half_up(value: float, places: int) -> float:
    """Round half up to `places` decimals: a midpoint rounds away from zero."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_half_up_cents(value: float) -> int:
    """Collapse a mills figure onto a whole cent, half up."""
    return int(Decimal(repr(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_cents(value: float) -> int:
    """Round toward positive infinity to the next whole cent."""
    exact = Decimal(repr(value)).quantize(Decimal("1.000000000"), rounding=ROUND_HALF_UP)
    return int(exact.to_integral_value(rounding=ROUND_CEILING))


def floor_cents(value: float) -> int:
    """Round toward negative infinity to a whole cent."""
    exact = Decimal(repr(value)).quantize(Decimal("1.000000000"), rounding=ROUND_HALF_UP)
    return int(exact.to_integral_value(rounding=ROUND_FLOOR))


# ── Geometry and the engineering stack (PRD 3.2) ──────────────────────────────
def mean_coil_diameter_mm(outer_diameter_mm: float, wire_diameter_mm: float) -> float:
    """The mean coil diameter: outer diameter less one wire diameter."""
    return outer_diameter_mm - wire_diameter_mm


def spring_index(outer_diameter_mm: float, wire_diameter_mm: float) -> float:
    return mean_coil_diameter_mm(outer_diameter_mm, wire_diameter_mm) / wire_diameter_mm


def wahl_factor(outer_diameter_mm: float, wire_diameter_mm: float) -> float:
    """Four times the index plus two, over four times the index minus three."""
    index = spring_index(outer_diameter_mm, wire_diameter_mm)
    return (4 * index + 2) / (4 * index - 3)


def expected_spring_rate(
    shear_modulus_gpa: float,
    wire_diameter_mm: float,
    outer_diameter_mm: float,
    active_coils: float,
) -> float:
    """Spring rate in N/mm, half up to three decimals."""
    shear_modulus_mpa = shear_modulus_gpa * 1000
    mean_d = mean_coil_diameter_mm(outer_diameter_mm, wire_diameter_mm)
    raw = (shear_modulus_mpa * wire_diameter_mm ** 4) / (8 * mean_d ** 3 * active_coils)
    return round_half_up(raw, 3)


def raw_shear_stress(
    load_n: float, wire_diameter_mm: float, outer_diameter_mm: float
) -> float:
    """The corrected shear stress at one load, held at machine precision."""
    mean_d = mean_coil_diameter_mm(outer_diameter_mm, wire_diameter_mm)
    factor = wahl_factor(outer_diameter_mm, wire_diameter_mm)
    return factor * 8 * load_n * mean_d / (PI * wire_diameter_mm ** 3)


def expected_shear_stress(
    load_n: float, wire_diameter_mm: float, outer_diameter_mm: float
) -> float:
    """One of the two persisted stress fields, half up to two decimals."""
    return round_half_up(raw_shear_stress(load_n, wire_diameter_mm, outer_diameter_mm), 2)


def raw_stress_split(
    wire_diameter_mm: float,
    outer_diameter_mm: float,
    max_working_load_n: float,
    min_working_load_n: float,
) -> Tuple[float, float]:
    """The unrounded (amplitude, mean) pair the fatigue rule consumes."""
    high = raw_shear_stress(max_working_load_n, wire_diameter_mm, outer_diameter_mm)
    low = raw_shear_stress(min_working_load_n, wire_diameter_mm, outer_diameter_mm)
    return (high - low) / 2, (high + low) / 2


def expected_stress_amplitude(
    wire_diameter_mm: float,
    outer_diameter_mm: float,
    max_working_load_n: float,
    min_working_load_n: float,
) -> float:
    amplitude, _ = raw_stress_split(
        wire_diameter_mm, outer_diameter_mm, max_working_load_n, min_working_load_n
    )
    return round_half_up(amplitude, 2)


def expected_mean_stress(
    wire_diameter_mm: float,
    outer_diameter_mm: float,
    max_working_load_n: float,
    min_working_load_n: float,
) -> float:
    _, mean = raw_stress_split(
        wire_diameter_mm, outer_diameter_mm, max_working_load_n, min_working_load_n
    )
    return round_half_up(mean, 2)


def endurance_limit_mpa(tensile_grade_mpa: float, shot_peening_required: bool) -> float:
    """The shear endurance limit after the shot-peening factor."""
    factor = C.SSE_PEENED_FACTOR if shot_peening_required else C.SSE_UNPEENED_FACTOR
    return tensile_grade_mpa * factor


def ultimate_shear_strength_mpa(tensile_grade_mpa: float) -> float:
    return tensile_grade_mpa * C.SSU_FACTOR


def shear_yield_strength_mpa(tensile_grade_mpa: float) -> float:
    return tensile_grade_mpa * C.SSY_FACTOR


def expected_fatigue_criterion(application_class: str) -> str:
    """SODERBERG for the two safety-critical classes, GOODMAN for the rest."""
    if application_class in (C.CLASS_AUTOMOTIVE_SAFETY, C.CLASS_MEDICAL_IMPLANT):
        return C.CRITERION_SODERBERG
    return C.CRITERION_GOODMAN


def expected_fatigue_margins(
    wire_diameter_mm: float,
    outer_diameter_mm: float,
    max_working_load_n: float,
    min_working_load_n: float,
    tensile_grade_mpa: float,
    shot_peening_required: bool,
) -> Dict[str, float]:
    """Both variants, each half up to three decimals, keyed by criterion name."""
    amplitude, mean = raw_stress_split(
        wire_diameter_mm, outer_diameter_mm, max_working_load_n, min_working_load_n
    )
    sse = endurance_limit_mpa(tensile_grade_mpa, shot_peening_required)
    goodman_denominator = amplitude / sse + mean / ultimate_shear_strength_mpa(
        tensile_grade_mpa
    )
    soderberg_denominator = amplitude / sse + mean / shear_yield_strength_mpa(
        tensile_grade_mpa
    )
    return {
        C.CRITERION_GOODMAN: round_half_up(1 / goodman_denominator, 3),
        C.CRITERION_SODERBERG: round_half_up(1 / soderberg_denominator, 3),
    }


def expected_fatigue_margin(
    application_class: str,
    wire_diameter_mm: float,
    outer_diameter_mm: float,
    max_working_load_n: float,
    min_working_load_n: float,
    tensile_grade_mpa: float,
    shot_peening_required: bool,
) -> float:
    """The margin the design persists: the variant the class selects."""
    margins = expected_fatigue_margins(
        wire_diameter_mm,
        outer_diameter_mm,
        max_working_load_n,
        min_working_load_n,
        tensile_grade_mpa,
        shot_peening_required,
    )
    return margins[expected_fatigue_criterion(application_class)]


def expected_life_tier(fatigue_margin_ratio: float) -> int:
    """The integer cycle tier, each comparison inclusive at its lower bound."""
    for breakpoint, cycles in zip(C.LIFE_TIER_BREAKPOINTS, C.LIFE_TIER_CYCLES):
        if fatigue_margin_ratio >= breakpoint:
            return cycles
    return C.LIFE_TIER_CYCLES[-1]


def developed_length_mm(
    wire_diameter_mm: float,
    outer_diameter_mm: float,
    active_coils: float,
    end_type: str,
) -> float:
    """Coil length plus twice the tail allowance of the declared end type."""
    mean_d = mean_coil_diameter_mm(outer_diameter_mm, wire_diameter_mm)
    coil = PI * mean_d * (active_coils + C.END_COIL_ALLOWANCE_COILS)
    return coil + 2 * C.TAIL_LENGTH_MM[end_type]


def expected_wire_mass_per_piece_kg(
    wire_diameter_mm: float,
    outer_diameter_mm: float,
    active_coils: float,
    end_type: str,
    density_kg_per_m3: float,
) -> float:
    """The per-piece mass, half up to exactly six decimals."""
    length = developed_length_mm(
        wire_diameter_mm, outer_diameter_mm, active_coils, end_type
    )
    area_m2 = PI * (wire_diameter_mm / 2000) ** 2
    return round_half_up((length / 1000) * area_m2 * density_kg_per_m3, 6)


def expected_tangle_risk_index(free_length_mm: float, outer_diameter_mm: float) -> float:
    return round_half_up(free_length_mm / outer_diameter_mm, 3)


def expected_tangle_risk_class(
    free_length_mm: float, outer_diameter_mm: float, end_type: str
) -> str:
    index = expected_tangle_risk_index(free_length_mm, outer_diameter_mm)
    if index >= C.TANGLE_HIGH_INDEX or end_type == C.END_HOOK_EXTENSION:
        return C.TANGLE_HIGH
    return C.TANGLE_LOW


# ── The wire ledger (PRD 3.7) ────────────────────────────────────────────────
def expected_wire_reserved_kg(stored_mass_per_piece_kg: float, planned_pieces: int) -> float:
    """Stored mass, times planned pieces, inflated 3 %, rounded once at the end."""
    return round_half_up(
        stored_mass_per_piece_kg * planned_pieces * (1 + C.SCRAP_ALLOWANCE_PCT), 3
    )


def expected_wire_consumed_kg(
    stored_mass_per_piece_kg: float, produced_pieces: int, scrapped_pieces: int
) -> float:
    """Scrap burns wire exactly like good product does."""
    return round_half_up(
        stored_mass_per_piece_kg * (produced_pieces + scrapped_pieces), 3
    )


def assert_wire_ledger_conserved(lot: Json) -> None:
    """`received_kg` is always the sum of the three buckets (PRD 2.9)."""
    total = round_half_up(
        lot["on_hand_kg"] + lot["reserved_kg"] + lot["consumed_kg"], 3
    )
    assert total == round_half_up(lot["received_kg"], 3), (
        "wire mass is conserved: on_hand + reserved + consumed must equal received, "
        f"got {lot['on_hand_kg']} + {lot['reserved_kg']} + {lot['consumed_kg']} "
        f"= {total} against received {lot['received_kg']}"
    )


def assert_tooling_ledger_conserved(tool: Json) -> None:
    """`recovered_cents` and `unamortized_cents` always sum to the cost."""
    assert tool["recovered_cents"] + tool["unamortized_cents"] == tool[
        "original_cost_cents"
    ], (
        "tooling cost is conserved: recovered + unamortized must equal "
        f"original_cost_cents, got {tool['recovered_cents']} + "
        f"{tool['unamortized_cents']} against {tool['original_cost_cents']}"
    )


def assert_commitment_conserved(program: Json) -> None:
    """Open, allocated and shipped pieces always sum to the commitment."""
    total = (
        program["open_commitment_pieces"]
        + program["allocated_pieces"]
        + program["shipped_pieces"]
    )
    assert total == program["committed_pieces"], (
        "piece commitment is conserved: open + allocated + shipped must equal "
        f"committed_pieces, got {total} against {program['committed_pieces']}"
    )


# ── Capability statistics (PRD 3.7) ──────────────────────────────────────────
def raw_mean(measurements: Sequence[float]) -> float:
    return sum(measurements) / len(measurements)


def raw_sigma(measurements: Sequence[float]) -> float:
    """The Bessel-corrected sample standard deviation, unrounded."""
    mean = raw_mean(measurements)
    squares = sum((value - mean) ** 2 for value in measurements)
    return math.sqrt(squares / (len(measurements) - 1))


def expected_mean_value(measurements: Sequence[float]) -> float:
    return round_half_up(raw_mean(measurements), 4)


def expected_sigma_value(measurements: Sequence[float]) -> float:
    return round_half_up(raw_sigma(measurements), 6)


def expected_capability_index(
    measurements: Sequence[float], lsl: float, usl: float
) -> float:
    """The smaller of the two specification distances over three sigma."""
    mean = raw_mean(measurements)
    sigma = raw_sigma(measurements)
    binding = min(usl - mean, mean - lsl)
    return round_half_up(binding / (3 * sigma), 3)


def expected_cpk_value(measurements: Sequence[float], lsl: float, usl: float) -> float:
    return expected_capability_index(measurements, lsl, usl)


def expected_ppk_value(
    pooled_measurements: Sequence[float], lsl: float, usl: float
) -> float:
    """The same index over every SPC measurement of the run and characteristic."""
    return expected_capability_index(pooled_measurements, lsl, usl)


def expected_control_state(
    measurements: Sequence[float], lsl: float, usl: float, cpk_floor: float
) -> str:
    """OUT_OF_CONTROL on a sub-floor rounded index or any out-of-spec reading."""
    cpk = expected_cpk_value(measurements, lsl, usl)
    if cpk < cpk_floor:
        return C.CONTROL_OUT_OF_CONTROL
    if any(value > usl or value < lsl for value in measurements):
        return C.CONTROL_OUT_OF_CONTROL
    return C.CONTROL_IN_CONTROL


# ── Quoting (PRD 3.11) ───────────────────────────────────────────────────────
def expected_volume_discount_pct(pre_discount_subtotal_cents: int) -> float:
    """Strict below each breakpoint, inclusive at the top tier."""
    if pre_discount_subtotal_cents < C.VOLUME_TIER_BREAKPOINTS_CENTS[0]:
        return C.VOLUME_TIER_DISCOUNTS[0]
    if pre_discount_subtotal_cents < C.VOLUME_TIER_BREAKPOINTS_CENTS[1]:
        return C.VOLUME_TIER_DISCOUNTS[1]
    if pre_discount_subtotal_cents < C.VOLUME_TIER_BREAKPOINTS_CENTS[2]:
        return C.VOLUME_TIER_DISCOUNTS[2]
    return C.VOLUME_TIER_DISCOUNTS[3]


def expected_quote(
    wire_mass_per_piece_kg: float,
    cost_per_kg_cents: int,
    cycle_seconds_per_piece: float,
    quoted_qty: int,
    tooling_unamortized_cents: int,
) -> Dict[str, float]:
    """The eleven quoting steps, run in the order PRD 3.11 pins them."""
    material_per_piece = round_half_up(wire_mass_per_piece_kg * cost_per_kg_cents, 4)
    labour_per_piece = round_half_up(
        cycle_seconds_per_piece / 3600 * C.LABOR_RATE_CENTS_PER_HOUR, 4
    )
    base_unit_cost = round_half_up(material_per_piece + labour_per_piece, 4)
    pre_discount_subtotal = round_half_up_cents(base_unit_cost * quoted_qty)
    discount_pct = expected_volume_discount_pct(pre_discount_subtotal)
    discounted_unit_cost = round_half_up(base_unit_cost * (1 - discount_pct), 4)
    raw_amort_ask = ceil_cents(tooling_unamortized_cents / quoted_qty)
    amort_cap = floor_cents(C.TOOLING_AMORT_CAP_PCT * discounted_unit_cost)
    amort_per_piece = min(raw_amort_ask, amort_cap)
    unit_price = round_half_up_cents(discounted_unit_cost + amort_per_piece)
    total = unit_price * quoted_qty + C.SETUP_FEE_CENTS
    return {
        "material_content_cents": material_per_piece,
        "labour_content_cents": labour_per_piece,
        "base_unit_cost_cents": base_unit_cost,
        "quoted_pre_discount_subtotal_cents": pre_discount_subtotal,
        "quoted_volume_discount_pct": discount_pct,
        "discounted_unit_cost_cents": discounted_unit_cost,
        "raw_amortization_ask_cents": raw_amort_ask,
        "amortization_cap_cents": amort_cap,
        "quoted_tooling_amort_per_piece_cents": amort_per_piece,
        "quoted_unit_price_cents": unit_price,
        "quoted_total_cents": total,
    }


# ── Amortization (PRD 3.4) ───────────────────────────────────────────────────
def expected_amort_per_piece_cents(original_cost_cents: int, basis_pieces: int) -> int:
    """Cost over the frozen basis, rounded up to the next whole cent."""
    return ceil_cents(original_cost_cents / basis_pieces)


def expected_forecast_recovery_cents(
    piece_count: int, amort_per_piece_cents: int, unamortized_cents: int
) -> int:
    """Straight-line: pieces times the frozen rate, capped at the balance."""
    return min(piece_count * amort_per_piece_cents, unamortized_cents)


def expected_actual_recovery_cents(
    unamortized_cents: int, piece_count: int, open_commitment_pieces: int
) -> int:
    """Accelerated declining: 1.5x the pro-rata share of the remaining balance."""
    divisor = open_commitment_pieces if open_commitment_pieces > 0 else 1
    raw = unamortized_cents * C.ACCELERATION_FACTOR * piece_count / divisor
    return min(ceil_cents(raw), unamortized_cents)


# ── Delivery posture (PRD 3.1) ───────────────────────────────────────────────
def expected_delivery_posture(
    has_granted_submission: bool, quarantined_lot_count: int, has_held_run: bool
) -> str:
    """The three-input posture rule, re-derived rather than patched."""
    if not has_granted_submission:
        return C.POSTURE_BLOCKED
    if quarantined_lot_count >= 1 or has_held_run:
        return C.POSTURE_AT_RISK
    return C.POSTURE_ON_TRACK


# ── Shape assertions (PRD 2.4) ───────────────────────────────────────────────
def assert_audited_resource(resource: Json) -> None:
    """A full-audit resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id must be a UUID, got {resource['id']!r}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at must be ISO 8601 UTC, got {resource['created_at']!r}"
    assert is_iso8601_timestamp(
        resource["updated_at"]
    ), f"updated_at must be ISO 8601 UTC, got {resource['updated_at']!r}"
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1 on creation"


def assert_write_once_resource(resource: Json) -> None:
    """A write-once resource carries id and created_at and nothing more."""
    assert is_valid_uuid(resource["id"]), f"id must be a UUID, got {resource['id']!r}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at must be ISO 8601 UTC, got {resource['created_at']!r}"
    assert "updated_at" not in resource, (
        "a write-once resource omits updated_at entirely, "
        f"but it carried {resource.get('updated_at')!r}"
    )
    assert "version" not in resource, (
        "a write-once resource omits version entirely, "
        f"but it carried {resource.get('version')!r}"
    )


def assert_decimal_places(value: float, places: int, label: str = "value") -> None:
    """The stored figure is carried to exactly the decimal count its rule names."""
    assert value == round_half_up(value, places), (
        f"{label} must be carried to {places} decimal places, got {value!r}"
    )


def decimal_places_of(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return Decimal(text).as_tuple().exponent * -1
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0
