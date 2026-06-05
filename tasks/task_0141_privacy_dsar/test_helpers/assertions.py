"""Entity assertions and domain invariant checkers for the Privacy DSAR API."""
from datetime import datetime
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _to_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional seconds and a
    trailing Z) into a timezone-aware datetime for instant comparison."""
    assert isinstance(ts, str) and ts, f"expected an ISO 8601 timestamp, got {ts!r}"
    normalized = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def assert_instant_equals(actual: str, expected: str, label: str = "instant"):
    """Compare two ISO 8601 instants for equality of the underlying moment,
    tolerant of fractional-second formatting (e.g. '...09:00:00Z' vs
    '...09:00:00.000Z')."""
    a, e = _to_instant(actual), _to_instant(expected)
    assert a == e, f"{label}: expected {expected}, got {actual}"

_DATA_CATEGORIES = ["IDENTITY", "FINANCIAL", "BEHAVIORAL", "CONTACT", "HEALTH"]
_DSAR_STATUSES = [
    "PENDING_VERIFICATION", "VERIFICATION_REJECTED", "DISCOVERY",
    "UNDER_REVIEW", "FULFILLING", "CLOSED_FULFILLED", "CLOSED_REJECTED",
    "CLOSED_EXPIRED",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_controller(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["jurisdiction"] in ("GDPR", "CCPA"), f"bad jurisdiction {data['jurisdiction']!r}"
    assert isinstance(data["dpo_email"], str) and len(data["dpo_email"]) > 0
    assert isinstance(data["open_request_count"], int) and data["open_request_count"] >= 0


def assert_data_subject(data: dict):
    _assert_common(data)
    assert isinstance(data["controller_id"], str)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["jurisdiction_residency"] in ("EU", "CALIFORNIA", "OTHER")
    assert isinstance(data["known_record_count"], int) and data["known_record_count"] >= 0


def assert_processor(data: dict):
    _assert_common(data)
    assert isinstance(data["controller_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["notify_email"], str)
    assert isinstance(data["sla_ack_hours"], int) and data["sla_ack_hours"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_consent_record(data: dict):
    _assert_common(data)
    assert isinstance(data["data_subject_id"], str)
    assert data["purpose"] in ("MARKETING", "ANALYTICS", "SALE_OF_DATA", "ESSENTIAL")
    assert data["state"] in ("GRANTED", "WITHDRAWN")
    if data["state"] == "GRANTED":
        assert data.get("withdrawn_at") is None, "withdrawn_at must be null while GRANTED"
    else:
        assert is_iso8601_timestamp(data.get("withdrawn_at", "")), "withdrawn_at must be set when WITHDRAWN"


def assert_legal_hold(data: dict):
    _assert_common(data)
    assert isinstance(data["controller_id"], str)
    assert isinstance(data["data_subject_id"], str)
    assert isinstance(data["matter_reference"], str)
    assert isinstance(data["data_categories"], list) and len(data["data_categories"]) >= 1
    for cat in data["data_categories"]:
        assert cat in _DATA_CATEGORIES, f"bad data_category {cat!r}"
    assert data["state"] in ("ACTIVE", "LIFTED")


def assert_dsar_request(data: dict):
    _assert_common(data)
    assert isinstance(data["controller_id"], str)
    assert isinstance(data["data_subject_id"], str)
    assert data["request_type"] in ("ACCESS", "DELETION", "OPT_OUT")
    assert is_iso8601_timestamp(data["received_at"]), "received_at must be ISO 8601"
    assert data["status"] in _DSAR_STATUSES, f"bad status {data['status']!r}"
    assert isinstance(data["identity_attempts"], int) and data["identity_attempts"] >= 0
    assert isinstance(data["extension_count"], int) and 0 <= data["extension_count"] <= 1
    assert is_iso8601_timestamp(data["deadline_at"]), "deadline_at must be ISO 8601"
    assert isinstance(data["business_days_remaining"], int) and data["business_days_remaining"] >= 0
    assert isinstance(data["discovery_finding_count"], int) and data["discovery_finding_count"] >= 0
    assert isinstance(data["fulfillment_progress_pct"], (int, float))
    assert 0.0 <= float(data["fulfillment_progress_pct"]) <= 100.0


def assert_discovery_finding(data: dict):
    _assert_common(data)
    assert isinstance(data["dsar_request_id"], str)
    assert isinstance(data["processor_id"], str)
    assert data["data_category"] in _DATA_CATEGORIES
    assert isinstance(data["record_count"], int) and data["record_count"] >= 1
    assert data["confidence"] in ("EXACT", "PROBABLE")
    assert data["state"] in ("PENDING", "CONFIRMED", "DISMISSED")


def assert_exemption_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["dsar_request_id"], str)
    assert data["data_category"] in _DATA_CATEGORIES
    assert data["basis"] in ("LEGAL_OBLIGATION", "FREEDOM_OF_EXPRESSION", "LEGAL_HOLD", "TRADE_SECRET")
    assert data["state"] in ("ASSERTED", "UPHELD", "OVERRULED")


def assert_fulfillment_item(data: dict):
    _assert_common(data)
    assert isinstance(data["dsar_request_id"], str)
    assert isinstance(data["discovery_finding_id"], str)
    assert isinstance(data["processor_id"], str)
    assert data["data_category"] in _DATA_CATEGORIES
    assert data["action"] in ("DISCLOSE", "ERASE", "SUPPRESS")
    assert isinstance(data["record_count"], int) and data["record_count"] >= 1
    assert data["state"] in ("QUEUED", "DISPATCHED", "COMPLETED", "BLOCKED", "SKIPPED_EXEMPT")


def assert_processor_notification(data: dict):
    _assert_common(data)
    assert isinstance(data["fulfillment_item_id"], str)
    assert isinstance(data["processor_id"], str)
    assert is_iso8601_timestamp(data["dispatched_at"]), "dispatched_at must be ISO 8601"
    assert is_iso8601_timestamp(data["ack_deadline_at"]), "ack_deadline_at must be ISO 8601"
    assert data["state"] in ("SENT", "ACKNOWLEDGED", "OVERDUE")


def assert_audit_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "audit id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # Append-only: no updated_at / version.
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "audit events are append-only and must not carry updated_at"
    assert "version" not in data or data.get("version") is None, \
        "audit events are append-only and must not carry version"
