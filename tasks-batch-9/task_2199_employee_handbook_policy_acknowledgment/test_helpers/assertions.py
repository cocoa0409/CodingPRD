"""Entity assertions and domain invariant checkers (PRD-exact field names)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """PRD §2.4: id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict):
    """PRD §2.4: append-only rows carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only row must not expose updated_at"
    assert "version" not in data, "append-only row must not expose version"


def assert_jurisdiction(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"] == data["state_code"].upper()
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["min_legal_review_days"], int)
    assert 0 <= data["min_legal_review_days"] <= 120
    assert isinstance(data["ack_deadline_days"], int)
    assert 1 <= data["ack_deadline_days"] <= 180
    assert isinstance(data["esign_permitted"], bool)
    assert isinstance(data["proxy_ack_permitted"], bool)
    assert isinstance(data["retention_years"], int)
    assert 1 <= data["retention_years"] <= 30
    assert isinstance(data["required_language_codes"], list)
    assert data["required_language_codes"], "required_language_codes must be non-empty"
    assert "en" in data["required_language_codes"]
    assert isinstance(data["ack_window_buffer_days"], int)
    assert 0 <= data["ack_window_buffer_days"] <= 30


def assert_legal_reviewer(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["bar_number"], str) and data["bar_number"]
    assert isinstance(data["concurrent_review_limit"], int)
    assert 1 <= data["concurrent_review_limit"] <= 10
    assert isinstance(data["open_review_count"], int) and data["open_review_count"] >= 0
    assert isinstance(data["is_active"], bool)


def assert_employee(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["work_email"], str) and "@" in data["work_email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["preferred_language_code"], str)
    assert len(data["preferred_language_code"]) == 2
    assert isinstance(data["needs_accessible_format"], bool)
    assert data["employment_status"] in ("ACTIVE", "ON_LEAVE", "TERMINATED")
    assert isinstance(data["open_ack_count"], int) and data["open_ack_count"] >= 0
    assert isinstance(data["open_escalation_count"], int)
    assert data["open_escalation_count"] >= 0


def assert_policy_document(data: dict):
    assert_common_fields(data)
    assert isinstance(data["title"], str) and 3 <= len(data["title"]) <= 160
    assert data["category"] in (
        "CODE_OF_CONDUCT", "LEAVE", "SAFETY", "COMPENSATION", "DATA_PRIVACY",
    )
    assert isinstance(data["latest_version_no"], int)
    assert data["latest_version_no"] >= 0
    assert isinstance(data["max_ack_deadline_days"], int)
    assert 1 <= data["max_ack_deadline_days"] <= 180


def assert_policy_version(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["policy_document_id"])
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["body_text"], str) and data["body_text"]
    assert isinstance(data["section_count"], int)
    assert 1 <= data["section_count"] <= 40
    assert data["status"] in (
        "DRAFT", "IN_LEGAL_REVIEW", "APPROVED", "PUBLISHED", "SUPERSEDED", "WITHDRAWN",
    )
    assert isinstance(data["required_jurisdiction_ids"], list)
    assert data["required_jurisdiction_ids"]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["pinned_addendum_ids"], list)


def assert_addendum(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["policy_version_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["body_text"], str) and data["body_text"]
    assert data["status"] in ("DRAFT", "APPROVED", "RETIRED")


def assert_legal_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["policy_version_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["reviewer_id"])
    assert is_iso8601_timestamp(data["assigned_at"])
    assert isinstance(data["due_at"], str) and data["due_at"]
    assert data["status"] in (
        "REQUESTED", "IN_PROGRESS", "APPROVED", "CHANGES_REQUESTED", "WITHDRAWN",
    )
    assert isinstance(data["round_no"], int) and data["round_no"] >= 1


def assert_translation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["policy_version_id"])
    assert isinstance(data["language_code"], str) and len(data["language_code"]) == 2
    assert data["status"] in (
        "PENDING", "IN_TRANSLATION", "A11Y_REVIEW", "PUBLISHED", "ABANDONED",
    )
    assert isinstance(data["section_scores"], list)
    assert isinstance(data["a11y_round_no"], int) and data["a11y_round_no"] >= 0
    assert data["conformance_level"] in (None, "FAIL", "AA", "AAA")
    if data["a11y_index"] is not None:
        assert 0 <= data["a11y_index"] <= 100


def assert_release_package(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["effective_date"], str) and data["effective_date"]
    assert isinstance(data["scope_jurisdiction_ids"], list)
    assert data["scope_jurisdiction_ids"]
    assert data["status"] in ("DRAFT", "SCHEDULED", "RELEASED", "CLOSED", "CANCELLED")
    assert isinstance(data["roster_snapshot_size"], int)
    assert data["roster_snapshot_size"] >= 0


def assert_release_item(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data["release_package_id"])
    assert is_valid_uuid(data["policy_version_id"])


def assert_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["release_package_id"])
    assert is_valid_uuid(data["policy_version_id"])
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["ack_state"] in (
        "UNDELIVERED", "PENDING", "ACKNOWLEDGED", "EXEMPT", "VOIDED",
    )
    assert data["escalation_state"] in ("NONE", "ESCALATING", "RESOLVED", "MOOT")
    assert isinstance(data["window_start_date"], str) and data["window_start_date"]
    assert isinstance(data["due_date"], str) and data["due_date"]
    assert isinstance(data["days_overdue"], int) and data["days_overdue"] >= 0
    assert data["policy_category"] in (
        "CODE_OF_CONDUCT", "LEAVE", "SAFETY", "COMPENSATION", "DATA_PRIVACY",
    )


def assert_acknowledgment(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data["assignment_id"])
    assert is_valid_uuid(data["employee_id"])
    assert data["method"] in ("ESIGN", "WET_SIGNATURE", "ATTESTED")
    assert isinstance(data["language_code"], str) and len(data["language_code"]) == 2
    assert isinstance(data["signature_text"], str) and data["signature_text"]
    assert is_iso8601_timestamp(data["captured_at"])
    assert data["status"] in ("EFFECTIVE", "REVOKED")


def assert_escalation_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["assignment_id"])
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["tier"], int) and 1 <= data["tier"] <= 3
    assert data["status"] in (
        "OPEN", "NOTIFIED", "ESCALATED_HR",
        "CLOSED_ACKNOWLEDGED", "CLOSED_MOOT", "CLOSED_DISCIPLINARY",
    )
    assert is_iso8601_timestamp(data["opened_at"])
    assert isinstance(data["notice_count"], int) and data["notice_count"] >= 0


def assert_policy_exception(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["policy_version_id"])
    assert is_valid_uuid(data["assignment_id"])
    assert data["reason_code"] in (
        "RELIGIOUS", "MEDICAL", "COLLECTIVE_BARGAINING", "ROLE_CONFLICT",
    )
    assert isinstance(data["justification"], str) and 0 < len(data["justification"]) <= 2000
    assert isinstance(data["requested_days"], int)
    assert 1 <= data["requested_days"] <= 365
    assert isinstance(data["prior_exception_count"], int)
    assert data["prior_exception_count"] >= 0
    assert data["status"] in (
        "SUBMITTED", "MANAGER_APPROVED", "GRANTED", "DENIED", "EXPIRED", "REVOKED",
    )


def assert_retention_record(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data["acknowledgment_id"])
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["record_kind"] in ("CAPTURE", "REVOCATION")
    assert data["signed_delta"] in (1, -1)
    assert is_iso8601_timestamp(data["retained_from"])
    assert isinstance(data["retention_until"], str) and data["retention_until"]
    assert isinstance(data["legal_hold"], bool)


def assert_two_decimal_places(value, label="value"):
    """PRD §2.7: percentage-style numbers carry two decimal places."""
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 2) == float(value), (
        f"{label} must be carried to two decimal places, got {value!r}"
    )


def assert_ack_ledger_balance(api, employee_id, admin_headers):
    """PRD §2.10: the signed sum of an employee's retention rows equals the
    count of that employee's EFFECTIVE acknowledgment events."""
    from prd_bench_local_runner.testing import get_success_data

    rows = get_success_data(
        api.list_retention_records(
            admin_headers, params={"employee_id": employee_id, "limit": 100}
        )
    )
    signed_sum = sum(r["signed_delta"] for r in rows)
    acks = get_success_data(
        api.list_acknowledgments(
            admin_headers,
            params={"employee_id": employee_id, "status": "EFFECTIVE", "limit": 100},
        )
    )
    assert signed_sum == len(acks), (
        f"signed acknowledgment ledger {signed_sum} must equal the count of "
        f"EFFECTIVE acknowledgment events {len(acks)} for employee {employee_id}"
    )
    return signed_sum


def assert_open_ack_count_matches(api, employee_id, admin_headers):
    """PRD §2.10: open_ack_count equals the number of that employee's
    assignments whose ack_state is UNDELIVERED or PENDING."""
    from prd_bench_local_runner.testing import get_success_data

    employee = get_success_data(api.get_employee(employee_id, admin_headers))
    rows = get_success_data(
        api.list_assignments(
            admin_headers, params={"employee_id": employee_id, "limit": 100}
        )
    )
    expected = sum(1 for a in rows if a["ack_state"] in ("UNDELIVERED", "PENDING"))
    assert employee["open_ack_count"] == expected, (
        f"open_ack_count {employee['open_ack_count']} must equal the recomputed "
        f"open assignment count {expected}"
    )
    return expected


def assert_open_escalation_count_matches(api, employee_id, admin_headers):
    """PRD §2.10: open_escalation_count equals the number of that employee's
    escalation cases whose status is OPEN, NOTIFIED or ESCALATED_HR."""
    from prd_bench_local_runner.testing import get_success_data

    employee = get_success_data(api.get_employee(employee_id, admin_headers))
    rows = get_success_data(
        api.list_escalations(
            admin_headers, params={"employee_id": employee_id, "limit": 100}
        )
    )
    expected = sum(
        1 for c in rows if c["status"] in ("OPEN", "NOTIFIED", "ESCALATED_HR")
    )
    assert employee["open_escalation_count"] == expected, (
        f"open_escalation_count {employee['open_escalation_count']} must equal the "
        f"recomputed open case count {expected}"
    )
    return expected


def _parse_instant(value):
    from datetime import datetime

    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_same_instant(actual, expected, label="instant"):
    """Compare two ISO 8601 UTC instants for equality of the moment they name."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
