"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() functions validate response structure against the
PRD contract using the framework's generic format validators. Field names are
PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_AWARD_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED")
_CLAIM_STATUSES = (
    "SUBMITTED", "DEVELOPMENT", "RATED", "GRANTED", "DENIED", "REMANDED", "CLOSED",
)
_SERVICE_CONNECTIONS = ("PROPOSED", "SERVICE_CONNECTED", "NOT_CONNECTED")
_ENROLLMENT_STATUSES = ("SUBMITTED", "CERTIFIED", "COMPLETED", "CANCELLED")
_VOC_REHAB_STATUSES = ("PROPOSED", "APPROVED", "COMPLETED", "REJECTED")


def assert_veteran(data: dict):
    """Validate a Veteran response (PRD §2.4, §3.1)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["file_number"], str) and len(data["file_number"]) > 0
    assert isinstance(data["total_active_duty_days"], int)
    assert data["total_active_duty_days"] >= 0
    assert isinstance(data["discharged_for_service_disability"], bool)
    assert data["award_status"] in _AWARD_STATUSES
    for f in (
        "combined_rating_pct",
        "provisional_combined_rating_pct",
        "gi_bill_tier_pct",
        "monthly_compensation_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be int"
        assert data[f] >= 0, f"{f} must be non-negative"
    assert data["combined_rating_pct"] in range(0, 101)
    assert data["gi_bill_tier_pct"] in (0, 50, 60, 70, 80, 90, 100)


def assert_claim(data: dict):
    """Validate a Claim response (PRD §3.3)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert is_valid_uuid(data["veteran_id"]), "veteran_id must be UUID"
    assert data["claim_type"] in ("ORIGINAL", "INCREASE", "SECONDARY")
    assert data["status"] in _CLAIM_STATUSES
    assert isinstance(data["remand_count"], int) and data["remand_count"] >= 0


def assert_condition(data: dict):
    """Validate a Condition response (PRD §3.3)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int), "version must be int"
    assert is_valid_uuid(data["veteran_id"]), "veteran_id must be UUID"
    assert is_valid_uuid(data["claim_id"]), "claim_id must be UUID"
    assert isinstance(data["diagnostic_code"], str)
    assert data["body_side"] in ("LEFT", "RIGHT", "NONE")
    assert isinstance(data["is_extremity"], bool)
    assert data["proposed_rating_pct"] % 10 == 0
    assert 0 <= data["proposed_rating_pct"] <= 100
    assert isinstance(data["final_rating_pct"], int)
    assert data["service_connection"] in _SERVICE_CONNECTIONS


def assert_dependent(data: dict):
    """Validate a Dependent response (PRD §2.4: id + created_at only, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert data["relationship"] in ("SPOUSE", "CHILD", "PARENT")
    assert data["status"] in ("ACTIVE", "REMOVED")
    assert "version" not in data, "Dependent must not carry a version field (PRD §2.4)"
    assert "updated_at" not in data, "Dependent must not carry updated_at (PRD §2.4)"


def assert_school(data: dict):
    """Validate a School response (PRD §3.11)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["is_public"], bool)
    assert isinstance(data["monthly_housing_rate_cents"], int)
    assert data["monthly_housing_rate_cents"] >= 0
    assert isinstance(data["yellow_ribbon_participant"], bool)
    assert isinstance(data["yellow_ribbon_slots_used"], int)
    assert data["yellow_ribbon_slots_used"] >= 0


def assert_enrollment(data: dict):
    """Validate an Enrollment response (PRD §3.11)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int), "version must be int"
    assert is_valid_uuid(data["veteran_id"]), "veteran_id must be UUID"
    assert is_valid_uuid(data["school_id"]), "school_id must be UUID"
    assert data["status"] in _ENROLLMENT_STATUSES
    for f in (
        "rate_of_pursuit_pct",
        "monthly_housing_allowance_cents",
        "estimated_mha_cents",
        "yellow_ribbon_match_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be int"
        assert data[f] >= 0, f"{f} must be non-negative"


def assert_voc_rehab_plan(data: dict):
    """Validate a VocRehabPlan response (PRD §3.14)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int), "version must be int"
    assert is_valid_uuid(data["veteran_id"]), "veteran_id must be UUID"
    assert data["track"] in (
        "REEMPLOYMENT", "EMPLOYMENT_THROUGH_LONG_TERM", "SELF_EMPLOYMENT",
    )
    assert data["status"] in _VOC_REHAB_STATUSES
