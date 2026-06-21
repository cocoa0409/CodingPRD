"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "program id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["code"] in ("PRECHECK", "GLOBAL_ENTRY")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert data["validity_years"] in (3, 4, 5)
    assert 0 <= data["vetting_risk_threshold"] <= 100
    assert 0 <= data["vetting_deny_threshold"] <= 100
    assert data["vetting_deny_threshold"] > data["vetting_risk_threshold"]
    assert 0 <= data["redress_min_score"] <= 100


def assert_applicant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "applicant id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["citizenship"] in ("US_CITIZEN", "LPR", "NONIMMIGRANT")
    assert isinstance(data["disqualifying_flag"], bool)


def assert_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "application id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["applicant_id"]), "applicant_id must be valid UUID"
    assert data["program_code"] in ("PRECHECK", "GLOBAL_ENTRY")
    assert isinstance(data["fee_due_cents"], int)
    assert isinstance(data["fee_paid_cents"], int)
    assert isinstance(data["appeal_count"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "VETTING", "INTERVIEW_SCHEDULED",
        "INTERVIEW_COMPLETE", "APPROVED", "DENIED", "APPEAL_PENDING", "WITHDRAWN",
    )
    assert isinstance(data["version"], int)


def assert_center(data: dict):
    assert is_valid_uuid(data.get("id", "")), "center id must be valid UUID"
    assert data["program_code"] in ("PRECHECK", "GLOBAL_ENTRY")
    assert isinstance(data["daily_interview_capacity"], int) and data["daily_interview_capacity"] >= 1
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert isinstance(data["lane_count"], int) and data["lane_count"] >= 1
    assert data["status"] in ("OPEN", "SUSPENDED")


def assert_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "slot id must be valid UUID"
    assert is_valid_uuid(data["center_id"]), "center_id must be valid UUID"
    assert isinstance(data["lane_index"], int) and data["lane_index"] >= 0
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in ("AVAILABLE", "BOOKED", "RELEASED")


def assert_background_check(data: dict):
    assert is_valid_uuid(data.get("id", "")), "background check id must be valid UUID"
    assert is_valid_uuid(data["application_id"]), "application_id must be valid UUID"
    assert isinstance(data["criminal_hits"], int) and data["criminal_hits"] >= 0
    assert isinstance(data["watchlist_hits"], int) and data["watchlist_hits"] >= 0
    assert isinstance(data["prior_revocations"], int) and data["prior_revocations"] >= 0
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 100, "risk_score must be clamped to [0,100]"
    assert isinstance(data["redress_offset_applied"], int)
    assert data["status"] in ("PENDING", "CLEARED", "REVIEW", "ADVERSE")


def assert_appointment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "appointment id must be valid UUID"
    assert is_valid_uuid(data["application_id"]), "application_id must be valid UUID"
    assert is_valid_uuid(data["slot_id"]), "slot_id must be valid UUID"
    assert data["status"] in ("CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_biometric_capture(data: dict):
    assert is_valid_uuid(data.get("id", "")), "biometric id must be valid UUID"
    assert is_valid_uuid(data["appointment_id"]), "appointment_id must be valid UUID"
    assert isinstance(data["fingerprint_quality"], int) and 1 <= data["fingerprint_quality"] <= 5
    assert isinstance(data["photo_captured"], bool)
    assert data["status"] in ("ACCEPTED", "REJECTED")


def assert_ktn(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ktn id must be valid UUID"
    assert is_valid_uuid(data["application_id"]), "application_id must be valid UUID"
    assert isinstance(data["ktn_value"], str) and len(data["ktn_value"]) == 9
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED", "SUPERSEDED")


def assert_appeal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "appeal id must be valid UUID"
    assert is_valid_uuid(data["application_id"]), "application_id must be valid UUID"
    assert isinstance(data["filed_reason"], str)
    assert data["status"] in ("OPEN", "DECIDED")


def assert_redress_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "redress id must be valid UUID"
    assert is_valid_uuid(data["application_id"]), "application_id must be valid UUID"
    assert isinstance(data["trip_number"], str)
    assert isinstance(data["match_strength_score"], int) and 0 <= data["match_strength_score"] <= 100
    assert data["status"] in ("FILED", "RESOLVED")


def assert_fee_transaction(data: dict):
    """FeeTransaction is an immutable event log: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "fee transaction id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["application_id"]), "application_id must be valid UUID"
    assert data["kind"] in ("PAYMENT", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    # Immutable event-log records carry no version field.
    assert "version" not in data, "FeeTransaction must not expose a version field"


def assert_fee_ledger_conserved(application: dict, payments_total: int, refunds_total: int):
    """fee_paid_cents must equal sum(PAYMENT) - sum(REFUND)."""
    expected = payments_total - refunds_total
    assert application["fee_paid_cents"] == expected, (
        f"fee_paid_cents {application['fee_paid_cents']} != "
        f"payments {payments_total} - refunds {refunds_total} = {expected}"
    )
