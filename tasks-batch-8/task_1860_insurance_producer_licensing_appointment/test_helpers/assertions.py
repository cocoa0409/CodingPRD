"""Entity assertions and domain invariant checkers (PRD sections 2.2-2.7, 3.x).

Datetime comparisons in this platform are made to the second (PRD section 2.7),
so instant assertions parse both sides and compare instants rather than
requiring an exact string rendering.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

LINES_OF_AUTHORITY = ("LIFE", "ACCIDENT_HEALTH", "PROPERTY", "CASUALTY", "PERSONAL_LINES")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits."""
    assert isinstance(value, str) and value.strip(), f"expected an ISO instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO 8601 instants denote the same second (PRD 2.7)."""
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    """Every resource carries id / created_at / updated_at / version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_subject(data: dict):
    """Exactly one of producer_id / agency_id is set (PRD 2.6)."""
    producer_id = data.get("producer_id")
    agency_id = data.get("agency_id")
    assert (producer_id is None) != (agency_id is None), (
        f"exactly one subject must be set, got producer_id={producer_id!r} agency_id={agency_id!r}"
    )


def _assert_hours(value, label: str):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a number, got {value!r}"
    )


def assert_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["resident_state_code"], str) and len(data["resident_state_code"]) == 2


def assert_producer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["npn"], str) and data["npn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["resident_state_code"], str) and len(data["resident_state_code"]) == 2
    assert data.get("agency_id") is None or is_valid_uuid(data["agency_id"])
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["ytd_issued_premium_cents"], int)
    assert isinstance(data["commission_held_cents"], int)


def assert_license(data: dict):
    _assert_common_fields(data)
    _assert_subject(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["license_class"] in ("RESIDENT", "NON_RESIDENT")
    assert isinstance(data["lines_of_authority"], list) and len(data["lines_of_authority"]) >= 1
    assert all(loa in LINES_OF_AUTHORITY for loa in data["lines_of_authority"])
    assert data["status"] in ("ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED")
    assert is_iso8601_timestamp(data["issue_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert is_iso8601_timestamp(data["ce_period_start"])
    assert is_iso8601_timestamp(data["ce_period_end"])
    for field in ("ce_required_hours", "ce_ethics_required_hours",
                  "ce_completed_hours", "ce_ethics_completed_hours"):
        _assert_hours(data[field], field)
    assert isinstance(data["renewed_count"], int) and data["renewed_count"] >= 0


def assert_ce_credit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["license_id"])
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert isinstance(data["course_title"], str) and data["course_title"]
    assert data["category"] in ("GENERAL", "ETHICS")
    _assert_hours(data["credit_hours"], "credit_hours")
    assert data["credit_hours"] > 0
    assert is_iso8601_timestamp(data["completed_on"])
    assert data["status"] in ("REPORTED", "ACCEPTED", "REJECTED")
    assert data.get("reviewed_by_user_id") is None or isinstance(data["reviewed_by_user_id"], str)


def assert_appointment(data: dict):
    _assert_common_fields(data)
    _assert_subject(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["lines_of_authority"], list) and len(data["lines_of_authority"]) >= 1
    assert all(loa in LINES_OF_AUTHORITY for loa in data["lines_of_authority"])
    assert data["origin"] in ("STANDARD", "JIT")
    assert data["status"] in (
        "REQUESTED", "JIT_PENDING", "ACTIVE", "TERMINATION_PENDING", "TERMINATED", "LAPSED",
    )
    assert data.get("termination_reason") in (None, "VOLUNTARY", "FOR_CAUSE", "LICENSE_INACTIVE")
    for field in ("effective_date", "termination_date", "termination_initiated_at",
                  "jit_filing_deadline"):
        assert data.get(field) is None or is_iso8601_timestamp(data[field]), field


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["producer_id"])
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["line_of_authority"] in LINES_OF_AUTHORITY
    assert isinstance(data["applicant_name"], str) and data["applicant_name"]
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] >= 500
    assert data["status"] in ("SUBMITTED", "APPROVED", "DECLINED", "ISSUED", "RESCINDED")
    assert is_iso8601_timestamp(data["submitted_at"])
    assert data.get("decided_at") is None or is_iso8601_timestamp(data["decided_at"])
    assert data.get("issued_at") is None or is_iso8601_timestamp(data["issued_at"])
    assert data["eligibility_snapshot"] in (
        "ELIGIBLE", "LICENSE_GAP", "APPOINTMENT_GAP", "PRODUCER_SUSPENDED",
    )
    assert data.get("jit_appointment_id") is None or is_valid_uuid(data["jit_appointment_id"])


def assert_commission_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["producer_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["amount_variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("HELD", "PAYABLE", "PAID", "FORFEITED")
    assert data.get("hold_reason") in (
        None, "APPOINTMENT_PENDING", "UNLICENSED_AT_SALE", "REGULATORY_HOLD",
    )


def assert_regulatory_action(data: dict):
    _assert_common_fields(data)
    _assert_subject(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["action_type"] in ("FINE", "SUSPENSION", "REVOCATION", "PROBATION")
    if data["action_type"] == "FINE":
        assert isinstance(data["fine_amount_cents"], int) and data["fine_amount_cents"] > 0
    assert is_iso8601_timestamp(data["effective_date"])
    assert data["status"] in ("REPORTED", "CONFIRMED", "DISMISSED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data.get("decided_by_user_id") is None or isinstance(data["decided_by_user_id"], str)
    assert isinstance(data["fine_allocations"], list)
    for allocation in data["fine_allocations"]:
        assert is_valid_uuid(allocation["application_id"])
        assert isinstance(allocation["allocated_cents"], int) and allocation["allocated_cents"] >= 0


def assert_inquiry(data: dict):
    _assert_common_fields(data)
    _assert_subject(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["reference_number"], str) and data["reference_number"]
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["status"] in ("OPEN", "OVERDUE", "RESPONSE_SUBMITTED", "CLOSED")
    assert data.get("response_text") is None or isinstance(data["response_text"], str)
    assert data.get("responded_at") is None or is_iso8601_timestamp(data["responded_at"])


def assert_producer_counters(producer: dict):
    """Derived counters are integer cents and never negative (PRD 3.1, 3.6)."""
    assert isinstance(producer["ytd_issued_premium_cents"], int)
    assert producer["ytd_issued_premium_cents"] >= 0
    assert isinstance(producer["commission_held_cents"], int)
    assert producer["commission_held_cents"] >= 0
