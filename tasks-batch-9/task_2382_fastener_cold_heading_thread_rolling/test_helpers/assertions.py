"""Entity assertions and the two conserved-ledger invariant checkers."""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import STRENGTH_CLASS_BANDS, STRENGTH_CLASS_SCAN_ORDER, THRESHOLDS

# ---------------------------------------------------------------------------
# Rounding / arithmetic helpers mirroring PRD §2.6
# ---------------------------------------------------------------------------


def round_half_up(value: float, places: int = 0) -> float:
    """Round half up — a value exactly at the midpoint rounds away from zero."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(result) if places > 0 else float(int(result))


def truncate_down(value: float) -> int:
    """Truncate downward to a whole number of pieces."""
    return int(math.floor(value + 1e-12))


def raise_up(value: float) -> int:
    """Raise upward to the next whole piece."""
    return int(math.ceil(value - 1e-12))


def expected_reduction_pct(inlet_mm: float, outlet_mm: float) -> float:
    """PRD §3.2 drawing reduction: 100 * (1 - (outlet/inlet)^2), half up to 2 dp."""
    ratio = outlet_mm / inlet_mm
    return round_half_up((1.0 - ratio * ratio) * 100.0, 2)


def expected_rated_derated_life(rated_life_pieces: int, regrind_count: int) -> int:
    """PRD §3.3: nameplate times (1 - 0.15 * regrind_count), truncated downward."""
    factor = 1.0 - THRESHOLDS["REGRIND_DERATE_PER_CYCLE"] * regrind_count
    return truncate_down(rated_life_pieces * factor)


def expected_conservative_life(
    rated_derated_life_pieces: int, observed_avg_cycle_pieces: Optional[float]
) -> int:
    """PRD §3.3: min(rated derated, 0.90 * observed average), truncated downward."""
    if observed_avg_cycle_pieces is None:
        return rated_derated_life_pieces
    conservative = THRESHOLDS["CONSERVATIVE_FACTOR"] * observed_avg_cycle_pieces
    return min(rated_derated_life_pieces, truncate_down(conservative))


def expected_normal_sample_size(available_count: int) -> int:
    """PRD §3.7 normal inspection: max(8, ceil(sqrt(available_count)))."""
    return max(
        THRESHOLDS["NORMAL_SAMPLE_FLOOR"], raise_up(math.sqrt(available_count))
    )


def expected_tightened_sample_size(available_count: int) -> int:
    """PRD §3.7 tightened inspection: max(13, ceil(1.5 * sqrt(available_count)))."""
    return max(
        THRESHOLDS["TIGHTENED_SAMPLE_FLOOR"],
        raise_up(
            THRESHOLDS["TIGHTENED_SAMPLE_MULTIPLIER"] * math.sqrt(available_count)
        ),
    )


def expected_achieved_strength_class(
    measured_hv: float, specified_class: str
) -> str:
    """PRD §3.7: the specified class gets first refusal, then the fixed scan order."""
    lo, hi = STRENGTH_CLASS_BANDS[specified_class]
    if lo <= measured_hv <= hi:
        return specified_class
    for candidate in STRENGTH_CLASS_SCAN_ORDER:
        lo, hi = STRENGTH_CLASS_BANDS[candidate]
        if lo <= measured_hv <= hi:
            return candidate
    return "NONE"


# ---------------------------------------------------------------------------
# Shared system-managed field assertions (PRD §2.5)
# ---------------------------------------------------------------------------


def assert_system_fields(data: Dict[str, Any], expected_version: Optional[int] = None):
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_no_type_prefix(entity_id: str):
    """PRD §2.5: the id "carries no type prefix"."""
    assert ":" not in entity_id and "_" not in entity_id, (
        f"id must not carry a type prefix, got {entity_id!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_part_spec(data: Dict[str, Any]):
    assert_system_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["thread_designation"], str)
    assert data["strength_class"] in [
        "CLASS_8_8",
        "CLASS_10_9",
        "CLASS_12_9",
        "GRADE_5",
        "GRADE_8",
    ]
    assert data["qualification_program"] in [
        "NONE",
        "AUTOMOTIVE_PPAP",
        "AEROSPACE_NADCAP",
    ]
    assert isinstance(data["allowed_steel_grades"], list) and data["allowed_steel_grades"]
    assert data["blank_mass_g"] > 0
    assert 0 <= data["scrap_allowance_pct"] <= 0.20
    assert data["station_count_required"] >= 1
    assert data["thread_timing"] in ["BEFORE_HEAT_TREAT", "AFTER_HEAT_TREAT"]
    assert "THREAD_ROLL" in data["required_secondary_ops"]
    assert data["plating_spec"] in ["NONE", "ZINC_CLEAR", "ZINC_NICKEL", "CADMIUM"]
    assert data["packaging_mode"] in ["BY_COUNT", "BY_WEIGHT"]
    assert data["nominal_pack_count"] >= 1
    assert data["pieces_per_kg"] > 0
    assert isinstance(data["he_bake_required"], bool)
    assert isinstance(data["he_bake_min_minutes"], int)
    assert_bake_duty_derivation(data)


def assert_bake_duty_derivation(data: Dict[str, Any]):
    """PRD §3.1: he_bake_required and he_bake_min_minutes follow from the finish."""
    prone = data["strength_class"] in ["CLASS_10_9", "CLASS_12_9", "GRADE_8"]
    expected_required = data["plating_spec"] != "NONE" and prone
    assert data["he_bake_required"] is expected_required, (
        f"he_bake_required should be {expected_required} for "
        f"{data['plating_spec']} / {data['strength_class']}"
    )
    if not expected_required:
        expected_minutes = 0
    elif data["strength_class"] in ["CLASS_12_9", "GRADE_8"]:
        expected_minutes = 480
    else:
        expected_minutes = 240
    assert data["he_bake_min_minutes"] == expected_minutes, (
        f"he_bake_min_minutes should be {expected_minutes}, "
        f"got {data['he_bake_min_minutes']}"
    )


def assert_steel_heat(data: Dict[str, Any]):
    assert_system_fields(data)
    assert isinstance(data["heat_number"], str) and data["heat_number"]
    assert isinstance(data["mill_code"], str)
    assert data["grade"] in ["SAE_1018", "SAE_1038", "SAE_10B21", "SAE_4037"]
    assert data["gross_mass_kg"] > 0
    assert isinstance(data["mill_cert_serial"], str) and data["mill_cert_serial"]
    assert data["cert_status"] in [
        "PENDING",
        "VERIFIED",
        "SUSPECTED_COUNTERFEIT",
        "REJECTED",
    ]


def assert_wire_lot(data: Dict[str, Any]):
    assert_system_fields(data)
    assert is_valid_uuid(data["steel_heat_id"])
    assert data["draw_pass_count"] >= 1
    assert data["inlet_diameter_mm"] > 0
    assert 0 < data["outlet_diameter_mm"] < data["inlet_diameter_mm"]
    assert data["lubricant_coating"] in ["PHOSPHATE", "POLYMER", "LIME", "NONE"]
    assert data["coating_weight_gsm"] >= 0
    assert data["gross_mass_kg"] > 0
    assert data["status"] in ["DRAWN", "RELEASED", "QUARANTINED"]
    assert data["quarantine_source"] in ["NONE", "HEAT_COUNTERFEIT", "HEAT_REJECTED"]
    assert data["reduction_pct"] == expected_reduction_pct(
        data["inlet_diameter_mm"], data["outlet_diameter_mm"]
    ), "reduction_pct must equal 100*(1-(outlet/inlet)^2) rounded half up to 2 dp"
    assert_wire_mass_ledger(data)


def assert_wire_mass_ledger(data: Dict[str, Any]):
    """PRD §2.8: gross_mass_kg == available + reserved + consumed, always."""
    total = (
        data["available_mass_kg"] + data["reserved_mass_kg"] + data["consumed_mass_kg"]
    )
    assert abs(total - data["gross_mass_kg"]) < 0.0005, (
        f"Wire mass ledger broken: {data['available_mass_kg']} + "
        f"{data['reserved_mass_kg']} + {data['consumed_mass_kg']} != "
        f"{data['gross_mass_kg']}"
    )


def assert_heading_tool(data: Dict[str, Any]):
    assert_system_fields(data)
    assert isinstance(data["tool_code"], str) and data["tool_code"]
    assert data["station_count"] >= 1
    assert data["rated_life_pieces"] >= 1
    assert data["max_regrinds"] >= 0
    assert data["regrind_count"] >= 0
    assert data["cumulative_pieces_current_cycle"] >= 0
    assert isinstance(data["cycle_pieces_history"], list)
    assert data["completed_cycle_count"] == len(data["cycle_pieces_history"]), (
        "completed_cycle_count is the length of cycle_pieces_history"
    )
    assert data["lifetime_pieces"] == sum(data["cycle_pieces_history"]) + data[
        "cumulative_pieces_current_cycle"
    ], "lifetime_pieces is the history sum plus the open cycle"
    assert data["status"] in ["AVAILABLE", "MOUNTED", "WORN", "SCRAPPED"]
    assert data["rated_derated_life_pieces"] == expected_rated_derated_life(
        data["rated_life_pieces"], data["regrind_count"]
    ), "rated_derated_life_pieces must derate the nameplate by 0.15 per regrind"
    assert data["conservative_life_pieces"] == expected_conservative_life(
        data["rated_derated_life_pieces"], data["observed_avg_cycle_pieces"]
    ), "conservative_life_pieces must be min(derated, 0.90*observed) truncated down"


def assert_furnace(data: Dict[str, Any]):
    assert_system_fields(data)
    assert isinstance(data["furnace_code"], str) and data["furnace_code"]
    assert data["max_charge_mass_kg"] > 0
    assert data["cooldown_minutes"] >= 0
    assert data["status"] in ["IDLE", "OCCUPIED"]


def assert_production_lot(data: Dict[str, Any]):
    assert_system_fields(data)
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert is_valid_uuid(data["part_spec_id"])
    assert is_valid_uuid(data["wire_lot_id"])
    assert is_valid_uuid(data["heading_tool_id"])
    assert is_valid_uuid(data["traceability_heat_id"])
    assert isinstance(data["pinned_part_spec_version"], int)
    assert data["planned_pieces"] >= 1
    assert data["process_state"] in [
        "SETUP",
        "HEADED",
        "SECONDARY_IN_PROGRESS",
        "SECONDARY_DONE",
        "HEAT_TREATED",
        "PLATED",
        "BAKED",
        "TESTING",
        "TESTED",
        "CERTIFIED",
        "PACKED",
        "SHIPPED",
        "ABORTED",
    ]
    assert data["disposition"] in ["IN_PROCESS", "HOLD", "QUARANTINED", "SCRAPPED"]
    assert data["hold_source"] in [
        "NONE",
        "TOOL_WEAR",
        "HT_FAILURE",
        "TEST_REJECT",
        "QUALITY",
        "HEAT_COUNTERFEIT",
    ]
    assert isinstance(data["heat_treat_completed"], bool)
    assert_lot_piece_ledger(data)


def assert_lot_piece_ledger(data: Dict[str, Any]):
    """PRD §2.8: headed_count + heading_scrap_count == available + scrap +
    destructive_test + packed."""
    left = data["headed_count"] + data["heading_scrap_count"]
    right = (
        data["available_count"]
        + data["scrap_count"]
        + data["destructive_test_count"]
        + data["packed_count"]
    )
    assert left == right, (
        f"Lot piece ledger broken: headed {data['headed_count']} + heading scrap "
        f"{data['heading_scrap_count']} != available {data['available_count']} + "
        f"scrap {data['scrap_count']} + destructive {data['destructive_test_count']} "
        f"+ packed {data['packed_count']}"
    )


def assert_secondary_operation(data: Dict[str, Any]):
    assert_system_fields(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert data["op_type"] in ["THREAD_ROLL", "DRILL", "SLOT", "POINT"]
    assert data["sequence_no"] >= 1
    assert isinstance(data["machine_code"], str)
    assert data["pieces_in"] >= 0
    assert data["status"] in ["PENDING", "DONE"]
    assert isinstance(data["performed_after_heat_treat"], bool)
    if data["status"] == "DONE":
        assert 0 <= data["pieces_out"] <= data["pieces_in"]
        assert data["scrap_pieces"] == data["pieces_in"] - data["pieces_out"], (
            "scrap_pieces is pieces_in minus pieces_out"
        )


def assert_heat_treat_run(data: Dict[str, Any]):
    assert_system_fields(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert is_valid_uuid(data["furnace_id"])
    assert data["quench_medium"] in ["OIL", "WATER", "POLYMER"]
    assert data["temper_time_min"] >= 1
    assert data["charge_mass_kg"] >= 0
    assert data["status"] in ["PLANNED", "RUNNING", "COMPLETED"]
    assert data["result"] in ["PENDING", "PASS", "FAIL_HARDNESS", "FAIL_DECARB"]


def assert_plating_run(data: Dict[str, Any]):
    assert_system_fields(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert data["plating_spec"] in ["ZINC_CLEAR", "ZINC_NICKEL", "CADMIUM"]
    assert data["load_mass_kg"] >= 0
    assert data["status"] in [
        "SCHEDULED",
        "PLATED",
        "BAKING",
        "BAKE_COMPLETE",
        "SUPERSEDED",
    ]


def assert_lot_test(data: Dict[str, Any]):
    assert_system_fields(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert data["severity"] in ["NORMAL", "TIGHTENED"]
    assert data["sample_size"] >= 1
    assert data["acceptance_number"] >= 0
    assert isinstance(data["destructive"], bool)
    assert data["result"] in ["PENDING", "ACCEPT", "REJECT"]
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    if data["result"] in ["ACCEPT", "REJECT"]:
        assert data["total_failures"] == (
            data["proof_load_failures"] + data["tensile_failures"]
        ), "total_failures is the sum of the two failure counts"
        expected = "ACCEPT" if data["total_failures"] <= data["acceptance_number"] else "REJECT"
        assert data["result"] == expected, (
            f"With {data['total_failures']} failures against acceptance number "
            f"{data['acceptance_number']} the verdict must be {expected}"
        )


def assert_certification_document(data: Dict[str, Any]):
    assert_system_fields(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert is_valid_uuid(data["lot_test_id"])
    assert isinstance(data["cert_serial"], str) and data["cert_serial"]
    assert data["revision"] >= 1
    assert isinstance(data["pinned_part_spec_version"], int)
    assert data["status"] in ["DRAFT", "ISSUED", "REVOKED", "REISSUE_PENDING"]
    assert isinstance(data["traceability_chain"], dict)


def assert_pack_unit(data: Dict[str, Any]):
    assert_system_fields(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert is_valid_uuid(data["certification_document_id"])
    assert isinstance(data["label_serial"], str) and data["label_serial"]
    assert data["pack_mode"] in ["BY_COUNT", "BY_WEIGHT"]
    assert data["declared_count"] >= 0
    assert data["count_tolerance_pieces"] >= 0
    assert isinstance(data["label_fields_complete"], bool)
    assert data["status"] in ["OPEN", "SEALED", "SHIPPED", "RECALLED"]


TRACEABILITY_CHAIN_KEYS = [
    "heat_number",
    "mill_code",
    "mill_cert_serial",
    "cert_status",
    "wire_lot_reduction_pct",
    "lubricant_coating",
    "tool_code",
    "tool_regrind_count",
    "tool_utilization_pct",
    "austenitize_temp_c",
    "core_hardness_hv",
    "total_decarb_depth_mm",
    "bake_delay_hours",
    "bake_duration_min",
    "pinned_part_spec_version",
]


def assert_traceability_projection(chain: Dict[str, Any]):
    """Every field PRD §3.8 lists in the provenance projection is present."""
    for key in TRACEABILITY_CHAIN_KEYS:
        assert key in chain, f"traceability projection missing {key!r}"


def assert_versions_incremented(before: Dict[str, Any], after: Dict[str, Any], by: int = 1):
    """PRD §2.5: version increments by exactly 1 on every mutation of that record."""
    assert after["version"] == before["version"] + by, (
        f"Expected version {before['version'] + by}, got {after['version']}"
    )


def assert_sorted_by_created_at_asc(rows: List[Dict[str, Any]]):
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"Expected ascending created_at order, got {stamps}"


def assert_sorted_by_created_at_desc(rows: List[Dict[str, Any]]):
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps, reverse=True), (
        f"Expected descending created_at order, got {stamps}"
    )
