"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_nurse(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["primary_state_of_residence"] in (
        "AZ", "CO", "FL", "GA", "MD", "NC", "TN", "TX",
    ) or isinstance(data["primary_state_of_residence"], str)
    assert data["employment_type"] in ("STAFF", "TRAVEL", "PER_DIEM")
    assert data["status"] in ("ONBOARDING", "ACTIVE", "TERMINATED")
    assert data["credential_posture"] in ("CLEAR", "SCHEDULING_SUSPENDED", "PRACTICE_RESTRICTED")
    assert data["multistate_privilege_status"] in (
        "ELIGIBLE_MULTISTATE", "SINGLE_STATE_ONLY", "NONE",
    )
    assert isinstance(data["practice_scope"], list)
    assert isinstance(data["open_encumbrance_count"], int)


def assert_state_license(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["nurse_id"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["license_class"] in ("RN", "APRN")
    assert isinstance(data["multistate_flag"], bool)
    assert isinstance(data["issued_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in (
        "DRAFT", "PENDING_VERIFICATION", "VERIFIED", "ACTIVE",
        "EXPIRED", "ENCUMBERED", "SURRENDERED",
    )
    assert isinstance(data["created_by_user_id"], str)
    assert data.get("verified_by_user_id") is None or isinstance(data["verified_by_user_id"], str)


def assert_psv(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["license_id"], str)
    assert data["channel"] in ("NURSYS", "BOARD_PORTAL", "MANUAL_REVIEW")
    assert data["status"] in ("REQUESTED", "VERIFIED", "DISCREPANCY", "UNREACHABLE")
    assert isinstance(data["requested_by_user_id"], str)
    assert data.get("resolved_by_user_id") is None or isinstance(data["resolved_by_user_id"], str)
    assert data.get("verified_on") is None or isinstance(data["verified_on"], str)
    assert data.get("valid_through") is None or isinstance(data["valid_through"], str)


def assert_certification(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["nurse_id"], str)
    assert data["cert_type"] in ("BLS", "ACLS", "PALS", "CCRN", "CNOR", "OCN")
    assert isinstance(data["issuing_body"], str) and data["issuing_body"]
    assert isinstance(data["obtained_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_disciplinary_action(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["nurse_id"], str)
    assert data.get("license_id") is None or isinstance(data["license_id"], str)
    assert data["scope"] in ("LICENSE", "PRIVILEGE")
    assert data["action_type"] in ("REPRIMAND", "PROBATION", "SUSPENSION", "REVOCATION")
    assert isinstance(data["effective_on"], str)
    assert data["status"] in ("REPORTED", "UNDER_REVIEW", "ADJUDICATED", "DISMISSED", "RESOLVED")
    assert isinstance(data["reported_by_user_id"], str)


def assert_credential_packet(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["nurse_id"], str)
    assert isinstance(data["target_unit_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "VOIDED")
    assert isinstance(data["readiness_score"], (int, float))
    assert isinstance(data["created_by_user_id"], str)


def assert_packet_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["packet_id"], str)
    assert data["item_type"] in (
        "LICENSE_VERIFICATION", "BLS", "ACLS", "COMPETENCY_ANNUAL", "ATTESTATION",
    )
    assert isinstance(data["critical"], bool)
    assert isinstance(data["weight"], int)
    assert data["status"] in ("MISSING", "SUBMITTED", "VERIFIED", "WAIVED", "INVALIDATED")


def assert_competency_requirement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["validity_months"], int)
    assert data["window_mode"] in ("ROLLING", "FISCAL")
    assert isinstance(data["mandatory"], bool)
    assert isinstance(data["applies_to"], list)


def assert_competency_completion(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["nurse_id"], str)
    assert isinstance(data["requirement_id"], str)
    assert isinstance(data["completed_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ("CURRENT", "LAPSED", "SUPERSEDED")
    assert data["source"] in ("MANUAL", "SESSION")


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["required_cert_types"], list)
    assert isinstance(data["scheduled_hours_total"], (int, float))
    assert isinstance(data["active_assignment_count"], int)


def assert_shift_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["nurse_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert isinstance(data["hours"], (int, float))
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "AUTO_CANCELLED")
    assert data.get("was_clear_at_start") is None or isinstance(data["was_clear_at_start"], bool)
    assert data.get("cancel_reason") is None or data["cancel_reason"] in (
        "MANUAL", "POSTURE_SCHEDULING_SUSPENDED", "POSTURE_PRACTICE_RESTRICTED", "NURSE_TERMINATED",
    )


def assert_competency_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["requirement_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["booked_count"], int)


def assert_session_booking(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["nurse_id"], str)
    assert isinstance(data["attended"], bool)
    assert data.get("completion_id") is None or isinstance(data["completion_id"], str)


def assert_privilege_evaluation(data: dict):
    """Append-only event row (PRD §2.4): id + created_at only; no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only event log must not carry updated_at"
    assert "version" not in data, "append-only event log must not carry version"
    assert isinstance(data["nurse_id"], str)
    assert data["trigger_reason"] in (
        "MANUAL", "PSOR_CHANGE", "LICENSE_CHANGE", "DISCIPLINE_CHANGE", "SWEEP",
    )
    assert data["resulting_status"] in ("ELIGIBLE_MULTISTATE", "SINGLE_STATE_ONLY", "NONE")
    assert isinstance(data["resulting_scope"], list)


def assert_audit_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["per_unit_sample_size"], int)
    assert data["status"] in ("INITIATED", "FIELD_WORK", "FINDINGS_ISSUED", "CLOSED")
    assert isinstance(data["sampled_nurse_ids"], list)
    assert data.get("point_in_time_rate") is None or isinstance(
        data["point_in_time_rate"], (int, float)
    )
    assert data.get("shift_incidence_rate") is None or isinstance(
        data["shift_incidence_rate"], (int, float)
    )
    assert data.get("projected_deficiency_count") is None or isinstance(
        data["projected_deficiency_count"], (int, float)
    )
    assert isinstance(data["created_by_user_id"], str)


def assert_audit_finding(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["audit_run_id"], str)
    assert isinstance(data["nurse_id"], str)
    assert data["finding_type"] in (
        "LICENSE_NOT_CURRENT_IN_WINDOW",
        "CERTIFICATION_NOT_CURRENT_IN_WINDOW",
        "COMPETENCY_NOT_CURRENT_IN_WINDOW",
    )
    assert isinstance(data["detail"], str)
    assert data["status"] in ("OPEN", "REMEDIATED", "ACCEPTED_RISK")


def assert_unit_counters(data: dict, expected_hours: float, expected_count: int):
    """The unit staffing ledger after any operation (PRD §3.6)."""
    import pytest

    assert data["scheduled_hours_total"] == pytest.approx(expected_hours, abs=0.01), (
        f"scheduled_hours_total {data['scheduled_hours_total']} != {expected_hours}"
    )
    assert data["active_assignment_count"] == expected_count, (
        f"active_assignment_count {data['active_assignment_count']} != {expected_count}"
    )
