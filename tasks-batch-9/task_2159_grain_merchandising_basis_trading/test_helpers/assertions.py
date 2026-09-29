"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import CONTRACT_UNIT_BUSHELS, INITIAL_MARGIN_USD_PER_LOT

COMMODITY_CODES = ["CORN", "SOYBEANS", "HRW_WHEAT"]


def _assert_common_fields(data: dict, entity: str) -> None:
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_trading_desk(data: dict) -> None:
    _assert_common_fields(data, "TradingDesk")
    assert isinstance(data["desk_code"], str) and data["desk_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["credit_line_usd"] > 0, "credit_line_usd must be greater than zero"
    assert data["posture"] in ("NORMAL", "RESTRICTED", "FROZEN")
    for money in ("margin_requirement_usd", "open_margin_call_usd",
                  "available_credit_usd", "realized_hedge_pnl_usd"):
        assert_cost_precision(data[money])
    assert isinstance(data["committed_hedge_lots"], int)
    assert data["margin_requirement_usd"] >= 0
    assert data["open_margin_call_usd"] >= 0


def assert_elevator_location(data: dict) -> None:
    _assert_common_fields(data, "ElevatorLocation")
    assert is_valid_uuid(data["desk_id"])
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert data["intake_capacity_bushels"] > 0
    assert isinstance(data["rail_served"], bool)
    assert data["committed_intake_bushels"] >= 0


def assert_discount_schedule(data: dict) -> None:
    _assert_common_fields(data, "DiscountSchedule")
    assert data["commodity_code"] in COMMODITY_CODES
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    assert isinstance(data["tiers"], list) and len(data["tiers"]) > 0
    seen = set()
    for tier in data["tiers"]:
        assert tier["factor"] in ("MOISTURE", "TEST_WEIGHT", "FOREIGN_MATERIAL", "DAMAGE")
        assert tier["direction"] in ("ABOVE", "BELOW")
        assert tier["factor"] not in seen, "at most one tier row per factor"
        seen.add(tier["factor"])


def assert_risk_limit(data: dict) -> None:
    _assert_common_fields(data, "RiskLimit")
    assert is_valid_uuid(data["desk_id"])
    assert data["commodity_code"] in COMMODITY_CODES
    assert data["max_unpriced_bushels"] >= 0
    assert data["max_net_short_lots"] >= 0
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_rail_fleet(data: dict) -> None:
    _assert_common_fields(data, "RailFleet")
    assert is_valid_uuid(data["home_location_id"])
    assert isinstance(data["fleet_code"], str) and data["fleet_code"]
    assert data["car_count"] > 0


def assert_bid(data: dict) -> None:
    _assert_common_fields(data, "Bid")
    assert is_valid_uuid(data["location_id"])
    assert data["commodity_code"] in COMMODITY_CODES
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "WITHDRAWN", "EXPIRED")
    assert data["max_bushels"] > 0
    assert data["delivery_period_end"] >= data["delivery_period_start"]
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["contracted_bushels"] >= 0


def assert_hedge_position(data: dict) -> None:
    _assert_common_fields(data, "HedgePosition")
    assert is_valid_uuid(data["desk_id"])
    assert data["commodity_code"] in COMMODITY_CODES
    assert data["side"] in ("SHORT", "LONG")
    assert data["status"] in ("OPEN", "MARGIN_CALL", "LIQUIDATED")
    assert data["lots_open"] >= 0
    assert data["lots_committed"] >= 0
    assert data["lots_available"] == data["lots_open"] - data["lots_committed"], (
        "lots_available is open lots less committed lots"
    )
    for money in ("posted_margin_usd", "unrealized_pnl_usd", "realized_pnl_usd"):
        assert_cost_precision(data[money])


def assert_purchase_contract(data: dict) -> None:
    _assert_common_fields(data, "PurchaseContract")
    assert is_valid_uuid(data["bid_id"])
    assert is_valid_uuid(data["desk_id"])
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["hedge_position_id"])
    assert data["contract_type"] in ("CASH", "HTA", "BASIS", "DEFERRED")
    assert data["commodity_code"] in COMMODITY_CODES
    assert data["settlement_basis"] in ("SHRINK_FIRST", "GROSS_GRADE")
    assert data["pricing_status"] in ("UNPRICED", "PARTIALLY_PRICED", "FULLY_PRICED")
    assert data["delivery_status"] in ("OPEN", "PARTIALLY_DELIVERED", "COMPLETE")
    assert data["status"] in ("ACTIVE", "SETTLED", "CANCELLED", "DEFAULTED", "ROLLED")
    assert data["bushels"] > 0
    assert data["delivery_end"] >= data["delivery_start"]
    assert isinstance(data["pricing_locked"], bool)
    assert data["hedge_lots_assigned"] >= 0
    assert data["delivered_bushels"] >= 0
    assert_cost_precision(data["settled_value_usd"])
    assert_cost_precision(data["damages_usd"])


def assert_pricing_order(data: dict) -> None:
    """A pricing order is an immutable event row: id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "PricingOrder.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "PricingOrder.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "version" not in data, "a pricing order carries no version field"
    assert "updated_at" not in data, "a pricing order carries no updated_at field"
    assert data["component"] in ("FUTURES", "BASIS")
    assert data["bushels"] > 0


def assert_margin_call(data: dict) -> None:
    _assert_common_fields(data, "MarginCall")
    assert is_valid_uuid(data["hedge_position_id"])
    assert data["status"] in ("OPEN", "CURED", "DEFAULTED")
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["cure_deadline_at"])
    assert data["call_amount_usd"] >= 0
    assert_cost_precision(data["call_amount_usd"])


def assert_delivery_ticket(data: dict) -> None:
    _assert_common_fields(data, "DeliveryTicket")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["discount_schedule_id"])
    assert data["status"] in ("GRADED", "APPLIED", "REJECTED", "REVERSED")
    assert data["gross_bushels"] > 0
    assert data["net_bushels"] >= 0
    assert data["shrink_pct"] >= 0
    assert_cost_precision(data["discount_total_usd"])
    if data["settlement_value_usd"] is not None:
        assert_cost_precision(data["settlement_value_usd"])


def assert_freight_booking(data: dict) -> None:
    _assert_common_fields(data, "FreightBooking")
    assert is_valid_uuid(data["fleet_id"])
    assert is_valid_uuid(data["contract_id"])
    assert data["cars_requested"] > 0
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert is_iso8601_timestamp(data["placement_at"])
    assert is_iso8601_timestamp(data["release_at"])
    assert is_iso8601_timestamp(data["occupancy_end_at"])
    assert data["release_at"] > data["placement_at"]
    assert data["substitution_count"] >= 0


# ─── Domain invariant checkers ────────────────────────

def assert_desk_credit_invariants(desk: dict) -> None:
    """The desk's credit picture is one derived quantity (PRD §2.9)."""
    expected_available = round(
        desk["credit_line_usd"] - desk["margin_requirement_usd"]
        - desk["open_margin_call_usd"], 2
    )
    assert desk["available_credit_usd"] == pytest.approx(expected_available, abs=0.01), (
        f"available_credit_usd should be {expected_available}, "
        f"got {desk['available_credit_usd']}"
    )
    expected_util = round(
        (desk["margin_requirement_usd"] + desk["open_margin_call_usd"])
        / desk["credit_line_usd"], 4
    )
    assert desk["credit_utilization"] == pytest.approx(expected_util, abs=0.0001), (
        f"credit_utilization should be {expected_util}, got {desk['credit_utilization']}"
    )
    if desk["credit_utilization"] >= 1.0000:
        assert desk["posture"] == "FROZEN"
    elif desk["credit_utilization"] >= 0.8000:
        assert desk["posture"] == "RESTRICTED"
    else:
        assert desk["posture"] == "NORMAL"


def assert_position_margin_invariants(position: dict) -> None:
    """An untouched OPEN position posts initial margin on its open lots."""
    expected = round(
        position["lots_open"] * INITIAL_MARGIN_USD_PER_LOT[position["commodity_code"]], 2
    )
    assert position["posted_margin_usd"] == pytest.approx(expected, abs=0.01), (
        f"posted_margin_usd should be {expected}, got {position['posted_margin_usd']}"
    )


def expected_hedge_lots(bushels: float) -> int:
    """Bushels divided by 5,000 per lot, rounded half-up to whole lots."""
    from decimal import ROUND_HALF_UP, Decimal
    quotient = Decimal(str(bushels)) / Decimal(CONTRACT_UNIT_BUSHELS)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def assert_contract_pricing_invariants(contract: dict) -> None:
    """unpriced_bushels and pricing_status follow from the two priced legs."""
    expected_unpriced = contract["bushels"] - min(
        contract["priced_futures_bushels"], contract["priced_basis_bushels"]
    )
    assert contract["unpriced_bushels"] == pytest.approx(expected_unpriced, abs=0.01), (
        f"unpriced_bushels should be {expected_unpriced}, "
        f"got {contract['unpriced_bushels']}"
    )
    if (contract["priced_futures_bushels"] >= contract["bushels"]
            and contract["priced_basis_bushels"] >= contract["bushels"]):
        assert contract["pricing_status"] == "FULLY_PRICED"
    elif (contract["priced_futures_bushels"] == 0
            and contract["priced_basis_bushels"] == 0):
        assert contract["pricing_status"] == "UNPRICED"
    else:
        assert contract["pricing_status"] == "PARTIALLY_PRICED"
