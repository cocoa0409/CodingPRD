"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common(data: dict):
    """id + created_at present and well-formed for every entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_common_full(data: dict):
    """Full common quartet for mutable entities."""
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_property(data: dict):
    _assert_common_full(data)
    assert isinstance(data["street_address"], str) and len(data["street_address"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["year_built"], int)
    assert isinstance(data["square_footage"], int) and data["square_footage"] > 0
    assert data["construction_type"] in ("FRAME", "MASONRY", "FIRE_RESISTIVE")
    assert isinstance(data["roof_age_years"], int) and data["roof_age_years"] >= 0
    assert isinstance(data["stories"], int) and data["stories"] >= 1
    assert isinstance(data["replacement_cost"], (int, float))
    assert isinstance(data["total_insured_value"], (int, float))
    assert data["estimate_variant"] in ("COMPONENT", "SQFT_BLEND", "NONE")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_risk_assessment(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be UUID"
    assert 0 <= data["wildfire_fuel_density"] <= 100
    assert 0 <= data["slope_grade_pct"] <= 100
    assert data["defensible_space_ft"] >= 0
    assert data["flood_zone"] in ("X", "A", "AE", "VE")
    assert data["distance_to_coast_mi"] >= 0
    assert isinstance(data["wildfire_score"], int)
    assert 0 <= data["wildfire_score"] <= 100
    assert data["wind_hail_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert data["score_stage"] in ("PROVISIONAL", "FINAL")


def assert_inspector(data: dict):
    _assert_common_full(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_state"], str)
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_inspection(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("property_id", ""))
    assert is_valid_uuid(data.get("inspector_id", ""))
    assert isinstance(data["window_start"], int)
    assert isinstance(data["window_end"], int)
    assert data["window_end"] > data["window_start"]
    for f in ("roof_ok", "electrical_ok", "plumbing_ok", "hvac_ok"):
        assert isinstance(data[f], bool)
    assert isinstance(data["passed_count"], int) and 0 <= data["passed_count"] <= 4
    assert data["status"] in ("SCHEDULED", "COMPLETED", "PASSED", "FAILED")


def assert_application(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("property_id", ""))
    assert isinstance(data["agent_id"], str)
    assert isinstance(data["requested_coverage_a"], (int, float))
    assert data["wind_hail_deductible_pct"] in (1, 2, 5)
    assert isinstance(data["quoted_premium"], (int, float))
    assert data["decline_reason"] in ("WILDFIRE_UNINSURABLE", "INSPECTION_FAILED", "NONE")
    assert data["assigned_underwriter_id"] is None or is_valid_uuid(data["assigned_underwriter_id"])
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "BOUND", "DECLINED")


def assert_endorsement(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["kind"] in ("PERIL_ADD", "EXCLUSION")
    assert data["peril_code"] in (
        "WATER_BACKUP", "SCREENED_ENCLOSURE", "ORDINANCE_LAW", "EARTH_MOVEMENT", "MOLD"
    )
    assert isinstance(data["coverage_limit"], (int, float)) and data["coverage_limit"] >= 0
    assert isinstance(data["premium_delta"], (int, float))
    assert data["status"] in ("DRAFT", "PENDING", "APPLIED", "REJECTED", "REMOVED")


def assert_quote(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("application_id", ""))
    for f in ("base_premium", "endorsement_premium", "annual_premium", "wind_hail_deductible_amount"):
        assert isinstance(data[f], (int, float))
        assert_cost_precision(data[f])
    assert data["status"] in ("BOUND_OFFER", "SUPERSEDED")


def assert_policy(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("property_id", ""))
    assert isinstance(data["effective_date"], int)
    assert isinstance(data["expiration_date"], int)
    assert data["expiration_date"] > data["effective_date"]
    assert isinstance(data["annual_premium"], (int, float))
    assert isinstance(data["premium_balance"], (int, float))
    assert_cost_precision(data["premium_balance"])
    assert isinstance(data["lapse_count"], int) and data["lapse_count"] >= 0
    assert data["status"] in ("PENDING_PAYMENT", "ACTIVE", "LAPSED", "REINSTATED", "CANCELLED")


def assert_payment(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("policy_id", ""))
    assert data["purpose"] in ("BINDING", "REINSTATEMENT")
    assert isinstance(data["amount"], (int, float)) and data["amount"] > 0
    assert data["status"] == "SETTLED"


def assert_underwriter(data: dict):
    """Underwriter is immutable after creation: id + created_at only,
    NO updated_at, NO version (PRD §2.4)."""
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["authority_limit"], (int, float)) and data["authority_limit"] > 0
    assert "updated_at" not in data, "Underwriter must NOT carry updated_at"
    assert "version" not in data, "Underwriter must NOT carry version"


def assert_tiv_conserved(prop: dict):
    """total_insured_value is never negative and is at two-decimal precision."""
    assert prop["total_insured_value"] >= 0
    assert_cost_precision(prop["total_insured_value"])
