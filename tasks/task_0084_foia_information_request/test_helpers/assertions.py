"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

FEE_CATEGORIES = ["COMMERCIAL", "EDUCATIONAL", "NEWS_MEDIA", "OTHER"]
REQUEST_STATUSES = [
    "SUBMITTED", "PERFECTED", "PROCESSING", "AWAITING_PAYMENT",
    "GRANTED", "PARTIALLY_GRANTED", "DENIED", "GLOMAR_INVOKED", "WITHDRAWN",
]
DEADLINE_STATUSES = ["RUNNING", "TOLLED", "EXTENDED", "MET", "MISSED"]
FEE_PAYMENT_STATUSES = ["NONE", "DUE", "PAID", "WAIVED"]
DISPOSITIONS = ["PENDING", "RELEASABLE", "REDACTED", "WITHHELD"]
EXEMPTION_CODES = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"]
APPEAL_STATUSES = ["FILED", "UNDER_REVIEW", "AFFIRMED", "REVERSED", "REMANDED"]
OBJECTION_STATUSES = ["NOTICED", "OBJECTED", "SUSTAINED", "OVERRULED", "NO_RESPONSE"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_requester(data: dict):
    _assert_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["declared_category"] in FEE_CATEGORIES
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_officer(data: dict):
    _assert_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["badge_id"], str) and len(data["badge_id"]) > 0
    assert isinstance(data["can_invoke_glomar"], bool)


def assert_appeal_authority(data: dict):
    _assert_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["badge_id"], str) and len(data["badge_id"]) > 0


def assert_submitter(data: dict):
    _assert_versioned(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0


def assert_foia_request(data: dict):
    _assert_versioned(data)
    assert isinstance(data["requester_id"], str)
    assert isinstance(data["subject_description"], str) and len(data["subject_description"]) > 0
    assert data["status"] in REQUEST_STATUSES
    assert data["deadline_status"] in DEADLINE_STATUSES
    assert data["fee_payment_status"] in FEE_PAYMENT_STATUSES
    assert isinstance(data["expedited"], bool)
    assert isinstance(data["fee_waiver_requested"], bool)
    assert isinstance(data["fee_waiver_granted"], bool)
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"


def assert_responsive_record(data: dict):
    _assert_versioned(data)
    assert isinstance(data["request_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert isinstance(data["contains_submitter_info"], bool)
    assert data["disposition"] in DISPOSITIONS


def assert_fee_estimate(data: dict):
    _assert_versioned(data)
    assert isinstance(data["request_id"], str)
    assert isinstance(data["assessed_fee_cents"], int) and data["assessed_fee_cents"] >= 0
    assert isinstance(data["requires_advance_payment"], bool)


def assert_processing_deadline(data: dict):
    _assert_versioned(data)
    assert isinstance(data["request_id"], str)
    assert is_iso8601_timestamp(data.get("base_due_at", "")), "base_due_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("effective_due_at", "")), "effective_due_at must be ISO 8601"
    assert isinstance(data["extension_days_added"], int)
    assert isinstance(data["tolled_working_days"], int)


def assert_appeal(data: dict):
    _assert_versioned(data)
    assert isinstance(data["request_id"], str)
    assert isinstance(data["appellant_id"], str)
    assert isinstance(data["grounds"], str) and len(data["grounds"]) > 0
    assert data["status"] in APPEAL_STATUSES
    assert is_iso8601_timestamp(data.get("filed_at", "")), "filed_at must be ISO 8601"


def assert_third_party_objection(data: dict):
    _assert_versioned(data)
    assert isinstance(data["record_id"], str)
    assert isinstance(data["submitter_id"], str)
    assert isinstance(data["objection_text"], str) and len(data["objection_text"]) > 0
    assert data["status"] in OBJECTION_STATUSES


def assert_exemption(data: dict):
    # Append-only: id + created_at only; no updated_at / version.
    _assert_common(data)
    assert data["applies_to_kind"] in ("RECORD", "REQUEST")
    assert data["exemption_code"] in EXEMPTION_CODES
    assert isinstance(data["justification"], str) and len(data["justification"]) > 0


def assert_audit_event(data: dict):
    # Append-only: id + created_at only; no updated_at / version.
    _assert_common(data)
    assert isinstance(data["event_type"], str)
    assert isinstance(data["actor_role"], str)


def assert_reading_room(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_review_station(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0


def assert_reading_room_booking(data: dict):
    _assert_versioned(data)
    assert isinstance(data["room_id"], str)
    assert isinstance(data["request_id"], str)
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"


def assert_review_station_booking(data: dict):
    _assert_versioned(data)
    assert isinstance(data["station_id"], str)
    assert isinstance(data["request_id"], str)
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
