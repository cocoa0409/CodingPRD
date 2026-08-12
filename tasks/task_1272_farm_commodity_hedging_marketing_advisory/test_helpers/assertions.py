"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_grower_operation(data: dict):
    _assert_common(data, "GrowerOperation")
    assert isinstance(data["name"], str) and data["name"]
    assert data["primary_commodity"] in ["CORN", "SOYBEAN", "WHEAT"]
    assert isinstance(data["crop_year"], int)
    assert data["risk_profile"] in ["CONSERVATIVE", "BALANCED", "AGGRESSIVE"]
    assert data["yield_method"] in ["APH", "TREND"]
    assert isinstance(data["over_sold_flag"], bool)


def assert_production_baseline(data: dict):
    _assert_common(data, "ProductionBaseline")
    assert is_valid_uuid(str(data["operation_id"]))
    assert isinstance(data["planted_acres"], int) and data["planted_acres"] > 0
    assert isinstance(data["aph_yield_bushels"], (int, float))
    assert isinstance(data["trend_yield_bushels"], (int, float))
    assert isinstance(data["expected_bushels_aph"], int)
    assert isinstance(data["expected_bushels_trend"], int)
    assert isinstance(data["expected_bushels"], int)
    assert data["status"] in ["PROVISIONAL", "CERTIFIED", "SUPERSEDED"]


def assert_insurance_policy(data: dict):
    _assert_common(data, "InsurancePolicy")
    assert is_valid_uuid(str(data["operation_id"]))
    assert is_valid_uuid(str(data["baseline_id"]))
    assert isinstance(data["coverage_level_pct"], (int, float))
    assert isinstance(data["projected_price"], (int, float))
    assert data["status"] in ["QUOTED", "BOUND", "CLAIM_SETTLED"]


def assert_marketing_plan(data: dict):
    _assert_common(data, "MarketingPlan")
    assert is_valid_uuid(str(data["operation_id"]))
    assert is_valid_uuid(str(data["baseline_id"]))
    assert isinstance(data["max_priced_pct"], (int, float))
    for field in (
        "expected_bushels_snapshot",
        "committed_contract_bushels",
        "uncommitted_bushels",
        "hedged_bushels",
        "priced_contract_bushels",
        "coverage_cap_bushels",
        "pending_recommendation_count",
    ):
        assert isinstance(data[field], int), f"MarketingPlan.{field} must be an integer"
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]


def assert_price_target(data: dict):
    _assert_common(data, "PriceTarget")
    assert is_valid_uuid(str(data["plan_id"]))
    assert isinstance(data["contract_month"], str)
    assert isinstance(data["target_price"], (int, float))
    assert isinstance(data["increment_bushels"], int) and data["increment_bushels"] > 0
    assert data["status"] in ["PENDING", "TRIGGERED", "FILLED", "LAPSED", "CANCELLED"]


def assert_hedge_recommendation(data: dict):
    _assert_common(data, "HedgeRecommendation")
    assert is_valid_uuid(str(data["plan_id"]))
    assert data["instrument"] in ["FUTURES_SHORT", "LONG_PUT"]
    assert isinstance(data["contract_month"], str)
    assert isinstance(data["bushels"], int) and data["bushels"] > 0
    assert isinstance(data["created_by_user_id"], str)
    assert data["status"] in ["PROPOSED", "ACCEPTED", "REJECTED", "EXECUTED", "EXPIRED"]


def assert_brokerage_position(data: dict):
    _assert_common(data, "BrokeragePosition")
    assert is_valid_uuid(str(data["recommendation_id"]))
    assert is_valid_uuid(str(data["operation_id"]))
    assert is_valid_uuid(str(data["margin_account_id"]))
    assert data["instrument"] in ["FUTURES_SHORT", "LONG_PUT"]
    assert isinstance(data["bushels"], int) and data["bushels"] > 0
    assert isinstance(data["entry_price"], (int, float))
    assert isinstance(data["initial_margin_dollars"], (int, float))
    assert isinstance(data["maintenance_margin_dollars"], (int, float))
    assert data["status"] in ["OPEN", "OFFSET", "LIQUIDATED"]


def assert_margin_account(data: dict):
    _assert_common(data, "MarginAccount")
    assert is_valid_uuid(str(data["operation_id"]))
    for field in (
        "cash_balance",
        "initial_margin_required",
        "maintenance_margin_required",
        "margin_equity",
        "margin_call_amount",
    ):
        assert isinstance(data[field], (int, float)), (
            f"MarginAccount.{field} must be numeric"
        )
    assert data["status"] in ["FUNDED", "CALL_OUTSTANDING", "RESTRICTED"]


def assert_buyer(data: dict):
    _assert_common(data, "Buyer")
    assert isinstance(data["name"], str) and data["name"]
    assert data["buyer_type"] in ["ELEVATOR", "PROCESSOR", "EXPORTER", "ETHANOL"]
    assert data["credit_rating"] in ["A", "B", "C"]
    assert data["status"] in ["PROVISIONAL", "APPROVED", "SUSPENDED"]


def assert_sales_contract(data: dict):
    _assert_common(data, "SalesContract")
    assert is_valid_uuid(str(data["operation_id"]))
    assert is_valid_uuid(str(data["plan_id"]))
    assert is_valid_uuid(str(data["buyer_id"]))
    assert data["contract_type"] in ["FLAT_PRICE", "HTA", "BASIS"]
    assert isinstance(data["bushels"], int) and data["bushels"] > 0
    assert data["pricing_status"] in ["UNPRICED", "PRICED"]
    assert data["fulfillment_status"] in [
        "OPEN",
        "PARTIALLY_DELIVERED",
        "DELIVERED",
        "CANCELLED",
        "DEFAULTED",
    ]


def assert_delivery_ticket(data: dict):
    _assert_common(data, "DeliveryTicket")
    assert is_valid_uuid(str(data["contract_id"]))
    assert isinstance(data["delivery_date"], str)
    assert isinstance(data["gross_bushels"], int) and data["gross_bushels"] > 0
    assert isinstance(data["moisture_pct"], (int, float))
    assert isinstance(data["shrink_pct"], (int, float))
    assert isinstance(data["net_bushels"], (int, float))
    assert data["status"] in ["RECORDED", "CONFIRMED", "VOIDED"]


def assert_storage_lot(data: dict):
    _assert_common(data, "StorageLot")
    assert is_valid_uuid(str(data["operation_id"]))
    assert isinstance(data["bin_id"], str) and data["bin_id"]
    assert isinstance(data["bushels"], int) and data["bushels"] > 0
    assert isinstance(data["start_date"], str)
    assert isinstance(data["planned_end_date"], str)
    assert isinstance(data["cost_per_bushel_month"], (int, float))
    assert isinstance(data["annual_interest_rate"], (int, float))
    assert data["status"] in ["STORED", "WITHDRAWN"]


def assert_advisory_agreement(data: dict):
    _assert_common(data, "AdvisoryAgreement")
    assert is_valid_uuid(str(data["operation_id"]))
    assert data["fee_type"] in ["PER_BUSHEL", "FLAT_ANNUAL"]
    assert isinstance(data["billable_bushels_accrued"], (int, float))
    assert data["disclosure_status"] in ["NONE", "REQUIRED", "DELIVERED", "ACKNOWLEDGED", "STALE"]
    assert isinstance(data["compliance_certified"], bool)
    assert data["status"] in ["DRAFT", "PENDING_SIGNATURE", "ACTIVE", "TERMINATED"]


def assert_market_tick(data: dict):
    """Append-only price-feed record: id + created_at only; no updated_at/version."""
    assert is_valid_uuid(str(data.get("id", ""))), "MarketTick.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        "MarketTick.created_at must be ISO 8601"
    )
    assert data["commodity"] in ["CORN", "SOYBEAN", "WHEAT"]
    assert isinstance(data["contract_month"], str)
    assert isinstance(data["price"], (int, float))
    assert data["kind"] in ["QUOTE", "SETTLEMENT"]
    assert isinstance(data["price_date"], str)
