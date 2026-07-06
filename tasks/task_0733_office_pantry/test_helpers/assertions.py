"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields_full(data: dict):
    """Fields present on entities with common_fields=true: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def _assert_common_fields_append_only(data: dict):
    """Fields present on append-only entities: id, created_at only (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_client(data: dict):
    _assert_common_fields_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["headcount"], int) and data["headcount"] >= 1
    assert isinstance(data["credit_balance_cents"], int) and data["credit_balance_cents"] >= 0


def assert_plan(data: dict):
    _assert_common_fields_full(data)
    assert data["billing_type"] in ("PER_EMPLOYEE", "FLAT")
    assert isinstance(data["tier"], str) and len(data["tier"]) > 0


def assert_subscription(data: dict):
    _assert_common_fields_full(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "CANCELLED")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["plan_version_snapshot"], int)
    assert isinstance(data["cumulative_active_days"], int)


def assert_location(data: dict):
    _assert_common_fields_full(data)
    assert data["kind"] in ("PANTRY", "FRIDGE", "MICRO_MARKET")
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 1
    assert isinstance(data["service_fee_bps"], int)
    assert 0 <= data["service_fee_bps"] <= 10000


def assert_product(data: dict):
    _assert_common_fields_full(data)
    assert data["category"] in ("SNACK", "BEVERAGE", "MEAL", "CANDY")
    assert isinstance(data["dietary_flags"], list)
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["requires_refrigeration"], bool)


def assert_par_level(data: dict):
    _assert_common_fields_full(data)
    assert isinstance(data["par_units"], int) and data["par_units"] >= 0


def assert_rotation_cycle(data: dict):
    _assert_common_fields_full(data)
    assert data["status"] in ("OPEN", "CLOSED", "INVALIDATED")
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])


def assert_delivery(data: dict):
    _assert_common_fields_full(data)
    assert data["status"] in (
        "SCHEDULED", "EN_ROUTE", "DELIVERED", "DISPUTED", "FINALIZED", "CANCELLED"
    )
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data.get("provisional_cents", 0), int)
    assert isinstance(data.get("final_cents", 0), int)
    assert isinstance(data.get("dispute_credit_cents", 0), int)


def assert_delivery_line(data: dict):
    _assert_common_fields_full(data)
    assert isinstance(data["planned_units"], int) and data["planned_units"] >= 0
    # actual_units may be null before being reported
    if data.get("actual_units") is not None:
        assert isinstance(data["actual_units"], int)
        assert 0 <= data["actual_units"] <= data["planned_units"]
    assert isinstance(data["unit_price_cents_snapshot"], int)
    assert isinstance(data["service_fee_bps_snapshot"], int)


def assert_invoice(data: dict):
    _assert_common_fields_full(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "DEFAULT")
    assert data["dispute_status"] in ("CLEAN", "UNDER_DISPUTE", "RESOLVED")
    assert isinstance(data["subscription_fee_cents"], int)
    assert isinstance(data["consumption_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] >= 0
    # Total must equal sub + consumption - credit
    assert data["total_cents"] == (
        data["subscription_fee_cents"] + data["consumption_cents"] - data["credit_applied_cents"]
    )


def assert_preference(data: dict):
    _assert_common_fields_append_only(data)
    assert isinstance(data["dietary_flag"], str) and len(data["dietary_flag"]) > 0
    # Append-only: MUST NOT have updated_at/version
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "Preference is append-only; must not have updated_at"
    assert "version" not in data or data.get("version") is None, \
        "Preference is append-only; must not have version"


def assert_feedback(data: dict):
    _assert_common_fields_append_only(data)
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    # Append-only
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "Feedback is append-only; must not have updated_at"
    assert "version" not in data or data.get("version") is None, \
        "Feedback is append-only; must not have version"


def assert_delivery_money_conservation(delivery: dict):
    """PRD §3.6 invariant: provisional_cents == final_cents + dispute_credit_cents
    on any dispute-resolved delivery."""
    assert delivery["provisional_cents"] == (
        delivery["final_cents"] + delivery["dispute_credit_cents"]
    ), (
        f"Money conservation broken: provisional={delivery['provisional_cents']}, "
        f"final={delivery['final_cents']}, credit={delivery['dispute_credit_cents']}"
    )
