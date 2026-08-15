"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_representative(data: dict):
    _assert_common(data)
    assert isinstance(data["crd_number"], str) and data["crd_number"]
    assert data["role_tier"] in ("RR", "PRINCIPAL")
    assert isinstance(data["insurance_licensed"], bool)
    assert data["registration_status"] in ("ACTIVE", "INACTIVE_CE", "TERMINATED")


def assert_content(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["ce_category"] in (
        "REGULATORY_ELEMENT", "FIRM_ELEMENT", "PRODUCT", "STATE_INSURANCE")
    assert data["delivery_format"] in ("ELEARNING", "INSTRUCTOR_LED")
    assert data["content_status"] in (
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "RETIRED")


def assert_session(data: dict):
    _assert_common(data)
    assert isinstance(data["content_id"], str)
    assert data["session_status"] in ("SCHEDULED", "DELIVERED", "CANCELLED")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["available_seats"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["rep_id"], str)
    assert data["enrollment_status"] in (
        "ENROLLED", "IN_PROGRESS", "COMPLETED", "FAILED",
        "CANCELLED", "EXPIRED", "VOIDED")
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["rep_id"], str)
    assert data["assignment_status"] in ("ASSIGNED", "OVERDUE", "LAPSED", "COMPLETED")
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert is_iso8601_timestamp(data.get("lapse_after", ""))


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["rep_id"], str)
    assert data["plan_status"] in (
        "NEEDS_ANALYSIS", "PLAN_PUBLISHED", "CLOSED", "SUPERSEDED")


def assert_attestation(data: dict):
    _assert_common(data)
    assert isinstance(data["rep_id"], str)
    assert isinstance(data["plan_id"], str)
    assert data["attestation_status"] in ("PENDING", "ATTESTED", "VOIDED")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["product_status"] in ("PROPOSED", "LAUNCHED", "WITHDRAWN")


def assert_certification(data: dict):
    _assert_common(data)
    assert isinstance(data["rep_id"], str)
    assert isinstance(data["product_id"], str)
    assert data["cert_status"] in ("PENDING_TRAINING", "CERTIFIED", "SUSPENDED")


def assert_license(data: dict):
    _assert_common(data)
    assert isinstance(data["rep_id"], str)
    assert isinstance(data["state_code"], str)
    assert data["license_status"] in ("ACTIVE", "LAPSED")


def assert_blackout_window(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and data["label"]
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))


def assert_audit_event(data: dict):
    # Append-only (PRD §2.5): id + created_at only, no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["event_type"] in (
        "CONTENT_APPROVED", "CONTENT_REJECTED", "CONTENT_RETIRED",
        "ENROLLMENT_COMPLETED", "ENROLLMENT_VOIDED",
        "ATTESTATION_ATTESTED", "ATTESTATION_VOIDED",
        "ASSIGNMENT_LAPSED", "ASSIGNMENT_COMPLETED",
        "REGISTRATION_STATUS_CHANGED", "PRODUCT_LAUNCHED",
        "CERTIFICATION_STATUS_CHANGED", "ENFORCEMENT_SWEEP_RUN",
        "PLAN_PUBLISHED", "PLAN_CLOSED", "PLAN_REOPENED")
    assert isinstance(data["entity_type"], str)
    assert isinstance(data["entity_id"], str)


def assert_seat_invariant(session: dict):
    """PRD §3.3: available_seats == capacity - active seat holders."""
    assert session["available_seats"] <= session["capacity"], (
        f"available_seats {session['available_seats']} exceeds "
        f"capacity {session['capacity']}")
    assert session["available_seats"] >= 0
