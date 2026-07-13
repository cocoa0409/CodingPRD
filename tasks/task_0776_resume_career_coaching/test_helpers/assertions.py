"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_ORDER_STATES = {"INTAKE", "IN_PRODUCTION", "READY", "DELIVERED", "CLOSED", "REFUNDED"}
_DELIVERABLE_STATES = {"PENDING", "DRAFTED", "IN_REVISION", "APPROVED", "CANCELLED"}
_REVISION_STATES = {"OPEN", "ADDRESSED", "WITHDRAWN"}
_SESSION_STATES = {"SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"}
_ADDON_STATES = {"PENDING", "CHARGED", "CANCELLED"}
_CLAIM_STATES = {"SUBMITTED", "APPROVED", "REJECTED"}


def _assert_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_client(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"ACTIVE", "INACTIVE"}


def assert_coach(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"ACTIVE", "INACTIVE"}
    assert isinstance(data["buffer_minutes"], int)


def assert_package_plan(data: dict):
    _assert_lightweight(data)
    assert data["tier"] in {"BASIC", "PRO", "EXECUTIVE"}
    assert isinstance(data["base_price_cents"], int)


def assert_order(data: dict):
    _assert_versioned(data)
    assert data["status"] in _ORDER_STATES, f"unexpected order status {data['status']!r}"
    assert isinstance(data["amount_charged_cents"], int)
    assert isinstance(data["amount_refunded_cents"], int)
    assert data["net_collected_cents"] == data["amount_charged_cents"] - data["amount_refunded_cents"], (
        "net_collected_cents must equal amount_charged_cents - amount_refunded_cents"
    )


def assert_deliverable(data: dict):
    _assert_versioned(data)
    assert data["status"] in _DELIVERABLE_STATES
    assert data["type"] in {"RESUME", "LINKEDIN", "COVER_LETTER"}


def assert_revision_request(data: dict):
    _assert_versioned(data)
    assert data["status"] in _REVISION_STATES
    assert isinstance(data["billable"], bool)


def assert_coaching_session(data: dict):
    _assert_versioned(data)
    assert data["status"] in _SESSION_STATES
    assert data["session_type"] in {"COACHING", "INTERVIEW_PREP"}
    assert isinstance(data["billable"], bool)
    assert isinstance(data["fee_cents"], int)


def assert_addon(data: dict):
    _assert_versioned(data)
    assert data["status"] in _ADDON_STATES
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["auto_generated"], bool)


def assert_guarantee_claim(data: dict):
    _assert_versioned(data)
    assert data["status"] in _CLAIM_STATES
    assert data["claim_type"] in {"SATISFACTION", "INTERVIEW"}


def assert_payment(data: dict):
    _assert_lightweight(data)
    assert data["type"] in {"CHARGE", "REFUND"}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_ats_scan(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["strict_score"], int)
    assert isinstance(data["semantic_score"], int)


def find_addon_by_source_ref(addons: list, source_ref: str) -> dict:
    """Return the AddOn whose source_ref matches, or None."""
    for a in addons:
        if a.get("source_ref") == source_ref:
            return a
    return None


def find_payment(payments: list, ptype: str, reason: str, amount_cents: int) -> dict:
    """Return a Payment matching type/reason/amount, or None."""
    for p in payments:
        if p.get("type") == ptype and p.get("reason") == reason and p.get("amount_cents") == amount_cents:
            return p
    return None
