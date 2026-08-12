"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §2.9)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["completed_builds_count"], int)
    assert isinstance(data["credit_balance_cents"], int)


def assert_staff_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["staff_role"] in (
        "FITTING_SPECIALIST", "REPAIR_TECHNICIAN", "INSTRUCTOR", "SHOP_MANAGER",
    )


def assert_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["bay_name"], str) and data["bay_name"]
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")
    assert isinstance(data["cleanup_buffer_minutes"], int)


def assert_lesson_package(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["total_credits"], int) and data["total_credits"] >= 1
    assert isinstance(data["credits_used"], int)
    assert isinstance(data["price_cents"], int)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")


def assert_fitting_session(data: dict):
    _assert_common(data)
    for field in ("customer_id", "bay_id", "specialist_id"):
        assert isinstance(data[field], str) and data[field]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["credit_consumed"], bool)
    assert isinstance(data["credit_refunded"], bool)


def assert_component_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["component_type"] in ("HEAD", "SHAFT", "GRIP")
    for field in ("unit_cost_cents", "msrp_cents", "stock_on_hand",
                  "stock_reserved", "consumed_total", "received_total"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_build_spec(data: dict):
    _assert_common(data)
    for field in ("customer_id", "fitting_session_id", "head_item_id",
                  "shaft_item_id", "grip_item_id"):
        assert isinstance(data[field], str) and data[field]
    assert isinstance(data["labor_cents"], int)
    assert data["status"] in (
        "DRAFT", "QUOTED", "ORDERED", "IN_BUILD", "READY", "DELIVERED", "CANCELLED",
    )


def assert_component_order(data: dict):
    _assert_common(data)
    assert isinstance(data["build_spec_id"], str) and data["build_spec_id"]
    assert data["status"] in (
        "PENDING_ALLOCATION", "ALLOCATED", "BACKORDERED", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["lines"], list) and len(data["lines"]) == 3
    for line in data["lines"]:
        assert isinstance(line["component_item_id"], str)
        assert line["required_qty"] == 1
        assert isinstance(line["allocated_qty"], int)
    assert data["required_units"] == 3


def assert_repair_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["club_description"], str)
    assert data["service_type"] in ("REGRIP", "RESHAFT", "LOFT_LIE_ADJUST")
    assert isinstance(data["rush"], bool)
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["deposit_cents"], int)
    assert data["work_status"] in (
        "QUOTED", "APPROVED", "IN_PROGRESS", "READY", "PICKED_UP", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "PAID", "REFUNDED")
    assert isinstance(data["rework_count"], int)


def assert_appraisal(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["clubs"], list) and len(data["clubs"]) >= 1
    assert data["status"] in ("SUBMITTED", "OFFERED", "DECLINED", "ACCEPTED", "EXPIRED")


def assert_listing(data: dict):
    _assert_common(data)
    assert isinstance(data["appraisal_id"], str)
    assert isinstance(data["list_price_cents"], int)
    assert data["status"] in ("LISTED", "RESERVED", "SOLD")


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["description"], str)
    assert data["coverage_pct"] in (0, 50, 100)
    assert isinstance(data["covered_estimate_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "RESOLVED")
    assert isinstance(data["appeal_count"], int)


def assert_credit_ledger_entry(data: dict):
    """Append-only entry: id + created_at present; updated_at/version absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["reason"] in (
        "TRADE_IN_ACCEPT", "BUILD_PAYMENT", "BUILD_REFUND",
        "WARRANTY_RESOLUTION", "TICKET_PAYMENT", "TICKET_REFUND",
    )


def assert_stock_conserved(item: dict):
    """PRD §2.9: stock_on_hand == received_total - stock_reserved - consumed_total."""
    expected = item["received_total"] - item["stock_reserved"] - item["consumed_total"]
    assert item["stock_on_hand"] == expected, (
        f"stock_on_hand {item['stock_on_hand']} != received {item['received_total']} "
        f"- reserved {item['stock_reserved']} - consumed {item['consumed_total']}"
    )


def assert_credit_balance_matches_ledger(customer: dict, ledger_entries: list):
    """PRD §2.8: balance is always exactly the sum of ledger amount_cents."""
    total = sum(e["amount_cents"] for e in ledger_entries)
    assert customer["credit_balance_cents"] == total, (
        f"credit_balance_cents {customer['credit_balance_cents']} != ledger sum {total}"
    )
