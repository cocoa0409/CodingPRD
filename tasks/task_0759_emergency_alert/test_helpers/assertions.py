"""Entity assertions and domain invariant checkers for the Emergency-Alert API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_LANGS = ["EN", "ES", "ZH", "VI"]
_SEVERITIES = ["INFO", "ADVISORY", "WARNING", "CRITICAL"]
_CHANNEL_TYPES = ["SMS", "VOICE", "EMAIL", "IPAWS"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_contact(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["primary_language"] in _LANGS
    assert isinstance(data["tty_required"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DELETED"]


def assert_channel(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contact_id", "")), "contact_id must be a UUID"
    assert data["channel_type"] in _CHANNEL_TYPES
    assert isinstance(data["address"], str)
    assert isinstance(data["tty_capable"], bool)
    assert data["opt_in_status"] in ["PENDING", "CONFIRMED", "OPTED_OUT"]


def assert_group(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["member_count"], int)


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contact_id", "")), "contact_id must be a UUID"
    assert data["subscription_type"] in ["GROUP", "GEO"]
    assert data["status"] in ["ACTIVE", "CANCELLED"]


def assert_template(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["default_severity"] in _SEVERITIES
    assert isinstance(data["body_by_language"], dict)
    assert data["status"] in ["DRAFT", "PUBLISHED", "ARCHIVED"]


def assert_alert(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert data["severity"] in _SEVERITIES
    assert isinstance(data["channels"], list)
    assert data["target_type"] in ["GROUP", "GEO"]
    assert data["status"] in [
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "DISPATCHING", "SENT", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["revision_count"], int)


def assert_localization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("alert_id", "")), "alert_id must be a UUID"
    assert data["language"] in _LANGS
    assert isinstance(data["message_text"], str)
    assert isinstance(data["segment_count"], int)


def assert_notification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("alert_id", "")), "alert_id must be a UUID"
    assert is_valid_uuid(data.get("contact_id", "")), "contact_id must be a UUID"
    assert data["channel_type"] in _CHANNEL_TYPES
    assert data["delivery_status"] in [
        "QUEUED", "SENT", "DELIVERED", "FAILED", "RETRYING", "EXHAUSTED", "SUPPRESSED",
    ]
    assert data["receipt_status"] in ["NONE", "ACKNOWLEDGED"]
    assert isinstance(data["attempt_count"], int)


def assert_gateway(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["channel_type"] in _CHANNEL_TYPES
    assert isinstance(data["capacity_per_window"], int)
    assert data["status"] in ["ONLINE", "OFFLINE"]
    assert isinstance(data["window_count"], int)


def assert_maintenance_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("gateway_id", "")), "gateway_id must be a UUID"
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])


def assert_drill(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("group_id", "")), "group_id must be a UUID"
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
