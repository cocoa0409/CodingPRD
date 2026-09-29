"""Payload factories — one per entity, input fields only."""

from .constants import FULL_TIERS, TEST_DEFAULTS


def create_trading_desk_payload(**overrides) -> dict:
    payload = {
        "desk_code": "GD1",
        "name": "Illinois River Desk",
        "credit_line_usd": TEST_DEFAULTS["CREDIT_LINE_USD"],
    }
    payload.update(overrides)
    return payload


def create_elevator_location_payload(desk_id, **overrides) -> dict:
    payload = {
        "desk_id": desk_id,
        "location_code": "ELV1",
        "name": "Morris Elevator",
        "intake_capacity_bushels": TEST_DEFAULTS["INTAKE_CAPACITY_BUSHELS"],
        "rail_served": True,
    }
    payload.update(overrides)
    return payload


def create_discount_schedule_payload(**overrides) -> dict:
    payload = {
        "commodity_code": "CORN",
        "effective_from": TEST_DEFAULTS["SCHEDULE_EFFECTIVE_FROM"],
        "moisture_standard_pct": 15.0,
        "shrink_factor_pct_per_point": 1.18,
        "tiers": [dict(tier) for tier in FULL_TIERS],
    }
    payload.update(overrides)
    return payload


def create_risk_limit_payload(desk_id, expected_desk_version, **overrides) -> dict:
    payload = {
        "desk_id": desk_id,
        "commodity_code": "CORN",
        "max_unpriced_bushels": 100000,
        "max_net_short_lots": 40,
        "expected_desk_version": expected_desk_version,
    }
    payload.update(overrides)
    return payload


def create_rail_fleet_payload(home_location_id, **overrides) -> dict:
    payload = {
        "home_location_id": home_location_id,
        "fleet_code": "FLT-A",
        "car_count": 60,
    }
    payload.update(overrides)
    return payload


def create_bid_payload(location_id, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "commodity_code": "CORN",
        "futures_month": TEST_DEFAULTS["FUTURES_MONTH"],
        "delivery_period_start": TEST_DEFAULTS["DELIVERY_PERIOD_START"],
        "delivery_period_end": TEST_DEFAULTS["DELIVERY_PERIOD_END"],
        "basis_cents": TEST_DEFAULTS["BID_BASIS_CENTS"],
        "max_bushels": TEST_DEFAULTS["BID_MAX_BUSHELS"],
        "expires_at": TEST_DEFAULTS["BID_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_hedge_position_payload(desk_id, **overrides) -> dict:
    payload = {
        "desk_id": desk_id,
        "commodity_code": "CORN",
        "futures_month": TEST_DEFAULTS["FUTURES_MONTH"],
        "side": "SHORT",
        "lots_open": 10,
        "avg_entry_price_cents": TEST_DEFAULTS["ENTRY_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_purchase_contract_payload(bid_id, hedge_position_id, **overrides) -> dict:
    """CASH contracts and HTA contracts must carry futures_price_cents;
    BASIS and DEFERRED contracts must omit it."""
    payload = {
        "bid_id": bid_id,
        "hedge_position_id": hedge_position_id,
        "contract_type": "CASH",
        "bushels": 10000,
        "seller_name": "Bell Farms",
        "delivery_start": TEST_DEFAULTS["DELIVERY_START"],
        "delivery_end": TEST_DEFAULTS["DELIVERY_END"],
        "futures_price_cents": TEST_DEFAULTS["ENTRY_PRICE_CENTS"],
    }
    payload.update(overrides)
    if payload.get("contract_type") in ("BASIS", "DEFERRED"):
        payload.pop("futures_price_cents", None)
    return payload


def create_pricing_order_payload(contract_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "component": "BASIS",
        "bushels": 10000,
        "price_cents": -30,
    }
    payload.update(overrides)
    return payload


def create_delivery_ticket_payload(contract_id, location_id, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "location_id": location_id,
        "gross_bushels": 10000,
        "moisture_pct": 15.0,
        "test_weight_lbs": 56.0,
        "foreign_material_pct": 2.0,
        "damage_pct": 0.0,
    }
    payload.update(overrides)
    return payload


def create_freight_booking_payload(fleet_id, contract_id, expected_fleet_version,
                                   **overrides) -> dict:
    payload = {
        "fleet_id": fleet_id,
        "contract_id": contract_id,
        "cars_requested": 25,
        "placement_at": "2026-11-05T00:00:00Z",
        "release_at": "2026-11-07T00:00:00Z",
        "expected_fleet_version": expected_fleet_version,
    }
    payload.update(overrides)
    return payload
