"""Payload factories — one per entity, input fields only.

A monotonic VIN counter keeps VINs unique within a single test process so a
test that creates several consignments never trips ERR_DUPLICATE_VIN by accident.
"""
import itertools

DEFAULTS = {
    "SALE_NAME": "Tuesday Dealer Sale",
    "SALE_DATE": "2026-06-02T09:00:00Z",
    "SELLER_NAME": "Seller A",
    "BUYER_NAME": "Buyer B",
    "CARRIER_NAME": "Carrier X",
    "GRADE": 4.0,
    "ODOMETER": 30000,
    "STARTING_BID_CENTS": 400000,
    "CREDIT_LIMIT_CENTS": 5_000_000,
}

_vin_counter = itertools.count(1)


def next_vin() -> str:
    """Return a unique, 17-character VIN for the current test process."""
    n = next(_vin_counter)
    base = "1FTFW1ET5DFA"
    suffix = f"{n:05d}"  # 5 digits -> total 12 + 5 = 17 chars
    vin = base + suffix
    assert len(vin) == 17, f"VIN must be 17 chars, got {len(vin)}: {vin}"
    return vin


def create_sale_payload(**overrides) -> dict:
    defaults = {
        "sale_name": DEFAULTS["SALE_NAME"],
        "sale_date": DEFAULTS["SALE_DATE"],
        # buyer_fee_schedule_code is optional (defaults to STANDARD); omit unless overridden.
    }
    defaults.update(overrides)
    return defaults


def create_lane_payload(sale_id, lane_number=1, open_minute=0, close_minute=600, **overrides) -> dict:
    defaults = {
        "sale_id": sale_id,
        "lane_number": lane_number,
        "open_minute": open_minute,
        "close_minute": close_minute,
    }
    defaults.update(overrides)
    return defaults


def create_seller_payload(**overrides) -> dict:
    defaults = {
        "dealer_name": DEFAULTS["SELLER_NAME"],
        # seller_fee_pct is optional (defaults to 0.02); omit unless overridden.
    }
    defaults.update(overrides)
    return defaults


def create_buyer_payload(credit_limit_cents=None, **overrides) -> dict:
    defaults = {
        "dealer_name": DEFAULTS["BUYER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"] if credit_limit_cents is None else credit_limit_cents,
    }
    defaults.update(overrides)
    return defaults


def create_consignment_payload(sale_id, seller_id, vin=None, **overrides) -> dict:
    defaults = {
        "sale_id": sale_id,
        "seller_id": seller_id,
        "vin": vin if vin is not None else next_vin(),
        # title_status optional (defaults to ABSENT); omit unless overridden.
    }
    defaults.update(overrides)
    return defaults


def create_condition_report_payload(consignment_id, grade=None, odometer_miles=None, **overrides) -> dict:
    defaults = {
        "consignment_id": consignment_id,
        "grade": DEFAULTS["GRADE"] if grade is None else grade,
        "odometer_miles": DEFAULTS["ODOMETER"] if odometer_miles is None else odometer_miles,
        # announcements optional (defaults to []); omit unless overridden.
    }
    defaults.update(overrides)
    return defaults


def catalog_payload(reserve_price_cents=0, floor_price_cents=0, **overrides) -> dict:
    defaults = {
        "reserve_price_cents": reserve_price_cents,
        "floor_price_cents": floor_price_cents,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(sale_id, consignment_id, lane_id, run_number=1,
                       slot_start_minute=0, slot_end_minute=10,
                       starting_bid_cents=None, **overrides) -> dict:
    defaults = {
        "sale_id": sale_id,
        "consignment_id": consignment_id,
        "lane_id": lane_id,
        "run_number": run_number,
        "slot_start_minute": slot_start_minute,
        "slot_end_minute": slot_end_minute,
        "starting_bid_cents": DEFAULTS["STARTING_BID_CENTS"] if starting_bid_cents is None else starting_bid_cents,
    }
    defaults.update(overrides)
    return defaults


def place_bid_payload(buyer_id, expected_lot_version, bid_type="LIVE",
                      amount_cents=400000, channel="LANE", **overrides) -> dict:
    defaults = {
        "buyer_id": buyer_id,
        "bid_type": bid_type,
        "amount_cents": amount_cents,
        "expected_lot_version": expected_lot_version,
        "channel": channel,
    }
    defaults.update(overrides)
    return defaults


def create_arbitration_claim_payload(lot_id, buyer_id, reason_code="MECHANICAL",
                                     claimed_cents=100000, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "buyer_id": buyer_id,
        "reason_code": reason_code,
        "claimed_cents": claimed_cents,
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(carrier_name=None, **overrides) -> dict:
    defaults = {
        "carrier_name": DEFAULTS["CARRIER_NAME"] if carrier_name is None else carrier_name,
        # turnaround_buffer_minutes optional (defaults to 30); omit unless overridden.
    }
    defaults.update(overrides)
    return defaults


def create_transport_order_payload(settlement_id, carrier_id,
                                   pickup_start_minute=100, pickup_end_minute=160, **overrides) -> dict:
    defaults = {
        "settlement_id": settlement_id,
        "carrier_id": carrier_id,
        "pickup_start_minute": pickup_start_minute,
        "pickup_end_minute": pickup_end_minute,
    }
    defaults.update(overrides)
    return defaults
