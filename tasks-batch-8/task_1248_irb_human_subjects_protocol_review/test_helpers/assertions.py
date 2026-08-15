"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating 'Z' or '+00:00' renderings."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_timestamp_equals(actual: str, expected_iso: str):
    """Two ISO 8601 strings denote the same instant."""
    assert isinstance(actual, str), f"expected a timestamp string, got {actual!r}"
    assert _parse_ts(actual) == _parse_ts(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_investigator(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["department"], str)
    assert is_iso8601_timestamp(data["training_expires_at"])
    assert isinstance(data["provisional_compliance_score"], int)
    assert isinstance(data["final_compliance_score"], int)
    assert data["status"] in ("ACTIVE", "DEBARRED")


def assert_irb_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["member_category"] in (
        "SCIENTIST", "NON_SCIENTIST", "UNAFFILIATED", "PRISONER_REPRESENTATIVE"
    )
    assert isinstance(data["is_chair"], bool)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["active_assignment_count"], int)


def assert_protocol(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pi_id", "")), "pi_id must reference an Investigator"
    assert isinstance(data["title"], str) and data["title"]
    assert data["claimed_review_level"] in ("EXEMPT", "EXPEDITED", "FULL_BOARD")
    assert data["risk_level"] in ("MINIMAL", "GREATER_THAN_MINIMAL")
    assert isinstance(data["involves_prisoners"], bool)
    assert isinstance(data["is_industry_sponsored"], bool)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RETURNED", "UNDER_EXPEDITED_REVIEW",
        "AWAITING_FULL_BOARD", "CHANGES_REQUESTED", "BOARD_CHANGES_REQUESTED",
        "EXEMPT_ACTIVE", "APPROVED", "SUSPENDED", "EXPIRED", "DISAPPROVED",
        "WITHDRAWN", "CLOSED",
    )


def assert_consent_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert isinstance(data["version_seq"], int) and data["version_seq"] >= 1
    assert isinstance(data["file_ref"], str) and data["file_ref"]
    assert data["waiver_type"] in (
        "NONE", "WAIVER_OF_CONSENT", "WAIVER_OF_DOCUMENTATION", "ALTERATION_OF_CONSENT"
    )
    assert data["status"] in ("SUBMITTED", "APPROVED", "SUPERSEDED", "CHANGES_REQUIRED")


def assert_review_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert is_valid_uuid(data.get("reviewer_id", ""))
    assert data["reviewer_role"] in ("PRIMARY", "SECONDARY")
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["response_deadline_at"])
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "DECLINED", "RECUSED", "EXPIRED", "SUBMITTED"
    )


def assert_conflict_declaration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert is_valid_uuid(data.get("reviewer_id", ""))
    assert data["declaration_type"] in ("NONE", "FINANCIAL", "PERSONAL", "SCIENTIFIC")
    assert data["status"] in ("PENDING_REVIEW", "CLEARED", "CONFLICTED")


def assert_board_meeting(data: dict):
    _assert_common(data)
    assert isinstance(data["room_id"], str) and data["room_id"]
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["item_count"], int)
    assert data["status"] in (
        "SCHEDULED", "CONVENED", "ADJOURNED", "CANCELLED", "FAILED_QUORUM"
    )


def assert_agenda_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("meeting_id", ""))
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert data["priority_class"] in ("SUSPENSION_REVIEW", "INITIAL_REVIEW", "MODIFICATION")
    assert data["status"] in ("LISTED", "VOTED", "DEFERRED", "REMOVED")


def assert_modification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert data["scope"] in ("MINOR", "MAJOR")
    assert isinstance(data["description"], str)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")


def assert_continuing_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert is_iso8601_timestamp(data["due_at"])
    assert is_iso8601_timestamp(data["window_opens_at"])
    assert data["status"] in (
        "PENDING_SUBMISSION", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "LAPSED"
    )


def assert_adverse_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert data["event_type"] in (
        "SERIOUS_ADVERSE_EVENT", "UNANTICIPATED_PROBLEM", "PROTOCOL_DEVIATION_WITH_HARM"
    )
    assert is_iso8601_timestamp(data["occurred_at"])
    assert is_iso8601_timestamp(data["reported_at"])
    assert isinstance(data["is_late"], bool)
    assert data["status"] in ("FILED", "TRIAGED", "CLOSED_NO_ACTION", "CLOSED_WITH_ACTION")


def assert_non_compliance_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert data["source"] in ("LATE_AE", "LAPSED_CR", "AE_ACTION", "MANUAL")
    assert is_iso8601_timestamp(data["opened_at"])
    assert data["status"] in (
        "OPENED", "INVESTIGATION", "FINDING_CONFIRMED", "FINDING_NOT_CONFIRMED", "CLOSED"
    )


def assert_reliance_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("protocol_id", ""))
    assert isinstance(data["ceding_institution_code"], str) and data["ceding_institution_code"]
    assert isinstance(data["reviewing_institution_code"], str)
    assert data["status"] in ("PROPOSED", "EXECUTED", "SUSPENDED", "TERMINATED")
