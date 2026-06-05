"""Entity assertions and domain invariant checkers.

Per-entity structural validators that confirm a response carries the PRD-declared
fields with the right shapes. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_quartet(data: dict):
    """id + created_at + updated_at + version — for full-quartet entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_account(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["service_address"], str)
    assert data["rate_class"] in ("RESIDENTIAL", "COMMERCIAL_SMALL", "COMMERCIAL_LARGE")
    assert data["status"] in ("PENDING_SETUP", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["account_balance_cents"], int)


def assert_cart(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data["stream"] in ("TRASH", "RECYCLE", "ORGANICS")
    assert data["size_gallons"] in (35, 65, 96)
    assert data["status"] in ("ASSIGNED", "ACTIVE", "ON_HOLD", "RETIRED")
    assert isinstance(data["tare_weight_lbs"], (int, float))


def assert_service_plan(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["stream"] in ("TRASH", "RECYCLE", "ORGANICS")
    assert data["frequency"] in ("WEEKLY", "BIWEEKLY", "MONTHLY")
    assert isinstance(data["base_monthly_fee_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "TERMINATED")


def assert_route(data: dict):
    _assert_common_quartet(data)
    assert data["stream"] in ("TRASH", "RECYCLE", "ORGANICS")
    assert data["status"] in ("PLANNED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["total_net_weight_lbs"], (int, float))


def assert_stop(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["status"] in ("PENDING", "SERVICED", "SKIPPED")


def assert_pickup(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("stop_id", ""))
    assert is_valid_uuid(data.get("cart_id", ""))
    assert data["outcome"] in ("SCHEDULED", "COMPLETED", "MISSED", "CANCELLED")
    assert isinstance(data["contaminated"], bool)


def assert_contamination_tag(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("pickup_id", ""))
    assert data["severity"] in ("MINOR", "MAJOR", "REJECT")
    assert data["status"] in ("OPEN", "CLEARED")


def assert_invoice(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "PAID", "VOID")
    for fld in (
        "base_fee_cents", "weight_charge_cents", "contamination_surcharge_cents",
        "credit_cents", "total_cents", "diversion_penalty_cents", "balance_cents",
    ):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"


def assert_special_pickup(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["kind"] in ("BULK", "HAZARDOUS")
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["quoted_fee_cents"], int)


def assert_missed_pickup_credit(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["source_type"] in ("PICKUP", "SPECIAL_PICKUP")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "APPLIED", "VOID")


def assert_diversion_period(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["status"] in ("OPEN", "FINALIZED")
    for fld in ("diverted_weight_lbs", "total_weight_lbs", "diversion_rate_pct"):
        assert isinstance(data[fld], (int, float)), f"{fld} must be a number"


def assert_weight_ticket(data: dict):
    """WeightTicket is immutable (PRD §2.4): only id + created_at + entity fields.
    It carries NO updated_at and NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "WeightTicket must NOT expose a version field"
    assert "updated_at" not in data, "WeightTicket must NOT expose an updated_at field"
    assert is_valid_uuid(data.get("pickup_id", ""))
    assert isinstance(data["gross_weight_lbs"], (int, float))
    assert isinstance(data["net_weight_lbs"], (int, float))
    assert isinstance(data["diverted"], bool)
