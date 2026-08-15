"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §3).

assert_<entity>(data) validates the common resource shape plus the fields
the PRD guarantees on the response. Tonnage comparisons use a 2-decimal
tolerance because PRD §2.8 carries tonnage to 2 decimals rounded half-up;
money is integer cents and compared exactly.
"""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Common shape helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity_label: str):
    """PRD §2.5: id (UUID) + created_at + updated_at + integer version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and not isinstance(
        data.get("version"), bool
    ), f"{entity_label}.version must be an integer"


def _assert_append_only_fields(data: dict, entity_label: str):
    """PRD §2.5: weather reports, spoilage events and market indices carry
    ONLY id + created_at; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp"
    )
    assert "version" not in data, f"{entity_label} must not carry a version field"
    assert "updated_at" not in data, f"{entity_label} must not carry an updated_at field"


def assert_tonnage(actual, expected, label="tonnage"):
    """Tonnage fields are rounded to 2 decimals, round-half-up (PRD §2.8)."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_grower(data: dict):
    _assert_common_fields(data, "Grower")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["settled_tons_ytd"], (int, float))
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_field(data: dict):
    _assert_common_fields(data, "Field")
    assert is_valid_uuid(data.get("grower_id", "")), "Field.grower_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["acres"], (int, float)) and data["acres"] > 0
    assert data["forage_type"] in ["ALFALFA", "GRASS", "MIXED"]
    assert isinstance(data["irrigated"], bool)


def assert_cutting(data: dict):
    _assert_common_fields(data, "Cutting")
    assert is_valid_uuid(data.get("field_id", "")), "Cutting.field_id must be a UUID"
    assert isinstance(data["cutting_number"], int) and data["cutting_number"] >= 1
    assert isinstance(data["season_year"], int)
    assert isinstance(data["planned_window_start"], str)
    assert isinstance(data["planned_window_end"], str)
    assert data["status"] in [
        "SCHEDULED", "WINDOW_OPEN", "CUT", "HARVESTED", "ABANDONED",
    ]
    if data.get("actual_cut_date") is not None:
        assert isinstance(data["actual_cut_date"], str)


def assert_weather_report(data: dict):
    _assert_append_only_fields(data, "WeatherReport")
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["report_date"], str)
    assert isinstance(data["precipitation_mm"], (int, float))
    assert isinstance(data["drying_index"], int)
    assert 0 <= data["drying_index"] <= 100


def assert_storage_site(data: dict):
    _assert_common_fields(data, "StorageSite")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["capacity_tons"], (int, float)) and data["capacity_tons"] > 0
    assert isinstance(data["moisture_controlled"], bool)


def assert_bale_lot(data: dict):
    _assert_common_fields(data, "BaleLot")
    assert is_valid_uuid(data.get("cutting_id", "")), "BaleLot.cutting_id must be a UUID"
    assert is_valid_uuid(data.get("storage_site_id", "")), (
        "BaleLot.storage_site_id must be a UUID"
    )
    assert data["bale_type"] in ["SMALL_SQUARE", "LARGE_SQUARE", "ROUND"]
    assert isinstance(data["bale_count"], int) and data["bale_count"] >= 1
    assert isinstance(data["harvested_tonnage"], (int, float))
    assert isinstance(data["harvested_date"], str)
    assert data["quality_tier"] in ["UNGRADED", "SUPREME", "PREMIUM", "GOOD", "FAIR"]
    for tons_field in (
        "shipped_tonnage", "spoilage_tonnage", "open_allocated_tonnage",
        "allocatable_tonnage", "physical_tonnage",
    ):
        assert isinstance(data[tons_field], (int, float)), (
            f"BaleLot.{tons_field} must be numeric"
        )
    assert data["status"] in ["ACTIVE", "DEPLETED", "CONDEMNED"]


def assert_spoilage_event(data: dict):
    _assert_append_only_fields(data, "SpoilageEvent")
    assert is_valid_uuid(data.get("bale_lot_id", "")), (
        "SpoilageEvent.bale_lot_id must be a UUID"
    )
    assert isinstance(data["event_date"], str)
    assert isinstance(data["tons_lost"], (int, float)) and data["tons_lost"] > 0
    assert data["reason"] in ["MOLD", "MOISTURE", "PEST", "FIRE", "OTHER"]


def assert_forage_test(data: dict):
    _assert_common_fields(data, "ForageTest")
    assert is_valid_uuid(data.get("bale_lot_id", "")), (
        "ForageTest.bale_lot_id must be a UUID"
    )
    assert isinstance(data["sample_date"], str)
    assert data["status"] in [
        "COLLECTED", "SUBMITTED", "RESULTED", "CERTIFIED", "INVALIDATED",
    ]
    if data.get("rfv") is not None:
        assert isinstance(data["rfv"], (int, float))
    if data.get("protein_pct") is not None:
        assert isinstance(data["protein_pct"], (int, float))
    if data.get("moisture_pct") is not None:
        assert isinstance(data["moisture_pct"], (int, float))


def assert_market_index(data: dict):
    _assert_append_only_fields(data, "MarketIndex")
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["forage_type"] in ["ALFALFA", "GRASS", "MIXED"]
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["price_per_ton_cents"], int) and (
        data["price_per_ton_cents"] > 0
    )
    assert data["drought_regime"] in ["STABLE", "VOLATILE", "DROUGHT"]


def assert_buyer(data: dict):
    _assert_common_fields(data, "Buyer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert isinstance(data["credit_used_cents"], int) and data["credit_used_cents"] >= 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_freight_lane(data: dict):
    _assert_common_fields(data, "FreightLane")
    assert isinstance(data["origin_region_code"], str)
    assert isinstance(data["dest_region_code"], str)
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] > 0
    assert isinstance(data["rate_per_mile_cents"], int) and (
        data["rate_per_mile_cents"] > 0
    )
    assert isinstance(data["min_charge_cents"], int) and data["min_charge_cents"] >= 0


def assert_quote(data: dict):
    _assert_common_fields(data, "Quote")
    assert is_valid_uuid(data.get("buyer_id", "")), "Quote.buyer_id must be a UUID"
    assert data["forage_type"] in ["ALFALFA", "GRASS", "MIXED"]
    assert data["quality_tier"] in ["UNGRADED", "SUPREME", "PREMIUM", "GOOD", "FAIR"]
    assert isinstance(data["tons"], (int, float)) and data["tons"] > 0
    assert isinstance(data["origin_region_code"], str)
    assert isinstance(data["dest_region_code"], str)
    assert isinstance(data["requested_delivery_by"], str)
    assert data["status"] in ["DRAFT", "ISSUED", "ACCEPTED", "DECLINED", "EXPIRED"]
    for money in ("unit_price_cents", "commodity_cents", "freight_cents", "total_cents"):
        assert isinstance(data[money], int), f"Quote.{money} must be integer cents"


def assert_contract(data: dict):
    _assert_common_fields(data, "Contract")
    assert is_valid_uuid(data.get("quote_id", "")), "Contract.quote_id must be a UUID"
    assert is_valid_uuid(data.get("buyer_id", "")), "Contract.buyer_id must be a UUID"
    assert data["quality_tier"] in ["SUPREME", "PREMIUM", "GOOD", "FAIR"]
    assert data["forage_type"] in ["ALFALFA", "GRASS", "MIXED"]
    assert isinstance(data["committed_tons"], (int, float))
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_reserved_cents"], int)
    assert isinstance(data["delivery_deadline"], str)
    assert isinstance(data["delivered_tons"], (int, float))
    assert isinstance(data["open_allocated_tons"], (int, float))
    assert isinstance(data["remaining_tons"], (int, float))
    assert data["status"] in [
        "ACTIVE", "SUSPENDED", "FULFILLED", "DEFAULTED", "CANCELLED",
    ]


def assert_delivery_load(data: dict):
    _assert_common_fields(data, "DeliveryLoad")
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["capacity_tons"], (int, float)) and data["capacity_tons"] > 0
    assert isinstance(data["planned_ship_date"], str)
    assert isinstance(data["loaded_tons"], (int, float))
    assert data["logistics_status"] in ["PLANNED", "LOADING", "IN_TRANSIT", "DELIVERED"]
    assert data["settlement_status"] in ["OPEN", "SETTLED"]


def assert_load_allocation(data: dict):
    _assert_common_fields(data, "LoadAllocation")
    assert is_valid_uuid(data.get("delivery_load_id", "")), (
        "LoadAllocation.delivery_load_id must be a UUID"
    )
    assert is_valid_uuid(data.get("contract_id", "")), (
        "LoadAllocation.contract_id must be a UUID"
    )
    assert is_valid_uuid(data.get("bale_lot_id", "")), (
        "LoadAllocation.bale_lot_id must be a UUID"
    )
    assert isinstance(data["tons"], (int, float)) and data["tons"] > 0
    assert data["status"] in ["OPEN", "DELIVERED", "RELEASED", "SETTLED"]
    for money in (
        "settled_gross_cents", "settled_commission_cents", "settled_net_cents",
    ):
        if data.get(money) is not None:
            assert isinstance(data[money], int), (
                f"LoadAllocation.{money} must be integer cents"
            )


def assert_baling_service_order(data: dict):
    _assert_common_fields(data, "BalingServiceOrder")
    assert is_valid_uuid(data.get("grower_id", "")), (
        "BalingServiceOrder.grower_id must be a UUID"
    )
    assert is_valid_uuid(data.get("cutting_id", "")), (
        "BalingServiceOrder.cutting_id must be a UUID"
    )
    assert data["status"] in [
        "REQUESTED", "SCHEDULED", "IN_PROGRESS", "COMPLETED",
        "DISPUTED", "INVOICED", "CANCELLED",
    ]
    if data.get("invoice_cents") is not None:
        assert isinstance(data["invoice_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_lot_tonnage_conservation(lot: dict):
    """PRD §2.9: derived tonnages are non-negative and floored at zero."""
    assert lot["allocatable_tonnage"] >= 0
    assert lot["physical_tonnage"] >= 0
    assert lot["open_allocated_tonnage"] >= 0
    assert lot["shipped_tonnage"] >= 0
    assert lot["spoilage_tonnage"] >= 0


def assert_contract_tonnage_identity(contract: dict):
    """PRD §3.6: remaining == committed - delivered - open_allocated."""
    expected = (
        contract["committed_tons"]
        - contract["delivered_tons"]
        - contract["open_allocated_tons"]
    )
    assert contract["remaining_tons"] == pytest.approx(expected, abs=0.005), (
        f"Contract remaining_tons {contract['remaining_tons']} != "
        f"committed - delivered - open_allocated ({expected})"
    )


def assert_settlement_net_identity(allocation: dict):
    """PRD §3.8: settled net == settled gross - settled commission."""
    assert (
        allocation["settled_net_cents"]
        == allocation["settled_gross_cents"] - allocation["settled_commission_cents"]
    ), (
        f"settled_net_cents {allocation['settled_net_cents']} != gross "
        f"{allocation['settled_gross_cents']} - commission "
        f"{allocation['settled_commission_cents']}"
    )
