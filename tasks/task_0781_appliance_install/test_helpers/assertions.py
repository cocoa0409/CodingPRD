"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_retailer(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED"), f"bad retailer status {data.get('status')}"
    assert isinstance(data["commission_rate_bps"], int)
    assert isinstance(data["settlement_balance_cents"], int)


def assert_service_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["max_concurrent_appointments"], int)
    assert isinstance(data["coverage_active"], bool)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)


def assert_pro(data: dict):
    _assert_common(data)
    assert isinstance(data["skills"], list) and len(data["skills"]) >= 1
    for counter in ("pending_payout_cents", "reserved_slot_count", "rating_sum", "rating_count"):
        assert isinstance(data[counter], int), f"{counter} must be int"


def assert_pro_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING_REVIEW", "APPROVED", "REJECTED", "SUSPENDED", "EXPIRED",
    ), f"bad application status {data.get('status')}"


def assert_install_task(data: dict):
    _assert_common(data)
    assert data["category"] in ("TV_MOUNT", "APPLIANCE", "SMART_DEVICE")
    assert data["required_skill"] in ("TV_MOUNT", "APPLIANCE", "SMART_DEVICE")
    assert isinstance(data["base_price_cents"], int)


def assert_addon(data: dict):
    _assert_common(data)
    assert data["category"] in ("TV_MOUNT", "APPLIANCE", "SMART_DEVICE")
    assert isinstance(data["price_cents"], int)


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "DISPATCHED", "IN_PROGRESS",
        "COMPLETED", "REDO_REQUESTED", "CANCELLED", "CLOSED",
    ), f"bad work order status {data.get('status')}"
    assert isinstance(data["quoted_price_cents"], int)
    assert isinstance(data["final_price_cents"], int)
    assert isinstance(data["redo_count"], int)


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED")


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["line_billed_cents"], int)


def assert_payout_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "HELD", "RELEASED", "REVERSED")
    assert isinstance(data["payout_cents"], int)


def assert_settlement_entry(data: dict):
    _assert_common(data)
    assert data["entry_type"] in ("CHARGE", "REVERSAL")
    assert data["status"] in ("PENDING", "SETTLED", "REVERSED")
    assert isinstance(data["amount_cents"], int)


def assert_rating(data: dict):
    """Rating is append-only (PRD §2.4): id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "rating id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert 1 <= data["stars"] <= 5, "stars must be 1..5"
