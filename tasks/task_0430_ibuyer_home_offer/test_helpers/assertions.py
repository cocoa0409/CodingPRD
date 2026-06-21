"""Entity assertions and domain invariant checkers for the iBuyer Home Offer API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def assert_common_fields(data: dict):
    """Versioned, mutable record: id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments"


def assert_seller(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["payout_method"] in ("ACH", "WIRE")


def assert_property(data: dict):
    assert_common_fields(data)
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["address_line"], str)
    assert isinstance(data["zip_code"], str)
    assert isinstance(data["bedrooms"], int) and data["bedrooms"] >= 0
    assert isinstance(data["living_area_sqft"], int) and data["living_area_sqft"] >= 1
    assert isinstance(data["comp_median_value"], (int, float))
    assert isinstance(data["market_trend_pct"], (int, float))
    assert isinstance(data["avm_value"], (int, float))
    assert_cost_precision(data["avm_value"])
    assert data["status"] in (
        "VALUED", "UNDER_OFFER", "IN_TRANSACTION", "SOLD", "WITHDRAWN",
    )
    # revised_avm_value, condition_score, active_offer_id may be null.
    if data.get("condition_score") is not None:
        assert data["condition_score"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")


def assert_offer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["avm_value_snapshot"], (int, float))
    assert_cost_precision(data["avm_value_snapshot"])
    assert isinstance(data["service_fee_pct"], (int, float))
    assert 0 <= data["service_fee_pct"] <= 0.15
    assert isinstance(data["service_fee"], (int, float))
    assert_cost_precision(data["service_fee"])
    assert isinstance(data["estimated_concession"], (int, float))
    assert_cost_precision(data["estimated_concession"])
    assert isinstance(data["preliminary_net_proceeds"], (int, float))
    assert_cost_precision(data["preliminary_net_proceeds"])
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in (
        "ISSUED", "ACCEPTED", "DECLINED", "EXPIRED", "SUPERSEDED",
    )


def assert_assessment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["offer_id"], str)
    for comp in ("roof_condition", "hvac_condition", "foundation_condition"):
        if data.get(comp) is not None:
            assert data[comp] in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert isinstance(data["questionnaire_flags"], list)
    if data.get("condition_score") is not None:
        assert data["condition_score"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_repair_line_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["assessment_id"], str)
    assert data["category"] in ("ROOF", "HVAC", "FOUNDATION", "COSMETIC", "OTHER")
    assert isinstance(data["estimate_amount"], (int, float))
    assert data["estimate_amount"] >= 0
    assert isinstance(data["rounded_amount"], (int, float))
    assert_cost_precision(data["rounded_amount"])


def assert_transaction(data: dict):
    assert_common_fields(data)
    assert isinstance(data["offer_id"], str)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["repair_credit"], (int, float))
    assert_cost_precision(data["repair_credit"])
    assert isinstance(data["final_concession"], (int, float))
    assert isinstance(data["retrade_amount"], (int, float))
    assert isinstance(data["leaseback_days"], int)
    assert isinstance(data["leaseback_daily_rate"], (int, float))
    assert isinstance(data["leaseback_total"], (int, float))
    assert isinstance(data["final_net_proceeds"], (int, float))
    assert_cost_precision(data["final_net_proceeds"])
    assert data["status"] in (
        "PENDING_ASSESSMENT", "SCHEDULED", "INSPECTION", "CLOSED", "CANCELLED",
    )


def assert_resale(data: dict):
    assert_common_fields(data)
    assert isinstance(data["transaction_id"], str)
    assert isinstance(data["list_price"], (int, float))
    assert isinstance(data["resale_commission_pct"], (int, float))
    assert isinstance(data["projected_spread"], (int, float))
    assert_cost_precision(data["projected_spread"])
    if data.get("sold_price") is not None:
        assert isinstance(data["sold_price"], (int, float))
    if data.get("net_spread") is not None:
        assert_cost_precision(data["net_spread"])
    assert data["status"] in ("LISTED", "SOLD", "DELISTED")
