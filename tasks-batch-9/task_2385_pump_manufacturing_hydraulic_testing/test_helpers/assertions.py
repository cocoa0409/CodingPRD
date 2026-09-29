"""Domain assertions for the pump manufacturing and hydraulic testing API.

Two groups live here:

* `assert_<entity>` shape checkers, which verify that a payload carries every
  field the PRD entity prose promises, with the right kinds of values and the
  right common-property set;
* invariant checkers for the conserved quantities and the derived numbers the
  PRD pins in sections 2.9, 2.11 and 3.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import constants as K

MONEY_TOL = 0.005
RATIO_TOL = 0.0001


# ── Common property blocks (PRD 2.4) ─────────────────────────────────────────
def assert_common_fields(row: Dict[str, Any], *, versioned: bool = True) -> None:
    """Every row carries id and created_at; versioned rows add updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {row.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(row["updated_at"]), (
            f"updated_at is not an ISO 8601 UTC timestamp: {row.get('updated_at')!r}"
        )
        assert isinstance(row["version"], int), "version must be an integer"
        assert row["version"] >= 1, "version starts at 1"
    else:
        assert "updated_at" not in row, (
            "this row is immutable and must not carry updated_at"
        )
        assert "version" not in row, "this row is immutable and must not carry version"


def assert_fields_present(row: Dict[str, Any], names: List[str]) -> None:
    missing = [n for n in names if n not in row]
    assert not missing, f"missing fields: {missing}"


# ── Per-entity shape checkers ────────────────────────────────────────────────
def assert_foundry(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "foundry_code",
            "name",
            "approved_alloys",
            "concurrent_pour_capacity",
            "status",
            "suspension_reason",
        ],
    )
    assert isinstance(row["approved_alloys"], list)
    assert isinstance(row["concurrent_pour_capacity"], int)
    assert row["status"] in ("ACTIVE", "SUSPENDED")


def assert_pump_model(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "model_code",
            "generation",
            "interchange_group",
            "max_impeller_diameter_mm",
            "min_impeller_diameter_mm",
            "shutoff_head_m",
            "bep_flow_m3h",
            "bep_head_m",
            "bep_efficiency_pct",
            "npshr_at_bep_m",
            "rated_speed_rpm",
            "max_flow_m3h",
            "rotor_mass_kg",
            "balance_grade",
            "superseded_by_model_id",
            "status",
            "warranty_defect_count",
            "application_error_count",
            "no_defect_count",
        ],
    )
    assert row["balance_grade"] in K.BALANCE_GRADE_G
    assert row["status"] in ("ORDERABLE", "PATTERN_CONSTRAINED", "SUPERSEDED")


def assert_pattern_asset(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "pump_model_id",
            "foundry_id",
            "pattern_code",
            "wear_threshold",
            "pours_since_refurb",
            "defect_pours_since_refurb",
            "wear_index",
            "refurb_cycles",
            "status",
        ],
    )
    assert row["status"] in ("QUALIFIED", "WORN", "IN_REFURB", "RETIRED")


def assert_material_seal_config(row: Dict[str, Any]) -> None:
    assert_common_fields(row, versioned=False)
    assert_fields_present(
        row,
        [
            "pump_model_id",
            "config_code",
            "casing_material",
            "impeller_material",
            "seal_type",
            "flush_plan",
            "service_class",
            "max_solids_pct",
            "max_viscosity_cst",
            "max_chloride_ppm",
            "max_temp_c",
            "min_running_clearance_mm",
        ],
    )


def assert_duty_application(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "application_code",
            "customer_name",
            "duty_flow_m3h",
            "duty_head_m",
            "npsha_available_m",
            "specific_gravity",
            "viscosity_cst",
            "solids_pct",
            "chloride_ppm",
            "process_temp_c",
            "min_efficiency_pct",
            "test_grade",
            "witness_required",
            "service_class_required",
            "status",
        ],
    )
    assert row["test_grade"] in K.GRADE_TABLE
    assert row["status"] in ("OPEN", "SELECTION_LOCKED", "CONTRACTED", "CLOSED")


def assert_selection(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "duty_application_id",
            "pump_model_id",
            "material_seal_config_id",
            "trimmed_impeller_diameter_mm",
            "diameter_ratio",
            "predicted_head_m",
            "predicted_efficiency_pct",
            "predicted_shaft_power_kw",
            "npshr_catalog_m",
            "npsh_provisional_margin_m",
            "npsh_safety_factor",
            "npshr_certified_m",
            "npsh_margin_m",
            "min_motor_kw",
            "proposed_by_user_id",
            "approved_by_user_id",
            "status",
        ],
    )
    assert row["status"] in (
        "DRAFT",
        "PROPOSED",
        "APPROVED",
        "UNDER_REVIEW",
        "SUPERSEDED",
    )


def assert_casting_lot(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "pattern_asset_id",
            "foundry_id",
            "heat_number",
            "alloy_code",
            "qty_poured",
            "pour_window_start",
            "pour_window_end",
            "qty_scrapped",
            "qty_rework_pending",
            "qty_accepted",
            "committed_build_count",
            "status",
        ],
    )
    assert row["status"] in (
        "POURED",
        "INSPECTED",
        "ACCEPTED",
        "QUARANTINED",
        "REWORK",
        "SCRAPPED",
    )
    assert_piece_ledger_conserved(row)


def assert_casting_defect(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "casting_lot_id",
            "defect_code",
            "defect_type",
            "severity",
            "affected_qty",
            "reported_by_user_id",
            "dispositioned_by_user_id",
            "disposition",
            "status",
        ],
    )
    assert row["severity"] in ("MINOR", "MAJOR", "CRITICAL")


def assert_build_order(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "selection_id",
            "casting_lot_id",
            "serial_number",
            "running_clearance_mm",
            "residual_unbalance_g_mm",
            "seal_flush_plan_installed",
            "allowable_unbalance_g_mm",
            "rework_cycles",
            "status",
        ],
    )
    assert row["status"] in (
        "PLANNED",
        "ASSEMBLED",
        "TESTED",
        "REWORK_REQUIRED",
        "CASTING_SHORT",
        "CLOSED",
    )


def assert_test_run(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "build_order_id",
            "test_speed_rpm",
            "correction_basis",
            "test_grade",
            "witness_required",
            "speed_ratio",
            "head_at_guarantee_m",
            "power_at_guarantee_kw",
            "efficiency_at_guarantee_pct",
            "head_deviation_pct",
            "efficiency_deviation_pct",
            "npshr_tested_m",
            "run_state",
            "hydraulic_status",
            "npsh_status",
        ],
    )
    assert row["run_state"] in ("OPEN", "POINTS_LOCKED", "EVALUATED", "CERTIFIED")
    assert row["hydraulic_status"] in (
        "NOT_EVALUATED",
        "WITHIN_TOLERANCE",
        "OUT_OF_TOLERANCE",
    )
    assert row["npsh_status"] in ("NOT_VERIFIED", "VERIFIED", "REJECTED")


def assert_test_point(row: Dict[str, Any]) -> None:
    assert_common_fields(row, versioned=False)
    assert_fields_present(
        row,
        [
            "test_run_id",
            "measured_flow_m3h",
            "measured_head_m",
            "measured_power_kw",
            "measured_npsh3_m",
            "is_npsh_point",
        ],
    )
    assert isinstance(row["is_npsh_point"], bool)


def assert_pump_package(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "build_order_id",
            "test_run_id",
            "baseplate_code",
            "motor_kw",
            "motor_frame",
            "control_type",
            "promised_ship_date",
            "actual_ship_date",
            "min_motor_kw",
            "guarantee_basis",
            "application_error_flagged",
            "status",
        ],
    )
    assert row["status"] in ("CONFIGURED", "RELEASED", "HELD", "SHIPPED")


def assert_repair_kit(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "pump_model_id",
            "kit_code",
            "interchange_group",
            "gen_min",
            "gen_max",
            "preferred_generation",
            "substitution_penalty_pct",
            "unit_price",
            "support_window_start",
            "support_window_end",
            "qty_received_total",
            "qty_on_hand",
            "qty_reserved",
            "qty_issued",
            "qty_consumed_total",
            "status",
        ],
    )
    assert row["status"] in ("ACTIVE", "DISCONTINUED")
    assert_kit_units_conserved(row)


def assert_kit_allocation(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "repair_kit_id",
            "build_order_id",
            "requested_qty",
            "selected_by",
            "substitution_penalty_applied_pct",
            "parts_extended",
            "handling_rate",
            "handling_fee",
            "total_charge",
            "status",
        ],
    )
    assert row["selected_by"] in ("EXPLICIT", "SELECTOR")
    assert row["status"] in ("RESERVED", "ISSUED", "CONSUMED", "RELEASED")


def assert_warranty_claim(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert_fields_present(
        row,
        [
            "pump_package_id",
            "as_found_flow_m3h",
            "as_found_head_m",
            "as_found_npsha_m",
            "as_found_solids_pct",
            "as_found_viscosity_cst",
            "as_found_speed_rpm",
            "claim_lines",
            "submitted_by_user_id",
            "adjudicated_by_user_id",
            "info_request_note",
            "liability_basis",
            "expected_head_m",
            "head_shortfall_pct",
            "application_error_flags",
            "determination",
            "months_since_ship",
            "coverage_factor",
            "settlement_subtotal",
            "admin_fee",
            "settlement_total",
            "status",
        ],
    )
    assert isinstance(row["claim_lines"], list) and row["claim_lines"]
    assert isinstance(row["application_error_flags"], list)


# ── Numeric helpers ──────────────────────────────────────────────────────────
def assert_money(actual: Optional[float], expected: float, label: str = "") -> None:
    """Compare a two-decimal money value."""
    assert actual is not None, f"{label or 'value'} must not be null"
    assert actual == pytest.approx(expected, abs=MONEY_TOL), (
        f"{label or 'value'}: expected {expected}, got {actual}"
    )


def assert_two_decimals(actual: float, label: str = "") -> None:
    assert round(float(actual), 2) == pytest.approx(float(actual), abs=1e-9), (
        f"{label or 'value'} carries more than two decimals: {actual}"
    )


def assert_one_decimal(actual: float, label: str = "") -> None:
    assert round(float(actual), 1) == pytest.approx(float(actual), abs=1e-9), (
        f"{label or 'value'} carries more than one decimal: {actual}"
    )


# ── Conserved quantities (PRD 2.9) ───────────────────────────────────────────
def assert_piece_ledger_conserved(lot: Dict[str, Any]) -> None:
    """qty_accepted + qty_rework_pending + qty_scrapped equals qty_poured."""
    total = lot["qty_accepted"] + lot["qty_rework_pending"] + lot["qty_scrapped"]
    assert total == lot["qty_poured"], (
        "casting piece ledger drifted: "
        f"accepted {lot['qty_accepted']} + rework {lot['qty_rework_pending']} "
        f"+ scrapped {lot['qty_scrapped']} != poured {lot['qty_poured']}"
    )


def assert_kit_units_conserved(kit: Dict[str, Any]) -> None:
    """on_hand + reserved + issued + consumed_total equals received_total."""
    total = (
        kit["qty_on_hand"]
        + kit["qty_reserved"]
        + kit["qty_issued"]
        + kit["qty_consumed_total"]
    )
    assert total == kit["qty_received_total"], (
        "repair kit unit conservation drifted: "
        f"on_hand {kit['qty_on_hand']} + reserved {kit['qty_reserved']} "
        f"+ issued {kit['qty_issued']} + consumed {kit['qty_consumed_total']} "
        f"!= received {kit['qty_received_total']}"
    )


def assert_wear_index(pattern: Dict[str, Any]) -> None:
    """wear_index is pours_since_refurb plus twice defect_pours_since_refurb."""
    expected = pattern["pours_since_refurb"] + K.PATTERN_DEFECT_WEIGHT * (
        pattern["defect_pours_since_refurb"]
    )
    assert pattern["wear_index"] == expected, (
        f"wear_index {pattern['wear_index']} does not equal "
        f"pours {pattern['pours_since_refurb']} + 2 x defect pours "
        f"{pattern['defect_pours_since_refurb']}"
    )


# ── Derived-value recomputation ──────────────────────────────────────────────
def round_half_up(value: float, places: int = 2) -> float:
    """Round half up, the rounding mode the contract pins in PRD 2.5."""
    from decimal import Decimal, ROUND_HALF_UP

    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def expected_allowable_unbalance(
    balance_grade: str, rotor_mass_kg: float, rated_speed_rpm: int
) -> float:
    """ISO 1940 allowance: G x 9549 x rotor mass / rated speed, rounded to two decimals."""
    g = K.BALANCE_GRADE_G[balance_grade]
    return round_half_up(g * K.ISO1940_COEFF * rotor_mass_kg / rated_speed_rpm, 2)


def expected_handling_rate(parts_extended: float) -> float:
    """Handling rate tier lookup on parts_extended, upper edge inclusive."""
    for edge, rate in K.HANDLING_RATE_TIERS:
        if parts_extended <= edge:
            return rate
    return K.HANDLING_RATE_ABOVE_TOP


def expected_coverage_factor(months_since_ship: int) -> Optional[float]:
    """Coverage factor tier lookup on months_since_ship, upper edge inclusive."""
    for edge, factor in K.COVERAGE_FACTOR_TIERS:
        if months_since_ship <= edge:
            return factor
    return None


def expected_npsh_safety_factor(provisional_margin_m: float) -> float:
    """Safety factor tier lookup on the provisional margin, upper edge exclusive."""
    for edge, factor in K.NPSH_SAFETY_TIERS:
        if provisional_margin_m < edge:
            return factor
    return K.NPSH_SAFETY_ABOVE_TOP


def expected_settlement(
    gross_amounts: List[float], coverage_factor: float
) -> Dict[str, float]:
    """Round each line, then sum, then take the administration fee (PRD 3.9)."""
    per_line = [round_half_up(g * coverage_factor, 2) for g in gross_amounts]
    subtotal = round_half_up(sum(per_line), 2)
    admin_fee = round_half_up(subtotal * K.ADMIN_RATE, 2)
    total = round_half_up(subtotal + admin_fee, 2)
    return {
        "settlement_subtotal": subtotal,
        "admin_fee": admin_fee,
        "settlement_total": total,
    }


def assert_settlement(claim: Dict[str, Any], gross_amounts: List[float]) -> None:
    expected = expected_settlement(gross_amounts, claim["coverage_factor"])
    for key, value in expected.items():
        assert_money(claim[key], value, key)


def assert_kit_charge(
    allocation: Dict[str, Any], unit_price: float, penalty_pct: float
) -> None:
    """parts_extended, handling_rate, handling_fee and total_charge cohere (PRD 3.8)."""
    effective_unit = round_half_up(unit_price * (1.0 + penalty_pct / 100.0), 2)
    parts_extended = round_half_up(effective_unit * allocation["requested_qty"], 2)
    assert_money(allocation["parts_extended"], parts_extended, "parts_extended")
    rate = expected_handling_rate(parts_extended)
    assert allocation["handling_rate"] == pytest.approx(rate, abs=RATIO_TOL), (
        f"handling_rate: expected {rate}, got {allocation['handling_rate']}"
    )
    fee = round_half_up(parts_extended * rate, 2)
    assert_money(allocation["handling_fee"], fee, "handling_fee")
    assert_money(
        allocation["total_charge"], round_half_up(parts_extended + fee, 2), "total_charge"
    )


# ── Test-run result dimensions ───────────────────────────────────────────────
def assert_run_dimensions(
    run: Dict[str, Any], run_state: str, hydraulic_status: str, npsh_status: str
) -> None:
    """The three independent result dimensions of one test run (PRD 3.6)."""
    assert run["run_state"] == run_state, (
        f"run_state: expected {run_state}, got {run['run_state']}"
    )
    assert run["hydraulic_status"] == hydraulic_status, (
        f"hydraulic_status: expected {hydraulic_status}, got {run['hydraulic_status']}"
    )
    assert run["npsh_status"] == npsh_status, (
        f"npsh_status: expected {npsh_status}, got {run['npsh_status']}"
    )


def assert_run_results_cleared(run: Dict[str, Any]) -> None:
    """All six reported values are null again after a reopen (PRD 3.6)."""
    for field in (
        "speed_ratio",
        "head_at_guarantee_m",
        "power_at_guarantee_kw",
        "efficiency_at_guarantee_pct",
        "head_deviation_pct",
        "efficiency_deviation_pct",
        "npshr_tested_m",
    ):
        assert run[field] is None, f"{field} should be null but is {run[field]}"


def assert_head_within_grade(run: Dict[str, Any], test_grade: str) -> None:
    """Head deviation sits inside the two-sided grade band, edges inclusive."""
    tol = K.GRADE_TABLE[test_grade]["head_tol_pct"]
    assert -tol <= run["head_deviation_pct"] <= tol, (
        f"head_deviation_pct {run['head_deviation_pct']} is outside "
        f"+/-{tol} for {test_grade}"
    )


def assert_error_envelope(body: Dict[str, Any], error_id: str) -> None:
    """PRD 2.2: a rejected request carries meta, response_type error and data."""
    assert set(body.keys()) >= {"meta", "response_type", "data"}
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["data"]["error_id"] == error_id
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
