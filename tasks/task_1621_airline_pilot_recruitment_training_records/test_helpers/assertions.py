"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. CostLedgerEntry is append-only and must
NOT expose updated_at/version (PRD resource identity section).
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Assert two timestamps denote the same instant regardless of whether
    fractional digits are rendered."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601 UTC")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601 UTC")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}")


def assert_applicant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["total_flight_hours"], int)
    assert data["status"] in (
        "SCREENING", "PRIA_PENDING", "PRIA_VERIFIED", "CLEARED",
        "REJECTED", "WITHDRAWN")
    assert data["seniority_number"] is None or isinstance(data["seniority_number"], int)
    assert data["current_equipment_id"] is None or isinstance(
        data["current_equipment_id"], str)
    assert data["cleared_at"] is None or is_iso8601_timestamp(data["cleared_at"])
    assert isinstance(data["ledger_balance_cents"], int)


def assert_records_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["applicant_id"], str)
    assert data["request_type"] in ("PRIA", "DRUG_TEST", "TRAINING_HISTORY")
    assert data["status"] in (
        "DRAFT", "SENT", "RECEIVED", "VERIFIED", "FAILED", "EXPIRED")


def assert_equipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["simulator_cost_per_hour_cents"], int)
    assert isinstance(data["ioe_hours_required"], int)
    assert isinstance(data["landings_required_90d"], int)


def assert_training_class(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["equipment_id"], str)
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert 0 <= data["base_attrition_rate"] <= 0.9
    assert data["status"] in (
        "SCHEDULED", "OPEN", "IN_SESSION", "COMPLETED", "CANCELLED")
    for field in ("active_enrollment_count", "confirmed_count",
                  "max_seats_sellable", "projected_completions_aggregate",
                  "projected_completions_walk"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["over_committed"], bool)


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["training_class_id"], str)
    assert data["status"] in (
        "TENTATIVE", "CONFIRMED", "IN_PROGRESS", "REMEDIATION",
        "COMPLETED", "DISQUALIFIED", "WITHDRAWN")
    assert data["current_phase"] in (
        "GROUND_SCHOOL", "SIMULATOR", "CHECKRIDE", "IOE", "DONE")
    assert isinstance(data["failed_attempts"], int) and data["failed_attempts"] >= 0


def assert_training_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["instructor_id"], str)
    assert data["phase"] in ("GROUND_SCHOOL", "SIMULATOR", "CHECKRIDE", "IOE")
    assert data["event_type"] in ("SESSION", "MILESTONE")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "FAILED", "CANCELLED")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["billed_amount_cents"], int)


def assert_checkride(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["check_airman_id"], str)
    assert data["ride_type"] in ("ORAL", "PRACTICAL", "LINE_CHECK")
    assert data["status"] in (
        "SCHEDULED", "COMPLETED_PASS", "COMPLETED_FAIL", "CANCELLED")
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1


def assert_qualification(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["equipment_id"], str)
    assert data["currency_state"] in (
        "QUALIFIED", "CURRENCY_WARNING", "LAPSED", "REQUALIFYING", "EXPIRED")
    assert data["operating_state"] in ("ACTIVE", "GROUNDED")
    assert isinstance(data["landings_90d"], int) and data["landings_90d"] >= 0
    assert isinstance(data["landings_expiring_7d"], int)
    assert data["landings_expiring_7d"] >= 0


def assert_flight_activity(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["qualification_id"], str)
    assert isinstance(data["landings"], int) and data["landings"] >= 0
    assert data["hours"] >= 0
    assert data["activity_type"] in ("REVENUE", "TRAINING", "CHECK")


def assert_medical_certificate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["applicant_id"], str)
    assert data["cert_class"] in ("FIRST", "SECOND", "THIRD")
    assert isinstance(data["pilot_age_at_issue"], int)
    assert data["pilot_age_at_issue"] >= 17
    assert data["status"] in ("VALID", "DOWNGRADED", "EXPIRED", "SUSPENDED")


def assert_bid_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["equipment_id"], str)
    assert isinstance(data["seats_available"], int) and data["seats_available"] >= 1
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "AWARDED", "FINALIZED")


def assert_bid(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bid_period_id"], str)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["preference_rank"], int) and data["preference_rank"] >= 1
    assert data["status"] in ("SUBMITTED", "AWARDED", "DENIED", "WITHDRAWN")
    assert data["denial_reason"] is None or data["denial_reason"] in (
        "INSUFFICIENT_SENIORITY", "INELIGIBLE")


def assert_instructor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["instructor_type"] in ("GROUND", "SIMULATOR", "CHECK_AIRMAN")
    assert isinstance(data["daily_max_sessions"], int)
    assert data["daily_max_sessions"] >= 1


def assert_simulator_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["equipment_id"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")


def assert_cost_ledger_entry(data: dict):
    """Append-only ledger entry: id + created_at only from the common set."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601 UTC")
    assert "updated_at" not in data, (
        "CostLedgerEntry is append-only: updated_at must be absent")
    assert "version" not in data, (
        "CostLedgerEntry is append-only: version must be absent")
    assert isinstance(data["applicant_id"], str)
    assert data["entry_type"] in (
        "GROUND_SCHOOL", "SIMULATOR", "IOE", "CHECKRIDE",
        "RETRAINING", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    assert data["provisional"] is True


def assert_ledger_balance_invariant(applicant: dict, ledger_rows: list):
    """The applicant's ledger_balance_cents equals the signed net sum of all
    of that applicant's ledger entries."""
    total = sum(row["amount_cents"] for row in ledger_rows)
    assert applicant["ledger_balance_cents"] == total, (
        f"ledger_balance_cents {applicant['ledger_balance_cents']} != "
        f"signed sum of entries {total}")
