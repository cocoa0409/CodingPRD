"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["daily_census_capacity"], int)
    assert isinstance(data["max_roster"], int)
    assert isinstance(data["medicaid_monthly_rate_cents"], int)
    assert isinstance(data["medicare_monthly_rate_cents"], int)
    assert isinstance(data["enrolled_count"], int)
    assert data["status"] in ("OPEN", "SUSPENDED")
    assert isinstance(data["version"], int)


def assert_participant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["dual_eligible"], bool)
    assert data["status"] in (
        "APPLICANT", "ELIGIBLE", "ENROLLED", "DISENROLLMENT_PENDING", "DISENROLLED",
    )
    assert isinstance(data["ledger_billed_cents"], int)
    assert isinstance(data["ledger_reconciled_cents"], int)
    assert isinstance(data["lifetime_attendance_days"], int)
    assert isinstance(data["version"], int)


def assert_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["participant_id"], str)


def assert_loc_assessment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["nf_score"], int)
    assert data["status"] in ("PENDING", "CERTIFIED", "DENIED", "EXPIRED", "SUPERSEDED")


def assert_care_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["idt_disciplines_signed"], list)
    assert isinstance(data["required_disciplines"], list)
    assert isinstance(data["goal_count"], int)
    assert data["status"] in (
        "DRAFT", "IN_REVIEW", "ACTIVE", "REVISION", "SUPERSEDED", "VOID",
    )


def assert_care_plan_goal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["discipline"] in ("RN", "SW", "PT", "DIETICIAN", "MEDICAL_DIRECTOR")
    assert data["status"] in ("OPEN", "MET", "DISCONTINUED")


def assert_attendance_day(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["meals_provided"], int)
    assert isinstance(data["activities_count"], int)
    assert isinstance(data["transport_leg_count"], int)
    assert data["status"] in (
        "SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED",
    )


def assert_transport_leg(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["direction"] in ("PICKUP", "DROPOFF")
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)
    assert data["status"] in ("PLANNED", "CANCELLED")


def assert_medication_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["daily_doses"], int)
    assert isinstance(data["administered_count"], int)
    assert data["status"] in ("ORDERED", "ACTIVE", "HELD", "DISCONTINUED")


def assert_medication_administration(data: dict):
    """Append-only event record: carries ONLY id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "MedicationAdministration must not carry updated_at"
    assert "version" not in data, "MedicationAdministration must not carry version"
    assert data["outcome"] in ("GIVEN", "REFUSED", "HELD")


def assert_capitation_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["proration_mode"] in ("FULL_MONTH", "DAILY")
    assert data["status"] in ("DRAFT", "FINALIZED", "RECONCILED", "VOID")


def assert_disenrollment_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("VOLUNTARY", "INVOLUNTARY")
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "FINALIZED", "DENIED", "WITHDRAWN",
    )


def assert_capitation_components_sum(data: dict):
    """total_billed_cents is the sum of the three rounded components (PRD 3.7)."""
    total = data["medicaid_share_cents"] + data["medicare_share_cents"] + data["supplement_cents"]
    assert data["total_billed_cents"] == total, (
        f"total_billed_cents {data['total_billed_cents']} must equal sum of components {total}"
    )
