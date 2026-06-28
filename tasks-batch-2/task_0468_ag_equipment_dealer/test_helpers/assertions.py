"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names mirror the PRD.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_first_class(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_unit(data: dict):
    _common_first_class(data)
    assert isinstance(data["stock_number"], str) and len(data["stock_number"]) > 0
    assert data["condition"] in ("NEW", "USED")
    assert isinstance(data["model_code"], str)
    assert isinstance(data["serial_number"], str)
    assert isinstance(data["dealer_cost_cents"], int) and data["dealer_cost_cents"] >= 0
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["engine_hours"], int) and data["engine_hours"] >= 0
    assert isinstance(data["floor_planned"], bool)
    assert data["status"] in (
        "AVAILABLE", "RESERVED", "SOLD", "LEASED",
        "AUCTION_LISTED", "AUCTION_SOLD", "REPOSSESSED", "RETIRED",
    )


def assert_floor_plan_note(data: dict):
    _common_first_class(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["annual_rate_bps"], int) and data["annual_rate_bps"] > 0
    assert isinstance(data["curtailment_paid_cents"], int) and data["curtailment_paid_cents"] >= 0
    assert isinstance(data["interest_accrued_cents"], int) and data["interest_accrued_cents"] >= 0
    assert isinstance(data["days_outstanding"], int) and data["days_outstanding"] >= 0
    assert isinstance(data["curtailment_stage"], int) and 0 <= data["curtailment_stage"] <= 3
    assert data["status"] in ("DRAFT", "ACTIVE", "CURTAILMENT_DUE", "PAID_OFF", "DEFAULTED")


def assert_customer(data: dict):
    _common_first_class(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["customer_type"] in ("RETAIL", "COMMERCIAL_AG", "GOVERNMENT")
    assert data["credit_tier"] in ("PRIME", "STANDARD", "SUBPRIME")
    assert isinstance(data["tax_exempt"], bool)


def assert_trade_in(data: dict):
    _common_first_class(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["base_value_cents"], int) and data["base_value_cents"] > 0
    assert isinstance(data["appraised_value_cents"], int) and data["appraised_value_cents"] >= 0
    assert data["condition_grade"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert data["status"] in ("APPRAISED", "OFFERED", "ACCEPTED", "DECLINED")


def assert_deal(data: dict):
    _common_first_class(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["deal_type"] in ("SALE", "LEASE", "AUCTION_SALE")
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] > 0
    assert isinstance(data["lease_term_months"], int) and data["lease_term_months"] >= 0
    assert isinstance(data["trade_allowance_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["status"] in ("QUOTED", "APPROVED", "FUNDED", "DELIVERED", "UNWOUND")


def assert_auction_lot(data: dict):
    _common_first_class(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["reserve_price_cents"], int) and data["reserve_price_cents"] > 0
    assert isinstance(data["high_bid_cents"], int) and data["high_bid_cents"] >= 0
    assert data["status"] in ("DRAFT", "LIVE", "CLOSED_MET", "CLOSED_NO_SALE", "SETTLED")


def assert_work_order(data: dict):
    _common_first_class(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["labor_rate_cents"], int) and data["labor_rate_cents"] > 0
    assert isinstance(data["flat_rate_hours"], (int, float)) and data["flat_rate_hours"] >= 0
    assert isinstance(data["actual_hours"], (int, float)) and data["actual_hours"] >= 0
    assert isinstance(data["labor_charge_cents"], int)
    assert isinstance(data["parts_charge_cents"], int)
    assert isinstance(data["total_charge_cents"], int)
    assert data["status"] in ("OPEN", "IN_PROGRESS", "AWAITING_PARTS", "CLOSED", "VOID")


def assert_part(data: dict):
    _common_first_class(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ("MECHANICAL", "FILTER", "PRECISION_AG", "TELEMATICS")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0


def assert_part_line(data: dict):
    _common_first_class(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_cents"], int)


def assert_warranty_claim(data: dict):
    _common_first_class(data)
    assert isinstance(data["unit_id"], str)
    assert data["claim_type"] in ("WARRANTY", "PIP", "RECALL")
    assert isinstance(data["claimed_cents"], int) and data["claimed_cents"] >= 0
    assert isinstance(data["approved_cents"], int) and data["approved_cents"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "PARTIAL", "DENIED", "PAID")


def assert_whole_goods_order(data: dict):
    _common_first_class(data)
    assert isinstance(data["customer_id"], str)
    assert data["season_program"] in ("EARLY_ORDER", "IN_SEASON", "LATE")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_msrp_cents"], int) and data["unit_msrp_cents"] > 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["net_price_cents"], int) and data["net_price_cents"] >= 0
    assert isinstance(data["fulfilled_qty"], int) and data["fulfilled_qty"] >= 0
    assert data["status"] in (
        "PLACED", "CONFIRMED", "PARTIAL_FULFILLED", "FULFILLED", "CANCELLED",
    )


def assert_bid(data: dict):
    """A Bid is append-only: it carries only id and created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
