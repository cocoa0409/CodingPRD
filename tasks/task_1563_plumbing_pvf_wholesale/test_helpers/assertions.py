"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9–§2.11, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """System-managed properties carried by every resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_branch(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("PIPE", "VALVE", "FITTING", "FIXTURE")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 1
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert isinstance(data["cubes_per_unit"], int) and data["cubes_per_unit"] >= 0
    assert isinstance(data["is_cut_to_order"], bool)
    assert isinstance(data["is_special_order"], bool)


def assert_account(data: dict):
    _assert_common(data)
    assert data["pricing_tier"] in ("STANDARD", "SILVER", "GOLD", "PLATINUM")
    assert data["terms"] in ("COD", "NET_15", "NET_30")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["forward_exposure_cents"], int)
    assert isinstance(data["available_credit_cents"], int)


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["manufacturer_name"], str) and data["manufacturer_name"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    assert data["status"] in ("ACTIVE", "CLOSED", "SETTLED")
    assert isinstance(data["purchases_cents"], int)


def assert_stock(data: dict):
    _assert_common(data)
    assert isinstance(data["on_hand"], int)
    assert isinstance(data["reserved"], int)
    assert isinstance(data["available"], int)
    assert_stock_invariants(data)


def assert_stock_invariants(data: dict):
    """Inventory invariant (PRD §2.10): available == on_hand - reserved at all times."""
    assert data["available"] == data["on_hand"] - data["reserved"], (
        f"available {data['available']} != on_hand {data['on_hand']} - reserved {data['reserved']}"
    )


def assert_receipt(data: dict):
    _assert_common(data)
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] == "POSTED"


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["method"] in ("CHECK", "ACH", "CARD")
    assert data["status"] == "APPLIED"


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "AWARDED", "REVISED", "LOST", "EXPIRED", "CONVERTED",
    )
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["freight_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_sheet(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PRESENTED", "APPROVED", "REVISED", "ORDERED")
    assert isinstance(data["selections"], list) and len(data["selections"]) >= 1


def assert_order(data: dict):
    _assert_common(data)
    assert data["source"] in ("COUNTER", "PROJECT", "SHOWROOM")
    assert data["payment_status"] in ("UNINVOICED", "INVOICED", "PAID")
    assert data["fulfillment_status"] in (
        "DRAFT", "OPEN", "PICKING", "STAGED", "DISPATCHED",
        "DELIVERED", "PICKED_UP", "CANCELLED",
    )
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["freight_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["cubes_total"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["qty_ordered"], int) and data["qty_ordered"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert data["price_source"] in (
        "COUNTER_TIER", "PROMO", "MANUAL_OVERRIDE", "QUOTE_LOCKED", "SHOWROOM_LIST",
    )
    assert isinstance(data["qty_allocated"], int)
    assert isinstance(data["qty_fulfilled"], int)
    assert isinstance(data["qty_returned"], int)
    assert data["status"] in ("OPEN", "ALLOCATED", "BACKORDERED", "FILLED", "CANCELLED")
    assert data["substitute_status"] in ("NONE", "PROPOSED", "APPROVED", "REJECTED")
    assert isinstance(data["line_total_cents"], int)


def assert_kit(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ASSEMBLED", "STAGED", "RELEASED")
    assert isinstance(data["floor_label"], str) and data["floor_label"]


def assert_slot(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["capacity_cubes"], int) and data["capacity_cubes"] >= 1
    assert isinstance(data["booked_cubes"], int) and data["booked_cubes"] >= 0
    assert data["status"] in ("OPEN", "FULL", "COMPLETED", "CANCELLED")


def assert_return(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CREDITED")
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1


def assert_credit_exposure(data: dict):
    """Computed credit-exposure read shape (PRD §2.9/§3.3)."""
    assert isinstance(data["account_id"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["statement_balance_cents"], int)
    assert isinstance(data["forward_exposure_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD", "SUSPENDED")
    assert (
        data["available_credit_cents"]
        == data["credit_limit_cents"] - data["forward_exposure_cents"]
    ), "available_credit_cents must equal credit_limit_cents - forward_exposure_cents"


def assert_job_costing(data: dict):
    """Computed job-costing read shape (PRD §3.3)."""
    assert isinstance(data["job_name"], str)
    assert isinstance(data["provisional_cost_cents"], int)
    assert isinstance(data["final_cost_cents"], int)
    assert isinstance(data["order_count"], int)
    assert isinstance(data["line_count"], int)
