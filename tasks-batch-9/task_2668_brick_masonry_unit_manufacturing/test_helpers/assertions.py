"""
Domain assertions and independent re-implementations of the PRD's arithmetic.

The helpers named expected_* recompute a derived value straight from the PRD
formula so a test can compare the API's answer against an independent one
instead of against a literal copied out of the API.

All money is whole cents and all rounding is half-up at the stated scale, per
the PRD's numeric precision discipline.
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import constants as C


# --- rounding ------------------------------------------------------------

def round_half_up(value: float, places: int = 2) -> float:
    """Round half-up at the given decimal scale, as the PRD requires."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def assert_decimal_places(value: float, places: int, label: str = "value") -> None:
    """Assert a number carries no more than `places` decimals."""
    assert value == round_half_up(value, places), (
        f"{label} {value!r} carries more than {places} decimal places"
    )


# --- audit columns -------------------------------------------------------

def assert_audit_columns(entity: Dict[str, Any], label: str = "resource") -> None:
    """Every resource carries a uuid id, two timestamps and an integer version."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{label}.id is not a uuid: {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"{label}.created_at is not an ISO 8601 UTC timestamp: {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at", "")), (
        f"{label}.updated_at is not an ISO 8601 UTC timestamp: {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), (
        f"{label}.version must be an integer, got {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, f"{label}.version must start at 1"


def assert_has_fields(entity: Dict[str, Any], fields: Iterable[str], label: str) -> None:
    """Assert every named field is present (a null value still counts)."""
    missing = [f for f in fields if f not in entity]
    assert not missing, f"{label} is missing declared fields: {missing}"


# --- conserved ledgers ---------------------------------------------------

def assert_clay_reserve_conserved(pit: Dict[str, Any]) -> None:
    """available_tons + committed_tons + consumed_tons equals proven_reserve_tons."""
    total = round_half_up(
        pit["available_tons"] + pit["committed_tons"] + pit["consumed_tons"], 2
    )
    assert total == round_half_up(pit["proven_reserve_tons"], 2), (
        "clay reserve not conserved for pit "
        f"{pit.get('pit_name')}: available {pit['available_tons']} + committed "
        f"{pit['committed_tons']} + consumed {pit['consumed_tons']} = {total}, "
        f"proven reserve {pit['proven_reserve_tons']}"
    )


def assert_fired_units_conserved(lot: Dict[str, Any]) -> None:
    """available_units + reserved_units + consumed_units equals fired_units."""
    total = lot["available_units"] + lot["reserved_units"] + lot["consumed_units"]
    assert total == lot["fired_units"], (
        f"fired unit ledger not conserved for lot {lot.get('lot_code')}: "
        f"available {lot['available_units']} + reserved {lot['reserved_units']} + "
        f"consumed {lot['consumed_units']} = {total}, fired {lot['fired_units']}"
    )


# --- body blend chemistry (PRD 3.2) -------------------------------------

def expected_blend_chemistry(components: List[Dict[str, float]]) -> Dict[str, float]:
    """
    Recompute a formulation's derived chemistry from its components.

    Each component is {"iron_oxide_pct", "lime_pct", "share_pct", "material_type"}.
    The weighted averages accumulate at full precision and round once, to three
    decimals; the shale share is an exact two-decimal sum.
    """
    iron = sum(c["iron_oxide_pct"] * c["share_pct"] for c in components) / 100
    lime = sum(c["lime_pct"] * c["share_pct"] for c in components) / 100
    shale = sum(c["share_pct"] for c in components if c["material_type"] == "SHALE")
    blend_iron = round_half_up(iron, 3)
    blend_lime = round_half_up(lime, 3)
    shale_share = round_half_up(shale, 2)
    raw = (
        C.ABSORPTION_BASE
        - C.IRON_ABSORPTION_COEFF * blend_iron
        - C.SHALE_ABSORPTION_COEFF * shale_share
        + C.LIME_ABSORPTION_COEFF * blend_lime
    )
    clamped = min(max(raw, C.ABSORPTION_MIN), C.ABSORPTION_MAX)
    absorption = round_half_up(clamped, 2)
    if absorption <= C.SW_MAX_ABSORPTION:
        grade = "SW"
    elif absorption <= C.MW_MAX_ABSORPTION:
        grade = "MW"
    else:
        grade = "NW"
    return {
        "blend_iron_oxide_pct": blend_iron,
        "blend_lime_pct": blend_lime,
        "shale_share_pct": shale_share,
        "absorption_index": absorption,
        "computed_durability_grade": grade,
    }


# --- clay tonnage commitment (PRD 3.3) ----------------------------------

def expected_clay_commitment(
    green_units_set: int, clay_tons_per_thousand_units: float, shares_pct: List[float]
) -> Dict[str, Any]:
    """
    The run total and the per-pit split, with the residual on the last pit.

    Shares must be given in the components' append order, which is the order the
    PRD walks them in.
    """
    total = round_half_up(
        green_units_set / 1000 * clay_tons_per_thousand_units, 2
    )
    per_pit = [round_half_up(total * s / 100, 2) for s in shares_pct]
    if per_pit:
        residual = round_half_up(total - sum(per_pit[:-1]), 2)
        per_pit[-1] = residual
    return {"total_tons": total, "per_pit_tons": per_pit}


# --- green yield (PRD 3.3) ----------------------------------------------

def expected_projected_net_green_units(green_units_set: int) -> int:
    """Projected loss is the ceiling of 3.5 percent of the set, plus twelve."""
    projected_loss = math.ceil(green_units_set * C.GREEN_HANDLING_LOSS_BP / 10000) + (
        C.SETTING_LOSS_UNITS_PER_CAR
    )
    return green_units_set - projected_loss


def expected_actual_green_yield(green_units_set: int, green_loss_units: int) -> Dict[str, Any]:
    """The realized net units, loss percentage, variance and the resulting fork."""
    net = green_units_set - green_loss_units
    loss_pct = round_half_up(green_loss_units * 100 / green_units_set, 2)
    variance = net - expected_projected_net_green_units(green_units_set)
    status = "SET" if loss_pct <= C.GREEN_LOSS_HOLD_PCT else "HELD"
    return {
        "net_green_units": net,
        "green_loss_pct": loss_pct,
        "green_loss_variance_units": variance,
        "status": status,
    }


# --- firing colour development (PRD 3.4) --------------------------------

def expected_base_cdi(actual_peak_temp_c: int, actual_soak_hours: float) -> float:
    return round_half_up(
        C.CDI_TEMP_COEFF * (actual_peak_temp_c - C.CDI_TEMP_ORIGIN_C) / 10
        + C.CDI_SOAK_COEFF * actual_soak_hours,
        2,
    )


def expected_firing_curve_deviation(
    actual_peak_temp_c: int,
    setpoint_peak_c: int,
    actual_soak_hours: float,
    target_soak_hours: float,
) -> float:
    return round_half_up(
        abs(actual_peak_temp_c - setpoint_peak_c) / 10
        + abs(actual_soak_hours - target_soak_hours),
        2,
    )


def expected_position_temp_delta(kiln_position: int, position_count: int) -> float:
    centreline = (position_count + 1) / 2
    return round_half_up(
        -C.POSITION_TEMP_GRADIENT_C * abs(kiln_position - centreline), 2
    )


def expected_position_cdi(base_cdi: float, position_temp_delta_c: float) -> float:
    return round_half_up(base_cdi + C.CDI_TEMP_COEFF * position_temp_delta_c / 10, 2)


def expected_firing_grade(position_cdi: float, target_cdi: float) -> str:
    """Overfire first, then underfire, then the on-colour band, else salvage."""
    if position_cdi > target_cdi + C.OVERFIRE_CDI_MARGIN:
        return "OVERFIRE_SCRAP"
    if position_cdi < target_cdi - C.UNDERFIRE_CDI_MARGIN:
        return "UNDERFIRE_SCRAP"
    if abs(position_cdi - target_cdi) <= C.ON_COLOR_CDI_BAND:
        return "ON_COLOR"
    return "OFF_COLOR_SALVAGE"


def expected_color_index(position_cdi: float, target_cdi: float) -> float:
    raw = C.COLOR_INDEX_MIDPOINT + C.COLOR_INDEX_CDI_SLOPE * (position_cdi - target_cdi)
    return round_half_up(min(max(raw, C.COLOR_INDEX_MIN), C.COLOR_INDEX_MAX), 2)


def expected_fired_lot_figures(
    actual_peak_temp_c: int,
    actual_soak_hours: float,
    kiln_position: int,
    position_count: int,
    target_cdi: float,
) -> Dict[str, Any]:
    """Everything grading derives for one loaded car position."""
    base = expected_base_cdi(actual_peak_temp_c, actual_soak_hours)
    delta = expected_position_temp_delta(kiln_position, position_count)
    pos_cdi = expected_position_cdi(base, delta)
    return {
        "base_cdi": base,
        "position_temp_delta_c": delta,
        "position_cdi": pos_cdi,
        "grade": expected_firing_grade(pos_cdi, target_cdi),
        "color_index": expected_color_index(pos_cdi, target_cdi),
    }


# --- freight (PRD 3.5, 3.8) ---------------------------------------------

def rectilinear_distance(ax: int, ay: int, bx: int, by: int) -> int:
    """Freight distance on the grid is the rectilinear distance in whole miles."""
    return abs(ax - bx) + abs(ay - by)


def expected_surcharge_cents(base_cents: int) -> int:
    """The three-arm surcharge, keyed on the already-rounded base freight."""
    if base_cents < C.SURCHARGE_TIER_1_CEILING_CENTS:
        pct = C.SURCHARGE_TIER_1_PCT
    elif base_cents < C.SURCHARGE_TIER_2_CEILING_CENTS:
        pct = C.SURCHARGE_TIER_2_PCT
    else:
        pct = C.SURCHARGE_TIER_3_PCT
    return int(round_half_up(base_cents * pct / 100, 0))


def expected_estimated_freight(
    requested_units: int, distance_miles: int, rate_cents: int
) -> Dict[str, Any]:
    """The estimate quoted at plant assignment, from brick weight alone."""
    tons = round_half_up(requested_units * C.UNIT_WEIGHT_LB / C.LB_PER_TON, 2)
    base = int(round_half_up(distance_miles * rate_cents * tons, 0))
    surcharge = expected_surcharge_cents(base)
    return {
        "estimated_billable_tons": tons,
        "estimated_base_freight_cents": base,
        "estimated_fuel_surcharge_cents": surcharge,
        "estimated_freight_cents": base + surcharge,
    }


def expected_final_freight(
    allocated_units: int,
    pallet_count: int,
    band_count: int,
    banding_type: str,
    distance_miles: int,
    rate_cents: int,
) -> Dict[str, Any]:
    """The re-quote at packaging, which adds pallet tare and band weight."""
    lbs = (
        C.PALLET_TARE_LB * pallet_count
        + C.BAND_WEIGHT_LB[banding_type] * band_count
        + C.UNIT_WEIGHT_LB * allocated_units
    )
    tons = round_half_up(lbs / C.LB_PER_TON, 2)
    base = int(round_half_up(distance_miles * rate_cents * tons, 0))
    surcharge = expected_surcharge_cents(base)
    return {
        "final_billable_tons": tons,
        "final_base_freight_cents": base,
        "final_fuel_surcharge_cents": surcharge,
        "final_freight_cents": base + surcharge,
    }


# --- lead time (PRD 3.5) -------------------------------------------------

def expected_lead_time_days(
    requested_units: int,
    base_capacity_green_units_per_day: int,
    is_special_order: bool = False,
    requires_panel_approval: bool = False,
) -> int:
    days = C.BASE_LEAD_DAYS
    if is_special_order:
        days += C.SPECIAL_ORDER_LEAD_DAYS
    if requires_panel_approval:
        days += C.PANEL_APPROVAL_LEAD_DAYS
    days += math.ceil(requested_units / base_capacity_green_units_per_day)
    return days


# --- clock arithmetic ----------------------------------------------------

def parse_iso8601(value: str) -> datetime:
    """
    Parse an ISO 8601 UTC instant with or without fractional seconds.

    Section 2.4 renders `created_at` and `updated_at` "with three fractional
    digits" while the clock itself and the clock-derived stamps are quoted at
    second precision ("exactly 2026-08-01T00:00:00Z", "at 2026-08-16T00:00:00Z"),
    so an instant comparison must accept either rendering.
    """
    text = value[:-1] if value.endswith("Z") else value
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in text else "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)


def same_instant(left: str, right: str) -> bool:
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return parse_iso8601(left) == parse_iso8601(right)


def format_iso8601(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(iso_value: str, days: int) -> str:
    """Add whole UTC days to an instant, preserving the time of day."""
    return format_iso8601(parse_iso8601(iso_value) + timedelta(days=days))


# --- blend colour profile (PRD 3.7) -------------------------------------

def expected_blend_profile(allocations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Recompute a composed blend's colour profile.

    Each allocation is {"color_index", "units", "dye_lot_code"}. The weighted
    index divides the single accumulated sum once and rounds once.
    """
    total_units = sum(a["units"] for a in allocations)
    weighted_sum = sum(a["color_index"] * a["units"] for a in allocations)
    indices = [a["color_index"] for a in allocations]
    return {
        "weighted_color_index": round_half_up(weighted_sum / total_units, 2),
        "color_range_span": round_half_up(max(indices) - min(indices), 2),
        "dye_lot_count": len({a["dye_lot_code"] for a in allocations}),
        "allocated_units": total_units,
    }


def expected_contribution_index(color_index: float, units: int) -> float:
    """A component's audit-only contribution figure."""
    return round_half_up(color_index * units, 2)


# --- entity shape assertions --------------------------------------------

PLANT_FIELDS = [
    "plant_code", "name", "grid_x", "grid_y", "market_radius_miles",
    "freight_rate_cents_per_ton_mile", "base_capacity_green_units_per_day",
    "unloading_equipment_available", "status", "fired_scrap_units", "idled_at",
]

CLAY_PIT_FIELDS = [
    "plant_id", "pit_name", "material_type", "proven_reserve_tons",
    "iron_oxide_pct", "lime_pct", "committed_tons", "consumed_tons",
    "available_tons", "status",
]

FORMULATION_FIELDS = [
    "plant_id", "supersedes_formulation_id", "formulation_code",
    "target_color_family", "target_cdi", "target_soak_hours",
    "clay_tons_per_thousand_units", "components", "component_share_total_pct",
    "blend_iron_oxide_pct", "blend_lime_pct", "shale_share_pct",
    "absorption_index", "computed_durability_grade", "status", "qualified_at",
    "dequalified_count",
]

PRODUCTION_RUN_FIELDS = [
    "plant_id", "formulation_id", "kiln_car_id", "kiln_run_id", "run_code",
    "texture", "green_units_set", "kiln_position", "projected_net_green_units",
    "green_loss_units", "net_green_units", "green_loss_pct",
    "green_loss_variance_units", "clay_tons_committed", "scrap_units", "status",
]

KILN_RUN_FIELDS = [
    "kiln_id", "formulation_id", "run_code", "start_at", "end_at",
    "planned_peak_temp_c", "planned_soak_hours", "actual_peak_temp_c",
    "actual_soak_hours", "base_cdi", "firing_curve_deviation", "loaded_units",
    "graded_by_user_id", "status",
]

FIRED_LOT_FIELDS = [
    "production_run_id", "lot_code", "kiln_position", "fired_units", "grade",
    "position_cdi", "color_index", "color_family", "texture",
    "durability_grade", "dye_lot_code", "source_formulation_id",
    "reserved_units", "consumed_units", "available_units", "quarantine_reason",
    "status",
]

ORDER_FIELDS = [
    "plant_id", "order_code", "jobsite_grid_x", "jobsite_grid_y",
    "requested_units", "color_family", "texture", "durability_grade",
    "is_special_order", "requires_panel_approval",
    "unloading_equipment_required", "banding_type", "pallet_count",
    "band_count", "unloading_equipment_provided", "distance_miles",
    "estimated_billable_tons", "estimated_base_freight_cents",
    "estimated_fuel_surcharge_cents", "estimated_freight_cents",
    "final_billable_tons", "final_base_freight_cents",
    "final_fuel_surcharge_cents", "final_freight_cents",
    "freight_variance_cents", "lead_time_days", "promised_ship_date",
    "assigned_by_user_id", "packaged_by_user_id", "assigned_at",
    "delivered_at", "invoiced_at", "cancellation_reason",
    "fulfillment_status", "freight_status",
]

BLEND_FIELDS = [
    "order_id", "blend_code", "target_color_index_min", "target_color_index_max",
    "target_color_index_midpoint", "requested_units", "allocated_units",
    "weighted_color_index", "color_range_span", "dye_lot_count", "panel_delta_e",
    "composed_by_user_id", "certified_by_user_id", "certified_at",
    "rejection_reason", "rejection_count", "status",
]

BLEND_COMPONENT_FIELDS = [
    "blend_id", "fired_lot_id", "units", "color_index_at_allocation",
    "contribution_index", "source", "status",
]

SAMPLE_PANEL_FIELDS = [
    "order_id", "formulation_id", "dye_lot_id", "panel_code",
    "panel_color_index", "tolerance_delta_e", "pinned_formulation_version",
    "pinned_dye_lot_code", "approved_color_index", "submitted_by_user_id",
    "approved_by_user_id", "approved_at", "expires_at", "revision_round",
    "revision_note", "status",
]


def assert_created_ascending(rows: List[Dict[str, Any]]) -> None:
    """A list response is ordered by created_at ascending."""
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at order: {stamps}"


def find_by_id(rows: List[Dict[str, Any]], target_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row.get("id") == target_id:
            return row
    return None
