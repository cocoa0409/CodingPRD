"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str)
    assert isinstance(data["max_bather_capacity"], int)
    assert data["max_bather_capacity"] >= 1
    assert isinstance(data["lap_lane_count"], int) and data["lap_lane_count"] >= 0
    assert isinstance(data["current_bather_count"], int)
    assert isinstance(data["required_lifeguard_count"], int)
    assert data["operational_status"] in [
        "OPEN", "RESTRICTED", "CLOSED_CHEMISTRY",
        "CLOSED_WEATHER", "CLOSED_STAFFING", "CLOSED_SEASON",
    ]
    assert data["chemistry_state"] in ["IN_RANGE", "WARNING", "OUT_OF_RANGE"]
    assert "chemistry_out_of_range_since" in data


def assert_season(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["season_name"], str)
    assert isinstance(data["resident_pass_price_cents"], int)
    assert isinstance(data["non_resident_pass_price_cents"], int)
    assert isinstance(data["resident_daily_price_cents"], int)
    assert isinstance(data["non_resident_daily_price_cents"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "CLOSED"]


def assert_pass_holder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert data["residency_status"] in ["RESIDENT", "NON_RESIDENT"]
    assert isinstance(data["email"], str)
    assert isinstance(data["strike_count"], int)
    assert "banned_until" in data


def assert_season_pass(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert data["status"] in ["ACTIVE", "REFUNDED", "REVOKED"]


def assert_admission(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["charge_cents"], int)
    assert data["status"] in [
        "ISSUED", "ENTERED", "EXITED", "RAIN_CHECKED", "VOID",
    ]
    assert "entered_at" in data
    assert "exited_at" in data


def assert_lesson_level(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["level_code"], str)
    assert isinstance(data["min_age_years"], int) and data["min_age_years"] >= 0
    assert isinstance(data["capacity_per_session"], int)
    assert data["capacity_per_session"] >= 1
    assert "prerequisite_level_id" in data


def assert_lesson_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lanes_required"], int) and data["lanes_required"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["status"] in [
        "DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    ]


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ENROLLED", "WAITLISTED", "COMPLETED", "DROPPED"]
    assert "waitlist_position" in data


def assert_lifeguard(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certification_id"], str)
    assert data["cert_status"] in ["ACTIVE", "EXPIRED", "SUSPENDED"]


def assert_shift(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "COVERED", "NO_SHOW", "CANCELLED"]


def assert_chemistry_log(data: dict):
    # Immutable record: id + created_at only — no updated_at, no version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ChemistryLog must not carry updated_at"
    assert "version" not in data, "ChemistryLog must not carry version"
    assert data["classification"] in ["IN_RANGE", "WARNING", "OUT_OF_RANGE"]


def assert_lane_allocation(data: dict):
    _assert_common_fields(data)
    assert data["purpose"] in ["LAP_SWIM", "SWIM_TEAM", "LESSON"]
    assert isinstance(data["lane_count"], int) and data["lane_count"] >= 1
    assert data["status"] in ["RESERVED", "RELEASED", "CANCELLED"]


def assert_rental(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["quoted_price_cents"], int)
    assert data["status"] in [
        "REQUESTED", "APPROVED", "CHECKED_IN",
        "COMPLETED", "CANCELLED", "REJECTED",
    ]


def assert_incident_report(data: dict):
    _assert_common_fields(data)
    assert data["incident_type"] in [
        "RESCUE", "FIRST_AID", "RULE_VIOLATION", "EQUIPMENT_FAILURE",
    ]
    assert data["severity"] in ["MINOR", "MODERATE", "MAJOR"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "CONFIRMED", "DISMISSED"]


def assert_closure_event(data: dict):
    _assert_common_fields(data)
    assert data["closure_reason"] in [
        "WEATHER", "CHEMISTRY", "STAFFING_SHORTAGE", "SEASON_END",
    ]
    assert data["rain_check_issuance"] in [
        "FULL_REFUND", "PRO_RATA_CREDIT", "NONE",
    ]
    assert data["status"] in ["ACTIVE", "RESOLVED"]
    assert "ended_at" in data


def assert_bather_count_invariant(before: int, after: int):
    """Enter/exit and check-in/check-out pairs must conserve bather count."""
    assert after == before, (
        f"Bather count invariant violated: before={before}, after={after}"
    )
