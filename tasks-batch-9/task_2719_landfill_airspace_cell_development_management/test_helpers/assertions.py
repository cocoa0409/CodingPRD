"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

MONEY = 0.005
DENSITY = 0.00005


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 instants by value, not by rendered fractional width."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_common_fields(data: dict, expected_version: Optional[int] = None) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC with three fractional digits: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC with three fractional digits: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_money(value, label: str = "amount") -> None:
    assert value is not None, f"{label} must not be null"
    assert_cost_precision(float(value), 2)


def assert_amount(actual, expected, label: str = "amount") -> None:
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(float(expected), abs=MONEY), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_density(actual, expected, label: str = "density") -> None:
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(float(expected), abs=DENSITY), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_landfill(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["permit_number"], str) and 1 <= len(data["permit_number"]) <= 40
    assert float(data["permitted_total_airspace_cy"]) > 0
    assert float(data["design_footprint_sf"]) > 0
    assert 0.40 <= float(data["planned_density_tons_per_cy"]) <= 1.20
    assert float(data["annual_tonnage_forecast"]) > 0
    assert 1 <= int(data["daily_load_limit"]) <= 2000
    assert data["operating_status"] in (
        "OPEN",
        "RESTRICTED_AIRSPACE",
        "SUSPENDED_NO_AIRSPACE",
        "SUSPENDED_FINANCIAL",
        "CLOSED",
    )
    assert data["gas_collection_status"] in ("COMPLIANT", "CORRECTIVE_ACTION")
    assert data["financial_assurance_status"] in (
        "UNFUNDED",
        "FUNDED",
        "SHORTFALL_REVIEW",
        "LAPSED",
    )
    assert_money(data["assurance_funded_amount"], "assurance_funded_amount")
    assert_money(data["remaining_airspace_cy"], "remaining_airspace_cy")
    assert_money(data["remaining_life_years"], "remaining_life_years")
    assert int(data["active_cell_count"]) >= 0


def assert_landfill_ledger(data: dict) -> None:
    """remaining_airspace_cy is the certified figure minus the consumed figure."""
    expected = round(
        float(data["certified_airspace_cy"]) - float(data["consumed_airspace_cy"]), 2
    )
    assert_amount(data["remaining_airspace_cy"], expected, "remaining_airspace_cy")


def assert_cell(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["landfill_id"])
    assert isinstance(data["cell_code"], str) and 1 <= len(data["cell_code"]) <= 20
    assert float(data["design_airspace_cy"]) > 0
    assert float(data["design_area_sf"]) > 0
    assert data["liner_type"] in ("SINGLE_COMPOSITE", "DOUBLE_COMPOSITE", "GCL_ONLY")
    assert data["status"] in (
        "DESIGN",
        "UNDER_CONSTRUCTION",
        "QA_REVIEW",
        "QA_CERTIFIED",
        "READY_FOR_WASTE",
        "ACTIVE",
        "FULL",
        "CLOSED",
        "REJECTED",
    )
    assert_money(data["consumed_airspace_cy"], "consumed_airspace_cy")
    assert_money(data["fill_pct"], "fill_pct")


def assert_cell_fill(data: dict) -> None:
    """fill_pct is one hundred times consumed over design, to 2 decimal places."""
    expected = round(
        100.0 * float(data["consumed_airspace_cy"]) / float(data["design_airspace_cy"]), 2
    )
    assert_amount(data["fill_pct"], expected, "fill_pct")


def assert_liner_qa_package(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["cell_id"])
    assert float(data["seam_length_ft"]) > 0
    assert int(data["destructive_test_count"]) >= 1
    assert 0 <= int(data["passing_test_count"]) <= int(data["destructive_test_count"])
    assert int(data["panel_count"]) >= 1
    assert int(data["defect_count"]) >= 0
    assert 0.0 <= float(data["qa_conformance_score"]) <= 100.0
    assert_money(data["qa_conformance_score"], "qa_conformance_score")
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "RETURNED", "APPROVED", "REJECTED")
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert 1 <= int(data["revision_round"]) <= 3


def assert_aerial_survey(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["landfill_id"])
    assert is_iso8601_timestamp(data["flown_on"])
    assert parse_instant(data["coverage_period_start"]) <= parse_instant(
        data["coverage_period_end"]
    )
    assert float(data["measured_remaining_airspace_cy"]) >= 0
    assert float(data["tons_placed_in_period"]) > 0
    assert_money(data["airspace_consumed_in_period_cy"], "airspace_consumed_in_period_cy")
    assert_cost_precision(float(data["measured_density_tons_per_cy"]), 4)
    assert data["status"] in ("RECORDED", "SUPERSEDED", "VOID")


def assert_operating_day(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["landfill_id"])
    assert is_valid_uuid(data["active_cell_id"])
    assert float(data["working_face_area_sf"]) > 0
    assert data["cover_material_type"] in (
        "SOIL_6IN",
        "ALTERNATIVE_TARP",
        "ADC_FOAM",
        "AUTO_SHRED_FINES",
    )
    assert data["status"] in ("OPEN", "CLOSED", "AMENDED")
    assert_money(data["tons_placed"], "tons_placed")
    assert_money(data["airspace_consumed_cy"], "airspace_consumed_cy")
    assert_cost_precision(float(data["effective_density_tons_per_cy"]), 4)


def assert_waste_load(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["operating_day_id"])
    assert isinstance(data["hauler_ref"], str) and 1 <= len(data["hauler_ref"]) <= 40
    assert data["waste_stream"] in ("MSW", "CD", "INDUSTRIAL_SPECIAL", "ASBESTOS_SPECIAL")
    assert float(data["manifest_tons"]) > 0
    assert data["load_check_result"] in ("PASS", "PROHIBITED_FOUND", "UNMANIFESTED")
    assert data["screening_status"] in ("PENDING", "FLAGGED", "CLEARED", "REJECTED")
    assert data["billing_status"] in ("UNBILLED", "PROVISIONAL", "FINALIZED", "VOID")
    for field in ("gate_charge_amount", "host_royalty_amount", "final_charge_amount"):
        if data.get(field) is not None:
            assert_money(data[field], field)


def assert_special_waste_approval(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["landfill_id"])
    assert isinstance(data["generator_name"], str) and 1 <= len(data["generator_name"]) <= 120
    assert isinstance(data["waste_code"], str) and 1 <= len(data["waste_code"]) <= 30
    assert data["profile_stream"] in ("INDUSTRIAL_SPECIAL", "ASBESTOS_SPECIAL")
    assert float(data["approved_tons_cap"]) > 0
    assert parse_instant(data["effective_from"]) < parse_instant(data["expires_on"])
    assert_money(data["consumed_tons"], "consumed_tons")
    assert data["status"] in (
        "REQUESTED",
        "APPROVED",
        "DENIED",
        "REVOKED",
        "SUSPENDED",
        "EXHAUSTED",
    )


def assert_treatment_agreement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["landfill_id"])
    assert isinstance(data["facility_name"], str) and 1 <= len(data["facility_name"]) <= 120
    assert float(data["daily_gallon_cap"]) > 0
    assert float(data["base_haul_fee"]) >= 0
    assert float(data["treatment_rate_per_kgal"]) > 0
    assert 1 <= int(data["concurrent_slot_capacity"]) <= 10
    assert parse_instant(data["effective_from"]) < parse_instant(data["expires_on"])
    assert float(data["scheduled_gallons_today"]) >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")


def assert_leachate_shipment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["treatment_agreement_id"])
    assert float(data["gallons"]) > 0
    assert parse_instant(data["window_start"]) < parse_instant(data["window_end"])
    assert_money(data["treatment_fee"], "treatment_fee")
    assert float(data["surcharge_pct"]) in (0.00, 0.06, 0.10)
    if data.get("invoice_total") is not None:
        assert_money(data["invoice_total"], "invoice_total")
    assert data["status"] in (
        "SCHEDULED",
        "DISPATCHED",
        "ACCEPTED",
        "REJECTED_AT_GATE",
        "CANCELLED",
    )


def assert_gas_well(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["cell_id"])
    assert isinstance(data["well_code"], str) and 1 <= len(data["well_code"]) <= 20
    assert float(data["depth_ft"]) > 0
    assert data["status"] in (
        "DRILLED",
        "CONNECTED",
        "ONLINE",
        "TUNING_REQUIRED",
        "OFFLINE",
        "ABANDONED",
    )


def assert_surface_emission_scan(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["landfill_id"])
    assert int(data["grid_points_count"]) >= 1
    assert float(data["max_reading_ppm"]) >= 0
    assert data["status"] in ("PASSED", "EXCEEDANCE_OPEN", "RESOLVED")


def assert_closure_cost_estimate(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["landfill_id"])
    assert 2000 <= int(data["estimate_year"]) <= 2100
    assert float(data["closure_unit_cost_per_sf"]) > 0
    assert float(data["post_closure_annual_cost"]) > 0
    assert 0 <= float(data["inflation_pct"]) <= 0.20
    assert 1 <= int(data["post_closure_years"]) <= 60
    for field in (
        "closure_cost_total",
        "post_closure_cost_total",
        "required_assurance_amount",
        "funding_shortfall",
    ):
        assert_money(data[field], field)
    assert float(data["funding_shortfall"]) >= 0
    assert data["status"] in ("DRAFT", "CERTIFIED", "STALE", "SUPERSEDED")


def assert_estimate_totals_consistent(data: dict) -> None:
    """required_assurance_amount is the sum of the two cost totals."""
    expected = round(
        float(data["closure_cost_total"]) + float(data["post_closure_cost_total"]), 2
    )
    assert_amount(data["required_assurance_amount"], expected, "required_assurance_amount")


def assert_host_community_agreement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["landfill_id"])
    assert isinstance(data["community_name"], str) and 1 <= len(data["community_name"]) <= 120
    assert float(data["posted_tipping_fee_per_ton"]) > 0
    assert float(data["host_fee_per_ton"]) >= 0
    assert float(data["tier1_monthly_tons"]) > 0
    assert 0 <= float(data["royalty_tier1_pct"]) <= 0.50
    assert 0 <= float(data["royalty_tier2_pct"]) <= 0.50
    assert float(data["minimum_annual_payment"]) >= 0
    assert parse_instant(data["effective_from"]) < parse_instant(data["expires_on"])
    assert data["status"] in ("DRAFT", "EXECUTED", "UNDER_AMENDMENT", "TERMINATED")
    assert int(data["amendment_round"]) >= 0


def assert_remaining_life_projection(data: dict) -> None:
    assert is_valid_uuid(data["landfill_id"])
    assert data["variant"] in ("survey_based", "ledger_based")
    assert_money(data["remaining_airspace_cy"], "remaining_airspace_cy")
    assert float(data["annual_tonnage_forecast"]) > 0
    assert_money(data["remaining_life_years"], "remaining_life_years")
    if data["variant"] == "ledger_based":
        assert data["source_survey_id"] is None, "ledger_based reports a null source survey"
    else:
        assert is_valid_uuid(data["source_survey_id"] or "")


def assert_projection_arithmetic(data: dict) -> None:
    """The projection is remaining airspace floored at zero, times density, over forecast."""
    remaining = max(0.0, float(data["remaining_airspace_cy"]))
    expected = round(
        remaining * float(data["density_tons_per_cy"]) / float(data["annual_tonnage_forecast"]), 2
    )
    assert_amount(data["remaining_life_years"], expected, "remaining_life_years")


def assert_error_envelope_only(body: dict) -> None:
    """An error body carries only error_id and message inside data."""
    assert body.get("response_type") == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error data must carry only error_id and message, got {sorted(body['data'])}"
    )
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
