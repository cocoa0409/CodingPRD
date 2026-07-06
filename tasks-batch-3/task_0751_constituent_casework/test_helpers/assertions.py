"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_representative(data: dict):
    _assert_common(data)
    assert data["chamber"] in ("HOUSE", "SENATE")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_constituent(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PURGED")
    assert isinstance(data["contact_consent"], bool)
    assert isinstance(data["data_sharing_consent"], bool)
    assert isinstance(data["upcoming_event_count"], int)


def assert_agency(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["open_referral_count"], int)


def assert_template(data: dict):
    _assert_common(data)
    assert data["category"] in ("IMMIGRATION", "HEALTHCARE", "HOUSING", "TAX", "BENEFITS", "OTHER")
    assert isinstance(data["active"], bool)
    assert data["response_window_hours"] > 0


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "NEW", "IN_PROGRESS", "AWAITING_CONSTITUENT", "AWAITING_AGENCY",
        "RESOLVED", "CLOSED", "WITHDRAWN",
    )
    assert data["priority"] in ("LOW", "NORMAL", "HIGH", "URGENT")
    assert data["category"] in ("IMMIGRATION", "HEALTHCARE", "HOUSING", "TAX", "BENEFITS", "OTHER")
    assert is_valid_uuid(data.get("constituent_id", "")), "constituent_id must be a UUID"
    assert is_valid_uuid(data.get("representative_id", "")), "representative_id must be a UUID"


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SENT", "RESOLVED", "REJECTED", "RECALLED", "CLOSED")
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"


def assert_venue(data: dict):
    _assert_common(data)
    assert data["capacity"] >= 0


def assert_event(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in ("SCHEDULED", "CANCELLED")
    assert data["registration_status"] in ("CLOSED", "OPEN", "FULL")
    assert isinstance(data["registered_count"], int)
    assert data["capacity"] >= 0


def assert_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ("REGISTERED", "CANCELLED")
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    assert is_valid_uuid(data.get("constituent_id", "")), "constituent_id must be a UUID"


def assert_newsletter(data: dict):
    _assert_common(data)
    assert data["status"] == "SENT"
    assert isinstance(data["recipient_count"], int)
    assert isinstance(data["send_cost_cents"], int)
