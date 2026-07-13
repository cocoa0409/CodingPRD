"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_plan(data: dict):
    _assert_common(data)
    assert data["life_status"] in ("ACTIVE", "INCAPACITATED", "DECEASED")
    assert isinstance(data["completeness_pct"], int) and 0 <= data["completeness_pct"] <= 100
    assert isinstance(data["seats_used"], int) and data["seats_used"] >= 0
    assert isinstance(data["seats_available"], int) and data["seats_available"] >= 0


def assert_vault_item(data: dict):
    _assert_common(data)
    assert data["kind"] in ("ACCOUNT", "ASSET", "DOCUMENT")
    assert data["status"] in ("DRAFT", "SEALED", "RELEASED", "ARCHIVED")
    assert data["sensitivity"] in ("LOW", "MEDIUM", "HIGH")
    if data["kind"] == "ASSET":
        assert data.get("net_value_cents") is not None
    else:
        assert data.get("net_value_cents") is None


def assert_deputy(data: dict):
    _assert_common(data)
    assert data["status"] in ("INVITED", "ACCEPTED", "REVOKED")
    assert data["deputy_role"] in ("EXECUTOR", "HEALTHCARE_PROXY", "GUARDIAN", "VIEWER")


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert data["status"] in ("NOMINATED", "VESTED", "REMOVED")
    assert isinstance(data["allocated_value_cents"], int) and data["allocated_value_cents"] >= 0


def assert_directive(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_REVISION", "SUPERSEDED", "REVOKED")
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1


def assert_release_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "VERIFIED", "APPROVED", "GRANTED", "DENIED", "EXPIRED")
    assert isinstance(data["approval_count"], int) and data["approval_count"] >= 0


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("TRIALING", "ACTIVE", "PAST_DUE", "CANCELED")
    assert data["tier"] in ("FREE", "PLUS", "FAMILY")


def assert_share(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")


def assert_integration(data: dict):
    _assert_common(data)
    assert data["sync_status"] in ("LINKED", "SYNCING")


def assert_review_reminder(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "DUE", "OVERDUE", "COMPLETED", "DISMISSED")


def assert_seat_invariant(plan: dict, seat_limit: int):
    """seats_used + seats_available == seat_limit, and seats_available never negative."""
    assert plan["seats_available"] >= 0
    assert plan["seats_used"] + plan["seats_available"] == seat_limit, (
        f"seat conservation broken: used {plan['seats_used']} + available "
        f"{plan['seats_available']} != limit {seat_limit}"
    )
