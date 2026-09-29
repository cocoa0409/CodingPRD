"""Entity assertions and domain invariant checkers for the hydrogen API."""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    KG_PER_L_PER_BAR,
    METER_TOLERANCE_PCT,
    MIN_HIGH_BANK_DELIVERABLE_KG,
)

# ─── Shape helpers ────────────────────────────────────────────────────────


def assert_common_fields(data: Dict[str, Any]) -> None:
    """Assert the four fields every versioned resource carries."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only records carry only id and created_at — no version axis."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "version" not in data, "an append-only record must carry no version field"
    assert "updated_at" not in data, "an append-only record must carry no updated_at field"


def assert_decimals(value: float, places: int, label: str) -> None:
    """Assert a number is carried at no more than `places` decimal places."""
    assert value is not None, f"{label} must be present"
    assert round(float(value), places) == pytest.approx(
        float(value)
    ), f"{label} must carry at most {places} decimal places, got {value}"


def assert_kg(value: float, label: str) -> None:
    assert_decimals(value, 3, label)


def assert_bar(value: float, label: str) -> None:
    assert_decimals(value, 2, label)


def assert_pct_3dp(value: float, label: str) -> None:
    assert_decimals(value, 3, label)


# ─── Envelope helper ──────────────────────────────────────────────────────


def assert_request_id(meta: Dict[str, Any]) -> None:
    request_id = meta.get("api_request_id", "")
    assert isinstance(request_id, str) and request_id.startswith(
        "req_"
    ), f"meta.api_request_id must begin with 'req_', got {request_id!r}"


# ─── Entity assertions ────────────────────────────────────────────────────


def assert_funding_agreement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["agreement_code"], str) and data["agreement_code"]
    assert isinstance(data["funder_name"], str) and data["funder_name"]
    assert 0 <= data["min_uptime_pct"] <= 100
    assert_pct_3dp(data["min_uptime_pct"], "min_uptime_pct")
    assert isinstance(data["penalty_per_point_cents"], int) and data["penalty_per_point_cents"] >= 0
    assert isinstance(data["initial_holdback_cents"], int) and data["initial_holdback_cents"] >= 0
    assert isinstance(data["holdback_balance_cents"], int)
    assert 0 <= data["holdback_balance_cents"] <= data["initial_holdback_cents"], (
        "holdback_balance_cents is floored at zero and never exceeds initial_holdback_cents"
    )
    assert data["uptime_method"] in ("NOZZLE_WEIGHTED", "STATION_LEVEL")


def assert_station(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["funding_agreement_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["nozzle_count"], int) and data["nozzle_count"] >= 1
    assert isinstance(data["offload_bay_count"], int) and data["offload_bay_count"] >= 1
    assert data["storage_capacity_kg"] > 0
    assert data["reserve_floor_kg"] >= 0
    assert data["max_pressure_class"] in ("H35", "H70")
    assert isinstance(data["setback_compliant"], bool)
    assert data["ventilation_status"] in ("NORMAL", "FAULT")
    assert data["leak_detection_status"] in ("NORMAL", "ALARM")
    assert data["compressor_status"] in ("ONLINE", "OFFLINE")
    assert data["safety_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["metering_accuracy_flag"] in ("WITHIN_TOLERANCE", "OUT_OF_TOLERANCE")
    assert isinstance(data["supply_alert"], bool)
    for field in (
        "onsite_inventory_kg",
        "reserved_kg",
        "available_kg",
        "total_deliverable_kg",
        "high_bank_deliverable_kg",
        "inbound_planned_kg",
        "projected_available_kg",
        "metered_kg_mtd",
        "corrected_kg_mtd",
    ):
        assert_kg(data[field], field)
    assert_pct_3dp(data["metering_error_pct_mtd"], "metering_error_pct_mtd")


def assert_station_derivations_consistent(data: Dict[str, Any]) -> None:
    """The station's derived aggregates must agree with one another."""
    assert data["available_kg"] == pytest.approx(
        data["onsite_inventory_kg"] - data["reserved_kg"], abs=0.001
    ), "available_kg is onsite_inventory_kg minus reserved_kg"
    assert data["projected_available_kg"] == pytest.approx(
        data["available_kg"] + data["inbound_planned_kg"], abs=0.001
    ), "projected_available_kg is available_kg plus inbound_planned_kg"
    assert data["supply_alert"] is (
        data["projected_available_kg"] < data["reserve_floor_kg"]
    ), "supply_alert is true exactly when projected_available_kg is below reserve_floor_kg"
    assert data["high_bank_deliverable_kg"] <= data["total_deliverable_kg"] + 0.001, (
        "high_bank_deliverable_kg is a restriction of total_deliverable_kg"
    )
    assert data["metering_accuracy_flag"] == (
        "WITHIN_TOLERANCE"
        if abs(data["metering_error_pct_mtd"]) <= METER_TOLERANCE_PCT
        else "OUT_OF_TOLERANCE"
    )


def assert_posture_band(data: Dict[str, Any]) -> None:
    """The first matching posture band must be the one reported."""
    frozen_conditions = (
        data["leak_detection_status"] == "ALARM"
        or data["ventilation_status"] == "FAULT"
        or data["setback_compliant"] is False
    )
    if frozen_conditions:
        assert data["safety_posture"] == "FROZEN", (
            "a leak alarm, ventilation fault or setback breach freezes the station"
        )
        return
    if data["safety_posture"] == "OPEN":
        assert data["compressor_status"] == "ONLINE"
        assert data["high_bank_deliverable_kg"] >= MIN_HIGH_BANK_DELIVERABLE_KG


def assert_pressure_vessel(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert data["bank_tier"] in ("HIGH", "MEDIUM", "LOW")
    assert data["water_volume_l"] > 0
    assert data["mawp_bar"] > 0
    assert 0 <= data["min_residual_bar"] < data["mawp_bar"]
    assert_bar(data["current_pressure_bar"], "current_pressure_bar")
    assert_kg(data["stored_mass_kg"], "stored_mass_kg")
    assert data["inspection_status"] in ("CURRENT", "DUE", "OVERDUE", "CONDEMNED")
    assert isinstance(data["inspection_count"], int) and data["inspection_count"] >= 0
    assert isinstance(data["next_inspection_due_date"], str)
    assert data["stored_mass_kg"] == pytest.approx(
        round(data["current_pressure_bar"] * data["water_volume_l"] * KG_PER_L_PER_BAR, 3),
        abs=0.001,
    ), "stored_mass_kg is current pressure times water volume times 0.00008"


def assert_production_asset(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["asset_code"], str) and data["asset_code"]
    assert data["pathway"] in (
        "PEM_ELECTROLYSIS",
        "ALKALINE_ELECTROLYSIS",
        "SMR",
        "SMR_CCS",
    )
    assert data["nameplate_kg_per_day"] > 0
    assert 0 <= data["ccs_capture_rate"] <= 1
    if data["pathway"] != "SMR_CCS":
        assert data["ccs_capture_rate"] == pytest.approx(0), (
            "ccs_capture_rate must be zero unless the pathway is SMR_CCS"
        )
    assert isinstance(data["operator_org"], str) and data["operator_org"]


def assert_power_supply_contract(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["production_asset_id"])
    assert isinstance(data["contract_code"], str) and data["contract_code"]
    assert data["grid_ci_gco2e_per_mwh"] >= 0
    assert 0 <= data["annual_renewable_pct"] <= 100
    assert 0 <= data["hourly_matched_renewable_pct"] <= 100
    assert isinstance(data["hourly_matching_enabled"], bool)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["effective_to"] > data["effective_from"]


def assert_production_lot(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["production_asset_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["mass_kg"] > 0
    assert data["energy_consumed_kwh"] >= 0
    assert data["feedstock_consumed_mmbtu"] >= 0
    assert 0 <= data["carryover_kg"] <= data["mass_kg"]
    assert data["qa_status"] in ("PENDING", "PASSED", "FAILED")
    assert data["ci_status"] in ("PENDING", "CERTIFIED")
    assert data["status"] in ("PRODUCED", "RELEASED", "REJECTED", "CONSUMED")
    assert_decimals(data["ci_provisional_gco2e_per_mj"], 2, "ci_provisional_gco2e_per_mj")
    if data["ci_status"] == "CERTIFIED":
        assert data["ci_certified_gco2e_per_mj"] is not None
        assert_decimals(data["ci_certified_gco2e_per_mj"], 2, "ci_certified_gco2e_per_mj")
        assert data["ci_variant_applied"] in ("ANNUAL_AVERAGE", "HOURLY_MATCHED")
    assert_kg(data["accepted_delivered_kg"], "accepted_delivered_kg")


def assert_purity_test(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    assert is_iso8601_timestamp(data["sampled_at"])
    assert data["verdict"] in ("PASS", "FAIL", "INDETERMINATE")
    assert isinstance(data["failing_analytes"], list)
    assert_pct_3dp(data["purity_margin_pct"], "purity_margin_pct")
    if data["verdict"] == "PASS":
        assert data["failing_analytes"] == [], "a passing test names no failing analyte"


def assert_inventory_ledger_entry(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["reason"] in (
        "OPENING_BALANCE",
        "DELIVERY_RECEIPT",
        "HEEL_RETURNED",
        "BOILOFF_LOSS",
        "DISPENSE_DRAW",
        "METER_CORRECTION",
        "METER_VOID_REVERSAL",
        "INSPECTION_VENT",
    )
    assert_kg(data["delta_kg"], "delta_kg")
    assert_kg(data["resulting_onsite_kg"], "resulting_onsite_kg")
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["source_ref_type"] in (
        "PRESSURE_VESSEL",
        "DELIVERY",
        "DISPENSE_SESSION",
    ), "source_ref_type names the entity kind that caused the movement"


def assert_ledger_replays(entries: List[Dict[str, Any]]) -> None:
    """Sequence numbers start at 1 and the running balance follows each delta."""
    running = 0.0
    for index, entry in enumerate(entries, start=1):
        assert_inventory_ledger_entry(entry)
        assert entry["sequence_no"] == index, (
            f"sequence_no must be a monotonic per-station index starting at 1; "
            f"row {index} carries {entry['sequence_no']}"
        )
        running = round(running + entry["delta_kg"], 3)
        assert entry["resulting_onsite_kg"] == pytest.approx(running, abs=0.001), (
            f"row {index}: resulting_onsite_kg must be the running balance after delta_kg"
        )


def assert_delivery(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["production_lot_id"])
    assert is_valid_uuid(data["receiving_vessel_id"])
    assert data["mode"] in ("TUBE_TRAILER", "LIQUID_TANKER")
    assert data["planned_kg"] > 0
    assert data["status"] in ("SCHEDULED", "ARRIVED", "ACCEPTED", "REJECTED", "QUARANTINED")
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert data["window_end"] > data["window_start"]
    if data["mode"] == "LIQUID_TANKER":
        assert data.get("trailer_water_volume_l") is None
        assert data.get("trailer_final_pressure_bar") is None
    if data["status"] not in ("REJECTED", "QUARANTINED"):
        assert data.get("reject_reason") is None, (
            "reject_reason is null unless the load was refused"
        )


def assert_dispense_session(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert data["vehicle_class"] in ("LIGHT_DUTY", "TRANSIT_BUS", "HEAVY_TRUCK", "FORKLIFT")
    assert data["target_pressure_class"] in ("H35", "H70")
    assert data["fill_protocol"] in ("SAE_J2601_TABLE", "MC_FORMULA")
    assert data["planned_kg"] > 0
    assert -40 <= data["ambient_temp_c"] <= 55
    assert_decimals(data["required_precool_c"], 1, "required_precool_c")
    assert data["fill_status"] in ("PRECOOLING", "FUELING", "COMPLETED", "ABORTED")
    assert data["billing_status"] in ("PENDING", "METERED", "VOIDED")
    assert isinstance(data["cascade_plan"], list)
    assert is_iso8601_timestamp(data["started_at"])
    if data["fill_status"] != "ABORTED":
        assert data.get("abort_reason") is None, (
            "abort_reason is null unless fill_status is ABORTED"
        )
    else:
        assert data["abort_reason"] in ("OPERATOR_ABORT", "STATION_FROZEN")
    if data["fill_status"] == "COMPLETED":
        assert_kg(data["corrected_kg"], "corrected_kg")
        assert_pct_3dp(data["metering_error_pct"], "metering_error_pct")
        assert isinstance(data["metering_within_tolerance"], bool)
        assert data["metering_within_tolerance"] is (
            abs(data["metering_error_pct"]) <= METER_TOLERANCE_PCT
        )


def assert_cascade_plan_shape(plan: List[Dict[str, Any]]) -> None:
    for record in plan:
        assert set(record) >= {"bank_tier", "vessel_id", "kg", "pressure_after_bar"}, (
            "each cascade_plan record carries bank_tier, vessel_id, kg and pressure_after_bar"
        )
        assert record["bank_tier"] in ("HIGH", "MEDIUM", "LOW")
        assert is_valid_uuid(record["vessel_id"])
        assert_kg(record["kg"], "cascade_plan[].kg")
        assert_bar(record["pressure_after_bar"], "cascade_plan[].pressure_after_bar")


def assert_safety_event(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert data["kind"] in (
        "LEAK_DETECTED",
        "VENTILATION_FAULT",
        "COMPRESSOR_FAULT",
        "OVERPRESSURE",
        "SETBACK_BREACH",
    )
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["affected_nozzle_count"], int) and data["affected_nozzle_count"] >= 0
    assert data["detected_by"] in ("SENSOR", "OPERATOR_ROUND", "THIRD_PARTY")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "CLEARED")
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert is_iso8601_timestamp(data["opened_at"])
    if data["status"] == "CLEARED":
        assert is_iso8601_timestamp(data["cleared_at"])
        assert data["cleared_by_user_id"] != data["opened_by_user_id"], (
            "the clearing user must differ from the opening user"
        )
        assert isinstance(data["corrective_action"], str) and data["corrective_action"].strip()


def assert_responder_certification(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["responder_ref"], str) and data["responder_ref"]
    assert data["cert_type"] in ("EMERGENCY_RESPONSE", "HAZMAT_AWARENESS", "CONFINED_SPACE")
    assert data["expires_on"] >= data["valid_from"]
    assert isinstance(data["is_current"], bool)


def assert_incentive_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert data["program"] in ("LCFS", "CFP_OREGON", "CFS_CANADA")
    assert data["period_end"] >= data["period_start"]
    assert isinstance(data["production_lot_ids"], list) and data["production_lot_ids"]
    assert data["status"] in (
        "SUBMITTED",
        "REVISION_REQUESTED",
        "CERTIFIED",
        "CREDITS_ISSUED",
        "DENIED",
    )
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert_kg(data["dispensed_kg"], "dispensed_kg")
    assert_kg(data["energy_mj"], "energy_mj")
    assert_decimals(data["pathway_ci_gco2e_per_mj"], 2, "pathway_ci_gco2e_per_mj")
    assert data["gross_credits_mt"] >= 0, "gross credits are floored at zero"
    assert_kg(data["gross_credits_mt"], "gross_credits_mt")
    assert_kg(data["admin_fee_mt"], "admin_fee_mt")
    assert_kg(data["net_credits_mt"], "net_credits_mt")
    assert data["admin_fee_rate"] in (0.010, 0.020, 0.030)
    assert data["net_credits_mt"] == pytest.approx(
        round(data["gross_credits_mt"] - data["admin_fee_mt"], 3), abs=0.001
    ), "net_credits_mt is gross_credits_mt minus admin_fee_mt"


def assert_uptime_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["funding_agreement_id"])
    assert data["period_end"] > data["period_start"]
    assert isinstance(data["nozzle_count_snapshot"], int) and data["nozzle_count_snapshot"] >= 1
    assert data["status"] in ("DRAFT", "FINAL", "AMENDED")
    for field in (
        "uptime_pct_nozzle_weighted",
        "uptime_pct_station_level",
        "uptime_pct",
        "shortfall_points",
    ):
        assert_pct_3dp(data[field], field)
    assert data["shortfall_points"] >= 0, "shortfall_points is floored at zero"
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0
    if data["status"] == "DRAFT":
        assert data["penalty_cents"] == 0, "a draft charges nothing against the holdback"
    assert data["uptime_pct_station_level"] >= data["uptime_pct_nozzle_weighted"] - 1e-9, (
        "the station-level variant is never lower than the nozzle-weighted variant"
    )


def assert_clock_state(data: Dict[str, Any]) -> None:
    assert is_iso8601_timestamp(data["current_utc"])
    assert isinstance(data["vessels_recomputed"], int) and data["vessels_recomputed"] >= 0
    assert isinstance(data["stations_recomputed"], int) and data["stations_recomputed"] >= 0


# ─── Cross-entity invariants ──────────────────────────────────────────────


def assert_mass_conserved(
    ledger_entries: List[Dict[str, Any]], reasons: List[str], expected_sum: float = 0.0
) -> None:
    """Assert the deltas of the named ledger reasons sum to `expected_sum`."""
    total = round(sum(e["delta_kg"] for e in ledger_entries if e["reason"] in reasons), 3)
    assert total == pytest.approx(expected_sum, abs=0.001), (
        f"deltas for {reasons} must sum to {expected_sum}, got {total}"
    )


def find_ledger_entry(
    entries: List[Dict[str, Any]], reason: str
) -> Optional[Dict[str, Any]]:
    for entry in entries:
        if entry["reason"] == reason:
            return entry
    return None
