"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields carried by every resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str)
    assert isinstance(data["currency"], str) and len(data["currency"]) > 0


def assert_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "CLOSED")
    assert data["tip_split_mode"] in ("EQUAL", "WEIGHTED")
    for field in ("free_grace_minutes", "hourly_rate_cents", "daily_max_cents",
                  "event_surcharge_cents", "overflow_surcharge_cents"):
        assert isinstance(data[field], int)


def assert_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["occupied_count"], int)
    assert data["occupied_count"] >= 0, "occupied_count is never negative (§2.8)"
    assert isinstance(data["is_overflow"], bool)
    assert isinstance(data["overflow_active"], bool)


def assert_attendant(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["total_liability_cents"], int)
    assert data["total_liability_cents"] >= 0


def assert_shift(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "CLOSED")
    for field in ("declared_tips_cents", "allocated_tip_cents", "liability_holdback_cents"):
        assert isinstance(data[field], int)


def assert_ticket(data: dict):
    _assert_common(data)
    assert data["park_status"] in ("PARKED", "RETRIEVED", "CLOSED")
    assert data["settlement_status"] in ("UNSETTLED", "SETTLED", "DISPUTED")
    assert isinstance(data["in_overflow"], bool)
    assert isinstance(data["quoted_fee_cents"], int)


def assert_retrieval_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "ASSIGNED", "STAGING", "READY",
                              "COMPLETED", "CANCELLED")


def assert_validation_grant(data: dict):
    _assert_common(data)
    assert data["grant_type"] in ("PERCENT", "FLAT", "FULL_COMP")
    assert data["status"] in ("APPLIED", "REVERSED")


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "APPROVED", "DENIED", "SETTLED")
    assert isinstance(data["claimed_amount_cents"], int)


def assert_reconciliation_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED")
