"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a non-prefixed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a non-prefixed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must NOT carry a version field"
    assert "updated_at" not in data, "append-only record must NOT carry an updated_at field"


def assert_consumer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["ssn_last4"], str)
    assert data["status"] == "ACTIVE"


def assert_furnisher(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["furnisher_type"] in ("BANK", "CARD_ISSUER", "COLLECTION_AGENCY", "LENDER")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_reverification_count"], int) and data["open_reverification_count"] >= 0


def assert_credit_file(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["consumer_id"])
    assert data["bureau_code"] in ("EQUIFAX", "EXPERIAN", "TRANSUNION")
    assert data["protection_state"] in ("OPEN", "LOCKED", "FROZEN")
    assert isinstance(data["open_dispute_count"], int) and data["open_dispute_count"] >= 0
    assert isinstance(data["tradeline_count"], int) and data["tradeline_count"] >= 0


def assert_tradeline(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["credit_file_id"])
    assert is_valid_uuid(data["furnisher_id"])
    assert data["account_type"] in ("REVOLVING", "INSTALLMENT", "COLLECTION")
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert data["status"] in ("REPORTING", "DISPUTED", "CORRECTED", "VERIFIED", "DELETED")
    assert isinstance(data["reage_violation"], bool)
    assert is_iso8601_timestamp(data["purge_due_at"])


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["credit_file_id"])
    assert is_valid_uuid(data["tradeline_id"])
    assert is_valid_uuid(data["consumer_id"])
    assert data["dispute_reason"] in (
        "NOT_MINE", "INACCURATE_BALANCE", "ILLEGAL_REAGE", "PAID_IN_FULL", "IDENTITY_THEFT",
    )
    assert data["clock_mode"] in ("CALENDAR", "EXPEDITED")
    assert is_iso8601_timestamp(data["filed_at"])
    assert is_iso8601_timestamp(data["deadline_at"])
    assert isinstance(data["priority_score"], int) and 0 <= data["priority_score"] <= 100
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data["status"] in (
        "FILED", "INVESTIGATING", "REVERIFYING", "REOPENED",
        "RESOLVED_DELETE", "RESOLVED_CORRECT", "RESOLVED_VERIFY", "AUTO_DELETED",
    )


def assert_reverification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dispute_id"])
    assert is_valid_uuid(data["furnisher_id"])
    assert data["status"] in ("PENDING", "RESPONDED", "EXPIRED", "CANCELLED")
    if data.get("response_type") is not None:
        assert data["response_type"] in ("DELETE", "MODIFY", "VERIFY")


def assert_security_freeze(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["credit_file_id"])
    assert data["freeze_type"] in ("LOCK", "FREEZE")
    assert is_iso8601_timestamp(data["effective_at"])
    assert data["status"] in ("ACTIVE", "LIFTED")


def assert_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dispute_id"])
    assert is_valid_uuid(data["consumer_id"])
    assert data["agency"] in ("CFPB", "STATE_AG")
    assert isinstance(data["narrative"], str)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "UPHELD", "DISMISSED")


def assert_notification(data: dict):
    _assert_append_only_common(data)
    assert is_valid_uuid(data["credit_file_id"])
    assert data["subject_type"] in ("DISPUTE", "SECURITY_FREEZE", "REGULATORY_COMPLAINT", "TRADELINE")
    assert is_iso8601_timestamp(data["dispatched_at"])


def assert_reage_event(data: dict):
    _assert_append_only_common(data)
    assert is_valid_uuid(data["tradeline_id"])
    assert isinstance(data["was_violation"], bool)


def find_notification(notifications: list, event_code: str, subject_id: str = None):
    """Return the first notification matching event_code (and subject_id if given)."""
    for n in notifications:
        if n.get("event_code") != event_code:
            continue
        if subject_id is not None and n.get("subject_id") != subject_id:
            continue
        return n
    return None
