"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CASE_STATUSES = [
    "REFERRED", "SCREENED_IN", "SCREENED_OUT", "ASSIGNED", "IN_REVIEW",
    "DELIBERATION", "NOTIFIED", "RESPONDED", "COMMITTEE_REVIEW", "CLOSED",
    "EXTERNAL_REVIEW",
]
ASSIGNMENT_STATUSES = ["PENDING", "SUBMITTED", "WAIVED"]
DELIBERATION_STATUSES = ["OPEN", "FINALIZED"]
RATINGS = ["APPROPRIATE", "MINOR_OFI", "MAJOR_OFI", "UNACCEPTABLE"]
MEMBER_STATUSES = ["ACTIVE", "INACTIVE"]
FOCUSED_REVIEW_STATUSES = ["ACTIVE", "CLOSED"]
SPECIALTIES = [
    "INTERNAL_MEDICINE", "SURGERY", "CARDIOLOGY", "PEDIATRICS",
    "EMERGENCY_MEDICINE", "ANESTHESIOLOGY", "OBSTETRICS", "PSYCHIATRY",
]


def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp. PRD §2.5 pins comparisons of instants
    to second precision, so equality is evaluated on the parsed instant rather
    than on the serialized spelling."""
    assert isinstance(ts, str) and ts.strip(), f"expected ISO 8601 timestamp string, got {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str):
    """Assert two ISO 8601 timestamps denote the same instant (PRD §2.5)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"expected instant {expected_iso}, got {actual}"
    )


def assert_provider(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["specialty"] in SPECIALTIES
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int), "version must be an integer"


def assert_committee_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("provider_id", "")), "provider_id must be a valid UUID"
    assert data["specialty"] in SPECIALTIES
    assert data["member_role"] in ["MEMBER", "CHAIR"]
    assert data["status"] in MEMBER_STATUSES
    assert isinstance(data["reliability_completed_count"], int)
    assert data["reliability_completed_count"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_review_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("subject_provider_id", "")), "subject_provider_id must be a UUID"
    assert data["referral_source"] in [
        "INCIDENT_REPORT", "PATIENT_COMPLAINT", "STAFF_REFERRAL", "INSURER_INQUIRY", "OTHER",
    ]
    assert is_iso8601_timestamp(data.get("referred_at", "")), "referred_at must be ISO 8601"
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert data["status"] in CASE_STATUSES
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_review_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a valid UUID"
    assert is_valid_uuid(data.get("reviewer_id", "")), "reviewer_id must be a valid UUID"
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["status"] in ASSIGNMENT_STATUSES
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_deliberation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in DELIBERATION_STATUSES
    if data["status"] == "FINALIZED":
        assert data["rating"] in RATINGS
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_focused_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("provider_id", "")), "provider_id must be a valid UUID"
    assert data["trigger_type"] in ["AUTOMATIC", "MANUAL"]
    assert data["status"] in FOCUSED_REVIEW_STATUSES
    assert is_iso8601_timestamp(data.get("opened_at", "")), "opened_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_focus_group(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("focus_id", "")), "focus_id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_ledger_record(data: dict):
    """PRD §2.4: ConflictDeclaration, CaseNote, ProviderNotification,
    ProviderResponse, ExternalReferral, and FocusGroupMember carry only `id`
    and `created_at`; both `updated_at` and `version` are absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ledger-style records must not expose version"
    assert "updated_at" not in data, "ledger-style records must not expose updated_at"


def assert_conflict_declaration(data: dict):
    assert_ledger_record(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert is_valid_uuid(data.get("provider_id", "")), "provider_id must be a valid UUID"
    assert data["conflict_type"] in [
        "PRIOR_TREATING", "FAMILY", "FINANCIAL", "SUPERVISORY", "OTHER",
    ]
    assert data["source"] in ["SELF_DECLARED", "AUTO_CASE_RESOLVED"]


def assert_case_note(data: dict):
    assert_ledger_record(data)
    assert is_valid_uuid(data.get("author_member_id", "")), "author_member_id must be a UUID"
    assert isinstance(data["body"], str) and len(data["body"]) > 0
    assert data["note_type"] in ["GENERAL", "DELIBERATION"]


def assert_provider_notification(data: dict):
    assert_ledger_record(data)
    assert is_iso8601_timestamp(data.get("sent_at", "")), "sent_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("response_deadline", "")), \
        "response_deadline must be ISO 8601"


def assert_provider_response(data: dict):
    assert_ledger_record(data)
    assert isinstance(data["response_text"], str) and len(data["response_text"]) > 0
    assert is_iso8601_timestamp(data.get("submitted_at", "")), "submitted_at must be ISO 8601"


def assert_external_referral(data: dict):
    assert_ledger_record(data)
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert is_iso8601_timestamp(data.get("referred_at", "")), "referred_at must be ISO 8601"


def assert_focus_group_member(data: dict):
    assert_ledger_record(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
