"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AllocationPolicy,
    AllocationStatus,
    BillingStatus,
    CommitMode,
    ConductorMetal,
    CustomerCreditStatus,
    DeliveryRunStatus,
    FulfillmentStatus,
    OrderLineAllocationStatus,
    PutUp,
    QuoteStatus,
    QuoteVoidReason,
    ReelHandling,
    ReelStatus,
    ReelType,
)


def _members(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every persisted resource carries a UUID id, an ISO 8601 created_at,
    an updated_at in the same format and an integer version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID string with no type prefix, got "
        f"{data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{entity_name}.version starts at 1"


def assert_branch(data: dict):
    assert_common_fields(data, "Branch")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str)
    assert isinstance(data["concurrent_cut_capacity"], int)
    assert data["concurrent_cut_capacity"] >= 1
    assert isinstance(data["delivery_surcharge_cents"], int)
    assert data["delivery_surcharge_cents"] >= 0
    assert data["scrap_ft_ytd"] >= 0


def assert_customer(data: dict):
    assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["open_balance_cents"], int)
    assert isinstance(data["deposit_liability_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert data["credit_status"] in _members(CustomerCreditStatus)
    assert_customer_credit_invariants(data)


def assert_customer_credit_invariants(data: dict):
    """available_credit_cents is always the credit limit less the open balance,
    and is explicitly permitted to go negative (PRD §3.1)."""
    assert data["available_credit_cents"] == (
        data["credit_limit_cents"] - data["open_balance_cents"]
    ), (
        "available_credit_cents must equal credit_limit_cents - "
        f"open_balance_cents, got {data['available_credit_cents']} for limit "
        f"{data['credit_limit_cents']} and balance {data['open_balance_cents']}"
    )
    assert data["deposit_liability_cents"] >= 0


def assert_product(data: dict):
    assert_common_fields(data, "CableProduct")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["conductor_metal"] in _members(ConductorMetal)
    assert data["copper_lbs_per_1000ft"] >= 0
    assert data["base_price_cents_per_ft"] >= 0
    assert data["min_cut_length_ft"] >= 25
    assert data["cut_charge_cents"] >= 0
    assert data["reel_deposit_cents"] >= 0
    assert data["master_reel_length_ft"] > 0
    assert data["reel_weight_lbs"] > 0
    assert isinstance(data["allowed_put_ups"], list) and data["allowed_put_ups"]
    for put_up in data["allowed_put_ups"]:
        assert put_up in _members(PutUp)
    if data["conductor_metal"] == ConductorMetal.ALUMINUM.value:
        assert data["copper_lbs_per_1000ft"] == 0, (
            "copper_lbs_per_1000ft must be 0 whenever conductor_metal is ALUMINUM"
        )


def assert_copper_index_entry(data: dict):
    """A published copper index entry is an immutable market record: it carries
    only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "CopperIndexEntry.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, (
        "A published copper index entry has no updated_at field"
    )
    assert "version" not in data, (
        "A published copper index entry has no version field"
    )
    assert isinstance(data["effective_date"], str)
    assert data["price_cents_per_lb"] > 0
    assert isinstance(data["published_by_user_id"], str)
    assert isinstance(data["voided_quote_count"], int)
    assert data["voided_quote_count"] >= 0


def assert_truck(data: dict):
    assert_common_fields(data, "Truck")
    assert is_valid_uuid(data["branch_id"])
    assert isinstance(data["truck_code"], str)
    assert isinstance(data["has_boom_lift"], bool)
    assert data["max_reel_slots"] >= 1


def assert_reel(data: dict):
    assert_common_fields(data, "Reel")
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["branch_id"])
    assert data["reel_type"] in _members(ReelType)
    assert data["status"] in _members(ReelStatus)
    assert isinstance(data["lot_code"], str)
    assert data["nominal_length_ft"] > 0
    assert_reel_footage_invariants(data)


def assert_reel_footage_invariants(data: dict):
    """available_length_ft is always current_length_ft less
    allocated_length_ft (PRD §3.6)."""
    assert data["current_length_ft"] >= 0
    assert data["allocated_length_ft"] >= 0
    assert data["scrap_ft"] >= 0
    assert data["available_length_ft"] == (
        data["current_length_ft"] - data["allocated_length_ft"]
    ), (
        "available_length_ft must equal current_length_ft - allocated_length_ft, "
        f"got {data['available_length_ft']} for current "
        f"{data['current_length_ft']} and allocated {data['allocated_length_ft']}"
    )


def assert_quote(data: dict):
    assert_common_fields(data, "Quote")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["branch_id"])
    assert data["status"] in _members(QuoteStatus)
    assert isinstance(data["created_by_user_id"], str)
    if data.get("void_reason") is not None:
        assert data["void_reason"] in _members(QuoteVoidReason)
    for field in (
        "line_subtotal_cents",
        "physical_reel_count",
        "gross_freight_cents",
        "rebate_cents",
        "freight_cents",
        "quoted_total_cents",
        "deposit_quoted_cents",
    ):
        assert isinstance(data[field], int), f"Quote.{field} must be whole cents"


def assert_quote_line(data: dict):
    assert_common_fields(data, "QuoteLine")
    assert is_valid_uuid(data["quote_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["put_up"] in _members(PutUp)
    assert data["line_number"] >= 1
    assert data["requested_length_ft"] > 0
    assert 1 <= data["parallel_set_size"] <= 4
    for field in (
        "metal_cents",
        "base_cents",
        "cut_charge_cents_total",
        "deposit_cents_total",
        "quoted_extended_cents",
    ):
        assert isinstance(data[field], int), f"QuoteLine.{field} must be whole cents"


def assert_sales_order(data: dict):
    assert_common_fields(data, "SalesOrder")
    assert is_valid_uuid(data["quote_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["branch_id"])
    assert data["fulfillment_status"] in _members(FulfillmentStatus)
    assert data["billing_status"] in _members(BillingStatus)
    assert data["allocation_policy"] in _members(AllocationPolicy)
    assert isinstance(data["deposit_charged_cents"], int)
    assert isinstance(data["deposit_credited_cents"], int)


def assert_order_line(data: dict):
    assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data["sales_order_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["put_up"] in _members(PutUp)
    assert data["allocation_status"] in _members(OrderLineAllocationStatus)
    assert isinstance(data["returnable"], bool)
    assert data["returnable"] == (data["put_up"] == PutUp.MASTER_REEL.value), (
        "returnable is true exactly when put_up is MASTER_REEL"
    )
    assert data["required_length_ft"] == (
        data["billable_length_ft"] * data["parallel_set_size"]
    ), "required_length_ft is billable_length_ft multiplied by parallel_set_size"


def assert_allocation(data: dict):
    assert_common_fields(data, "Allocation")
    assert is_valid_uuid(data["order_line_id"])
    assert is_valid_uuid(data["sales_order_id"])
    assert is_valid_uuid(data["reel_id"])
    assert data["status"] in _members(AllocationStatus)
    if data.get("commit_mode") is not None:
        assert data["commit_mode"] in _members(CommitMode)
    assert data["sequence_no"] >= 1
    assert data["length_ft"] > 0
    assert isinstance(data["cut_charge_applied_cents"], int)


def assert_delivery_run(data: dict):
    assert_common_fields(data, "DeliveryRun")
    assert is_valid_uuid(data["sales_order_id"])
    assert is_valid_uuid(data["truck_id"])
    assert is_valid_uuid(data["branch_id"])
    assert data["status"] in _members(DeliveryRunStatus)
    assert data["reel_handling"] in _members(ReelHandling)
    assert isinstance(data["jobsite_address"], str)
    assert isinstance(data["jobsite_has_forklift"], bool)
    assert data["heaviest_reel_lbs"] >= 0


def assert_reel_is_fresh_master(data: dict):
    """A received reel is a master reel with everything at its start value
    (PRD §3.6)."""
    assert data["reel_type"] == ReelType.MASTER.value
    assert data["parent_reel_id"] is None
    assert data["current_length_ft"] == data["nominal_length_ft"]
    assert data["allocated_length_ft"] == 0
    assert data["scrap_ft"] == 0
    assert data["delivered_sales_order_id"] is None
    assert data["delivered_at"] is None
    assert data["status"] == ReelStatus.IN_STOCK.value


def assert_success_envelope(body: dict, expected_response_type: str = "object"):
    """The fixed success envelope of PRD §2.2."""
    assert set(["meta", "response_type", "data"]).issubset(body.keys()), (
        f"Response body must carry meta, response_type and data; got {sorted(body)}"
    )
    assert body["response_type"] == expected_response_type
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Compare two ISO 8601 UTC timestamps as instants, so a trailing
    fractional-second component does not change the verdict."""
    from datetime import datetime

    def parse(value):
        assert isinstance(value, str) and value, f"{label} must be a string"
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert parse(actual) == parse(expected_iso), (
        f"{label}: expected the instant {expected_iso}, got {actual}"
    )
