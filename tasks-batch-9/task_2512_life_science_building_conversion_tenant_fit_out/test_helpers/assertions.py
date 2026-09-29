"""Per-entity response assertions and the two conservation identities."""

from typing import Dict, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import control_areas_for_floor, percent_maq_for_floor

MONEY_TOLERANCE = 0.01
SCORE_TOLERANCE = 0.05
RATIO_TOLERANCE = 0.00005


# ---------------------------------------------------------------------------
# Shared server-managed properties
# ---------------------------------------------------------------------------


def assert_common_fields(data: Dict) -> None:
    """`id`, `created_at`, `updated_at` and `version` on every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert "-" in str(data.get("id", "")), "id carries no type prefix"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_freshly_created(data: Dict) -> None:
    """A record just created: version 1 and updated_at equal to created_at."""
    assert_common_fields(data)
    assert data["version"] == 1, f"version begins at 1, got {data['version']}"
    assert (
        data["updated_at"] == data["created_at"]
    ), "updated_at equals created_at immediately after creation"


def assert_money(actual, expected: float, label: str = "amount") -> None:
    """Compare a monetary, gallon, airflow or percentage figure at two places."""
    assert actual == pytest.approx(
        expected, abs=MONEY_TOLERANCE
    ), f"{label}: expected {expected}, got {actual}"


def assert_score(actual, expected: float) -> None:
    """Compare a suitability score, which is carried to one decimal place."""
    assert actual == pytest.approx(
        expected, abs=SCORE_TOLERANCE
    ), f"suitability_score: expected {expected}, got {actual}"


def assert_ratio(actual, expected: float) -> None:
    """Compare the utility headroom ratio, carried to four decimal places."""
    assert actual == pytest.approx(
        expected, abs=RATIO_TOLERANCE
    ), f"utility_headroom_ratio: expected {expected}, got {actual}"


def assert_version_bumped_by(before: Dict, after: Dict, expected_delta: int = 1) -> None:
    """A mutation, direct or cascaded, raises `version` by exactly the delta."""
    assert after["version"] == before["version"] + expected_delta, (
        f"version should move {before['version']} -> "
        f"{before['version'] + expected_delta}, got {after['version']}"
    )


def assert_version_unchanged(before: Dict, after: Dict) -> None:
    """A record the request did not change keeps its `version`."""
    assert (
        after["version"] == before["version"]
    ), f"version should stay {before['version']}, got {after['version']}"
    assert (
        after["updated_at"] == before["updated_at"]
    ), "updated_at must not be refreshed on an unchanged record"


# ---------------------------------------------------------------------------
# The two conservation identities
# ---------------------------------------------------------------------------


def assert_ledger_identity(lease: Dict) -> None:
    """`ti_authorized_usd` equals uncommitted plus committed plus disbursed plus forfeited."""
    total = (
        lease["ti_uncommitted_usd"]
        + lease["ti_committed_usd"]
        + lease["ti_disbursed_usd"]
        + lease["ti_forfeited_usd"]
    )
    assert lease["ti_authorized_usd"] == pytest.approx(total, abs=MONEY_TOLERANCE), (
        f"ledger identity broken: authorized {lease['ti_authorized_usd']} != "
        f"uncommitted {lease['ti_uncommitted_usd']} + committed {lease['ti_committed_usd']}"
        f" + disbursed {lease['ti_disbursed_usd']} + forfeited {lease['ti_forfeited_usd']}"
    )


def assert_capacity_pool_identity(building: Dict) -> None:
    """Each pool total equals available plus reserved plus committed."""
    exhaust = (
        building["exhaust_available_cfm"]
        + building["exhaust_reserved_cfm"]
        + building["exhaust_committed_cfm"]
    )
    assert building["exhaust_capacity_total_cfm"] == pytest.approx(
        exhaust, abs=MONEY_TOLERANCE
    ), (
        f"exhaust identity broken: total {building['exhaust_capacity_total_cfm']} != "
        f"available {building['exhaust_available_cfm']} + reserved "
        f"{building['exhaust_reserved_cfm']} + committed {building['exhaust_committed_cfm']}"
    )
    power = (
        building["power_available_kw"]
        + building["power_reserved_kw"]
        + building["power_committed_kw"]
    )
    assert building["power_capacity_total_kw"] == pytest.approx(
        power, abs=MONEY_TOLERANCE
    ), (
        f"power identity broken: total {building['power_capacity_total_kw']} != "
        f"available {building['power_available_kw']} + reserved "
        f"{building['power_reserved_kw']} + committed {building['power_committed_kw']}"
    )


def assert_pools_restored(before: Dict, after: Dict) -> None:
    """Releasing capacity returns the pools to exactly their prior value."""
    for field in (
        "exhaust_capacity_total_cfm",
        "exhaust_available_cfm",
        "exhaust_reserved_cfm",
        "exhaust_committed_cfm",
        "power_capacity_total_kw",
        "power_available_kw",
        "power_reserved_kw",
        "power_committed_kw",
    ):
        assert after[field] == pytest.approx(
            before[field], abs=MONEY_TOLERANCE
        ), f"{field} drifted: {before[field]} -> {after[field]}"
    assert_capacity_pool_identity(after)


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_building(data: Dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address_city"], str) and data["address_city"]
    assert data["occupancy_status"] in (
        "VACANT",
        "PARTIALLY_OCCUPIED",
        "FULLY_OCCUPIED",
    )
    assert data["published_vibration_class"] in ("VC_A", "VC_B", "VC_C", "VC_D", "VC_E")
    assert data["published_floor_to_floor_ft"] > 0
    assert data["published_live_load_psf"] > 0
    assert data["exhaust_riser_capacity_cfm"] >= 0
    assert data["emergency_power_capacity_kw"] >= 0
    assert data["chilled_water_capacity_tons"] >= 0
    assert data["suitability_state"] in (
        "DRAFT",
        "ASSESSING",
        "ASSESSED_SUITABLE",
        "ASSESSED_CONDITIONAL",
        "ASSESSED_UNSUITABLE",
        "CONVERSION_APPROVED",
        "CONVERSION_COMPLETE",
    )
    assert data["latest_assessment_verdict"] in (
        None,
        "SUITABLE",
        "SUITABLE_WITH_CONVERSION",
        "UNSUITABLE",
    )
    assert isinstance(data["scope_disciplines_covered"], list)
    assert isinstance(data["scope_disciplines_complete"], list)
    assert data["scope_disciplines_covered"] == sorted(data["scope_disciplines_covered"])
    assert data["scope_disciplines_complete"] == sorted(
        data["scope_disciplines_complete"]
    )
    assert_capacity_pool_identity(data)


def assert_floor(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["building_id"])
    assert isinstance(data["floor_number"], int) and data["floor_number"] >= 1
    assert data["floor_to_floor_ft"] > 0
    assert data["live_load_psf"] > 0
    assert data["vibration_class"] in ("VC_A", "VC_B", "VC_C", "VC_D", "VC_E")
    assert isinstance(data["sprinklered"], bool)
    assert data["control_areas_allowed"] == control_areas_for_floor(
        data["floor_number"]
    ), "control_areas_allowed is derived from floor_number alone"
    # The percentage may be carried either as a whole percentage or as the
    # equivalent fraction; both readings must place the plate in the band its
    # floor number selects.
    band_percent = percent_maq_for_floor(data["floor_number"])
    assert data["percent_maq"] == pytest.approx(
        band_percent, abs=MONEY_TOLERANCE
    ) or data["percent_maq"] == pytest.approx(
        band_percent / 100.0, abs=0.0001
    ), f"percent_maq {data['percent_maq']} is outside the band for floor {data['floor_number']}"


def assert_assessment(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["building_id"])
    assert data["assessment_basis"] in ("SCREENING", "INVESTIGATION")
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED")
    assert data["required_vibration_class"] in ("VC_A", "VC_B", "VC_C", "VC_D", "VC_E")
    assert data["required_exhaust_cfm"] > 0
    assert data["required_power_kw"] > 0
    for credit in ("height_credit", "structural_credit", "vibration_credit", "utility_credit"):
        assert data[credit] in (0, 60, 100), f"{credit} must be 100, 60 or 0"
    assert isinstance(data["hard_fail_capped"], bool)
    if data["status"] == "DRAFT":
        assert data["verdict"] is None, "verdict stays null while the assessment is DRAFT"
    else:
        assert data["verdict"] in (
            "SUITABLE",
            "SUITABLE_WITH_CONVERSION",
            "UNSUITABLE",
        )
        assert_verdict_follows_score(data)


def assert_verdict_follows_score(data: Dict) -> None:
    """`verdict` follows from the final score alone."""
    score = data["suitability_score"]
    if score >= 75.0:
        expected = "SUITABLE"
    elif score >= 50.0:
        expected = "SUITABLE_WITH_CONVERSION"
    else:
        expected = "UNSUITABLE"
    assert (
        data["verdict"] == expected
    ), f"score {score} implies verdict {expected}, got {data['verdict']}"


def assert_scope_item(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["building_id"])
    assert data["discipline"] in (
        "LAB_EXHAUST",
        "EMERGENCY_POWER",
        "CHEMICAL_STORAGE",
        "WASTE_HANDLING",
    )
    assert data["status"] in ("PLANNED", "COMPLETE")
    assert data["budget_usd"] >= 0
    assert data["capacity_delta_cfm"] >= 0
    assert data["capacity_delta_kw"] >= 0
    if data["status"] == "PLANNED":
        assert data["completed_at"] is None
    else:
        assert is_iso8601_timestamp(data["completed_at"])


def assert_amenity(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["building_id"])
    assert data["amenity_type"] in (
        "GLASSWASH",
        "AUTOCLAVE",
        "NMR_SUITE",
        "CONFERENCE",
        "LOADING_DOCK",
    )
    assert data["serving_floor_number"] >= 1
    assert data["concurrent_capacity"] >= 1
    assert isinstance(data["vibration_sensitive"], bool)
    assert data["utility_draw_kw"] >= 0


def assert_tenant(data: Dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["research_type"] in (
        "BSL2_BIOLOGY",
        "CHEMISTRY_SYNTHESIS",
        "VIVARIUM",
        "ANALYTICAL_QC",
    )
    assert data["credit_tier"] in (
        "INVESTMENT_GRADE",
        "VENTURE_BACKED",
        "EARLY_STAGE",
    )
    assert data["lab_premium_psf"] > 0
    scripts = data["required_commissioning_scripts"]
    assert isinstance(scripts, list) and scripts
    assert scripts == sorted(scripts), "required_commissioning_scripts is sorted ascending"


def assert_lease(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["tenant_id"])
    assert is_valid_uuid(data["building_id"])
    assert is_valid_uuid(data["premises_floor_id"])
    assert data["rentable_sf"] > 0
    assert data["term_months"] >= 12
    assert data["base_rent_psf"] > 0
    assert data["status"] in (
        "LOI",
        "NEGOTIATING",
        "COUNTER_PENDING",
        "TERMS_ACCEPTED",
        "EXECUTED",
        "ACTIVE",
        "EXPIRING",
        "SURRENDERED",
    )
    assert data["negotiation_round_count"] >= 0
    assert_ledger_identity(data)


def assert_proposal(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    assert data["round_number"] >= 1
    assert data["proposed_by"] in ("LANDLORD", "TENANT")
    assert data["proposed_allowance_psf"] >= 0
    assert data["status"] in ("OPEN", "COUNTERED", "EXPIRED", "ACCEPTED")
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]


def assert_project(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["floor_id"])
    assert data["design_exhaust_cfm"] > 0
    assert data["design_power_kw"] > 0
    assert data["permit_status"] in ("P_UNPERMITTED", "P_APPLIED", "P_ISSUED")
    assert data["construction_status"] in (
        "C_NOT_STARTED",
        "C_IN_PROGRESS",
        "C_SUSPENDED",
        "C_SUBSTANTIAL_COMPLETION",
        "C_ACCEPTED",
    )
    assert data["delivery_risk"] in ("ON_TRACK", "AT_RISK")
    assert isinstance(data["required_commissioning_scripts"], list)
    assert data["passed_script_count"] >= 0
    assert data["passed_script_count"] <= len(data["required_commissioning_scripts"])


def assert_phase(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["sequence_no"] >= 1
    assert data["premium_class"] in ("SHELL", "LAB_MEP", "VIVARIUM", "CLEANROOM")
    assert data["work_class"] in ("QUIET", "VIBRATION_GENERATING", "SHUTDOWN_REQUIRED")
    assert data["hard_cost_usd"] > 0
    assert data["restoration_cost_usd"] >= 0
    assert data["status"] in (
        "DRAFT",
        "SCHEDULED",
        "VIBRATION_HOLD",
        "BLOCKED",
        "IN_PROGRESS",
        "COMPLETE",
    )
    assert data["ti_eligible_usd"] >= 0
    assert data["ti_committed_usd"] >= 0
    assert data["ti_disbursed_usd"] >= 0
    assert data["ti_disbursed_usd"] <= data["ti_committed_usd"] + MONEY_TOLERANCE
    if data["work_class"] == "SHUTDOWN_REQUIRED":
        assert data["affected_amenity_id"] is not None


def assert_reservation(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["building_id"]), "building_id is denormalised at creation"
    assert data["exhaust_cfm"] > 0
    assert data["power_kw"] > 0
    assert data["status"] in ("RESERVED", "CANCELLED", "COMMITTED", "RELEASED")


def assert_hazmat_permit(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["floor_id"])
    assert data["hazard_class"] in (
        "FLAMMABLE_IB",
        "FLAMMABLE_II",
        "CORROSIVE",
        "OXIDIZER_2",
    )
    assert data["use_condition"] in (
        "STORAGE_CABINET",
        "CLOSED_SYSTEM_USE",
        "OPEN_SYSTEM_USE",
    )
    assert data["quantity_gal"] > 0
    assert data["control_area_index"] >= 1
    assert data["allowance_per_control_area_gal"] > 0
    assert data["aggregate_allowance_gal"] >= data["allowance_per_control_area_gal"]
    assert data["status"] in (
        "REQUESTED",
        "APPROVED",
        "DENIED",
        "ACTIVE",
        "REVOKED",
        "SURRENDERED",
    )


def assert_allocation(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["amenity_id"])
    assert is_valid_uuid(data["project_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_start"] < data["window_end"]
    assert data["headcount"] >= 1
    assert data["status"] in ("REQUESTED", "CONFIRMED", "CANCELLED", "PREEMPTED")


def assert_commissioning_record(data: Dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["script_type"] in (
        "IQ",
        "OQ",
        "PQ",
        "EXHAUST_AIRFLOW",
        "EPSS_LOAD_TEST",
        "CONTAINMENT_VERIFICATION",
    )
    assert isinstance(data["executed_by_user_id"], str) and data["executed_by_user_id"]
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED")
    if data["status"] == "SCHEDULED":
        assert data["result"] is None
        assert data["witnessed_by_user_id"] is None
    else:
        assert data["result"] in ("PASS", "FAIL")
        assert data["witnessed_by_user_id"] != data["executed_by_user_id"]


def assert_utilization_report(
    data: Dict,
    floor_id: Optional[str] = None,
    hazard_class: Optional[str] = None,
) -> None:
    """The report echoes both numerators and both denominators."""
    for field in (
        "floor_id",
        "hazard_class",
        "control_area_index",
        "control_areas_allowed",
        "allowance_per_control_area_gal",
        "aggregate_allowance_gal",
        "per_control_area_basis_gal",
        "per_control_area_utilization_pct",
        "aggregate_basis_gal",
        "aggregate_utilization_pct",
    ):
        assert field in data, f"utilisation report must echo {field}"
    if floor_id is not None:
        assert data["floor_id"] == floor_id
    if hazard_class is not None:
        assert data["hazard_class"] == hazard_class
    assert data["control_area_index"] >= 1
    assert data["control_area_index"] <= data["control_areas_allowed"]
    assert_money(
        data["aggregate_allowance_gal"],
        data["allowance_per_control_area_gal"] * data["control_areas_allowed"],
        "aggregate_allowance_gal",
    )
