"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    """Primary resources carry id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_license_type(data: dict):
    _assert_common_fields(data, "LicenseType")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["ce_hours_required_per_cycle"] >= 0
    assert 1 <= data["cycle_length_months"] <= 120
    assert 1 <= data["verification_frequency_days"] <= 3650
    assert data["grace_period_days"] >= 0
    assert isinstance(data["requires_exclusion_screening"], bool)
    assert data["reimbursement_mode"] in ("RECEIPT_BASED", "FLAT_SCHEDULE")
    assert data["reimburse_full_up_to_cents"] >= 0
    assert data["reimburse_half_up_to_cents"] >= data["reimburse_full_up_to_cents"]
    assert data["flat_schedule_amount_cents"] >= 0
    assert data["hard_claim_cap_cents"] > 0


def assert_employee(data: dict):
    _assert_common_fields(data, "Employee")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["work_email"], str) and "@" in data["work_email"]
    assert isinstance(data["role_code"], str) and data["role_code"]
    assert data["work_authorization"] in ("AUTHORIZED", "RESTRICTED")
    assert data["restriction_reason"] in (
        None, "SCREENING_FLAGGED", "LICENSE_SUSPENDED", "LICENSE_LAPSED",
        "VERIFICATION_OVERDUE", "MISSING_LICENSE",
    )
    assert data["screening_posture"] in ("CLEAR", "PENDING_REVIEW", "FLAGGED")
    assert isinstance(data["reimbursement_committed_cents"], int)
    assert data["reimbursement_committed_cents"] >= 0
    assert isinstance(data["reimbursement_paid_cents"], int)
    assert data["reimbursement_paid_cents"] >= 0


def assert_role_requirement(data: dict):
    _assert_common_fields(data, "RoleRequirement")
    assert isinstance(data["role_code"], str) and data["role_code"]
    assert is_valid_uuid(data.get("license_type_id", ""))
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["is_required"], bool)


def assert_license(data: dict):
    _assert_common_fields(data, "License")
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("license_type_id", ""))
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["issued_on"], str) and data["issued_on"]
    assert isinstance(data["expires_on"], str) and data["expires_on"]
    assert data["status"] in (
        "PENDING_VERIFICATION", "ACTIVE", "EXPIRED", "LAPSED", "SUSPENDED",
        "REVOKED",
    )
    assert data["verification_posture"] in ("NEVER_VERIFIED", "CURRENT", "OVERDUE")
    assert data["alert_tier"] in ("NONE", "T90", "T60", "T30", "AT_EXPIRY")


def assert_verification_event(data: dict):
    """The verification log is append-only: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "VerificationEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "VerificationEvent.created_at must be ISO 8601 UTC"
    )
    assert is_valid_uuid(data.get("license_id", ""))
    assert isinstance(data["verified_on"], str) and data["verified_on"]
    assert data["source"] in ("STATE_BOARD_API", "MANUAL_UPLOAD", "NURSYS")
    assert data["outcome"] in ("VERIFIED", "MISMATCH", "UNREACHABLE")
    assert isinstance(data["verifier_user_id"], str)
    assert "version" not in data, "append-only log entries carry no version field"
    assert "updated_at" not in data, "append-only log entries carry no updated_at field"


def assert_ce_activity(data: dict):
    _assert_common_fields(data, "CEActivity")
    assert is_valid_uuid(data.get("license_id", ""))
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert isinstance(data["activity_title"], str) and data["activity_title"]
    assert 0.25 <= data["hours"] <= 200
    assert data["status"] in ("LOGGED", "VALIDATED", "REJECTED")
    # Half-hour quantum: rounded_hours is a whole multiple of 0.5.
    doubled = data["rounded_hours"] * 2
    assert abs(doubled - round(doubled)) < 1e-9, (
        f"rounded_hours {data['rounded_hours']} is not on the half-hour grid"
    )


def assert_renewal_request(data: dict):
    _assert_common_fields(data, "RenewalRequest")
    assert is_valid_uuid(data.get("license_id", ""))
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] >= 0
    assert isinstance(data["estimated_reimbursable_cents"], int)
    assert data["estimated_reimbursable_cents"] >= 0
    assert isinstance(data["expires_on_at_create"], str)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "MORE_INFO", "APPROVED", "REJECTED", "PAID", "VOIDED",
    )


def assert_disciplinary_event(data: dict):
    _assert_common_fields(data, "DisciplinaryEvent")
    assert is_valid_uuid(data.get("license_id", ""))
    assert isinstance(data["board_case_number"], str) and data["board_case_number"]
    assert data["event_type"] in (
        "WARNING", "REPRIMAND", "FINE", "SUSPENSION", "REVOCATION",
    )
    assert isinstance(data["effective_on"], str) and data["effective_on"]
    assert data["received_via"] in ("BOARD_FEED", "MANUAL")
    assert data["status"] in ("RECEIVED", "CONFIRMED", "DISMISSED", "RESOLVED")
    assert isinstance(data["created_by_user_id"], str)


def assert_exclusion_screening(data: dict):
    _assert_common_fields(data, "ExclusionScreening")
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data["list_source"] in ("OIG_LEIE", "SAM_GSA", "STATE_MEDICAID")
    assert isinstance(data["screened_on"], str) and data["screened_on"]
    assert data["outcome"] in ("CLEAR", "FLAGGED")
    assert data["status"] in (
        "CLOSED_CLEAR", "UNDER_REVIEW", "CONFIRMED_MATCH", "CLEARED_FALSE_POSITIVE",
    )
    if data["status"] == "CLOSED_CLEAR":
        assert isinstance(data["valid_until"], str) and data["valid_until"], (
            "CLOSED_CLEAR screenings carry valid_until"
        )
    assert isinstance(data["created_by_user_id"], str)


def assert_audit_package(data: dict):
    _assert_common_fields(data, "AuditPackage")
    assert is_valid_uuid(data.get("employee_id", ""))
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    assert data["status"] in ("BUILDING", "SEALED", "INVALIDATED")


def assert_money_conservation(employee: dict, cap_cents: int = 1_000_000):
    """Employee money counters stay within the employer ceilings."""
    assert 0 <= employee["reimbursement_committed_cents"] <= cap_cents
    assert 0 <= employee["reimbursement_paid_cents"] <= cap_cents
