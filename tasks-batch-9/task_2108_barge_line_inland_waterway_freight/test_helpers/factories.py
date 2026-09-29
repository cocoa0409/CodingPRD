"""Payload factories — one per write endpoint, input fields only."""
import itertools

from .constants import (
    DEFAULT_CREDIT_LIMIT_CENTS,
    DEFAULT_GAUGE_STATION,
    DEFAULT_READING_AT,
    DEFAULT_STAGE_FEET,
    FUEL_SURCHARGE_TABLE,
    GRAIN_BASE_RATE,
    GRAIN_DEMURRAGE_RATE_CENTS_PER_HOUR,
    GRAIN_MIN_CHARGE_CENTS,
    GRAIN_TARIFF_CODE,
    TEST_DEFAULTS,
)

_hull_seq = itertools.count(1)
_code_seq = itertools.count(1)


def next_hull_number() -> str:
    return f"BL-{9000 + next(_hull_seq)}"


def next_commodity_code() -> str:
    return f"CODE{next(_code_seq)}"


def create_shipper_payload(**overrides) -> dict:
    payload = {
        "name": "Delta Grain Co",
        "credit_limit_cents": DEFAULT_CREDIT_LIMIT_CENTS,
    }
    payload.update(overrides)
    return payload


def create_commodity_payload(**overrides) -> dict:
    payload = {
        "code": "CORN",
        "commodity_group": "GRAIN",
        "residue_class": "CLEAN",
        "hazard_flag": False,
        "stowage_factor": 1.28,
    }
    payload.update(overrides)
    return payload


def create_compatibility_rule_payload(
    prior_commodity_group, next_commodity_group, **overrides
) -> dict:
    payload = {
        "prior_commodity_group": prior_commodity_group,
        "next_commodity_group": next_commodity_group,
        "required_cleaning_level": "WASH",
        "prohibited": False,
    }
    payload.update(overrides)
    return payload


def create_tariff_filing_payload(**overrides) -> dict:
    payload = {
        "tariff_code": GRAIN_TARIFF_CODE,
        "commodity_group": "GRAIN",
        "base_rate_cents_per_ton_mile": GRAIN_BASE_RATE,
        "min_charge_cents": GRAIN_MIN_CHARGE_CENTS,
        "demurrage_rate_cents_per_hour": GRAIN_DEMURRAGE_RATE_CENTS_PER_HOUR,
        "fuel_surcharge_table": [dict(tier) for tier in FUEL_SURCHARGE_TABLE],
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-12-31T23:59:59Z",
    }
    payload.update(overrides)
    return payload


def create_fuel_index_posting_payload(**overrides) -> dict:
    payload = {"posting_date": "2026-08-03", "diesel_price_cents_per_gallon": 300}
    payload.update(overrides)
    return payload


def create_river_stage_reading_payload(**overrides) -> dict:
    payload = {
        "gauge_station": DEFAULT_GAUGE_STATION,
        "reading_at": DEFAULT_READING_AT,
        "stage_feet": DEFAULT_STAGE_FEET,
    }
    payload.update(overrides)
    return payload


def create_barge_payload(**overrides) -> dict:
    payload = {
        "hull_number": next_hull_number(),
        "capacity_tons": TEST_DEFAULTS["CAPACITY_TONS"],
        "light_draft_feet": TEST_DEFAULTS["LIGHT_DRAFT_FEET"],
        "tons_per_inch_immersion": TEST_DEFAULTS["TONS_PER_INCH_IMMERSION"],
    }
    payload.update(overrides)
    return payload


def create_cleaning_order_payload(required_for_commodity_id, **overrides) -> dict:
    payload = {"required_for_commodity_id": required_for_commodity_id}
    payload.update(overrides)
    return payload


def complete_cleaning_order_payload(
    performed_level="WASH", certificate_number="CERT-1", inspection_passed=True
) -> dict:
    return {
        "performed_level": performed_level,
        "certificate_number": certificate_number,
        "inspection_passed": inspection_passed,
    }


def create_fleeting_berth_payload(**overrides) -> dict:
    payload = {
        "harbor_name": "Cairo Harbor",
        "river_mile": 955.0,
        "capacity_barges": 4,
        "daily_fee_cents_per_barge": 15_000,
        "switch_fee_cents": 60_000,
    }
    payload.update(overrides)
    return payload


def create_fleeting_assignment_payload(barge_id, fleeting_berth_id, **overrides) -> dict:
    payload = {
        "barge_id": barge_id,
        "fleeting_berth_id": fleeting_berth_id,
        "start_at": "2026-08-18T00:00:00Z",
        "end_at": "2026-08-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_lock_payload(**overrides) -> dict:
    payload = {
        "lock_name": "Chain of Rocks",
        "river_mile": 185.0,
        "chamber_capacity_barges": 9,
        "cycle_minutes": 45,
        "turnback_buffer_minutes": 30,
    }
    payload.update(overrides)
    return payload


def create_lock_reservation_payload(
    lock_id, tow_id, requested_start_at, expected_tow_version, **overrides
) -> dict:
    payload = {
        "lock_id": lock_id,
        "tow_id": tow_id,
        "requested_start_at": requested_start_at,
        "expected_tow_version": expected_tow_version,
    }
    payload.update(overrides)
    return payload


def create_tow_payload(**overrides) -> dict:
    payload = {
        "towboat_name": "M/V Cairo",
        "horsepower": 6000,
        "origin_mile": TEST_DEFAULTS["ORIGIN_MILE"],
        "destination_mile": TEST_DEFAULTS["DESTINATION_MILE"],
        "controlling_gauge_station": DEFAULT_GAUGE_STATION,
    }
    payload.update(overrides)
    return payload


def create_barge_assignment_payload(
    barge_id, freight_contract_id, loaded_tons=None, cut_position=1, **overrides
) -> dict:
    payload = {
        "barge_id": barge_id,
        "freight_contract_id": freight_contract_id,
        "loaded_tons": TEST_DEFAULTS["LOADED_TONS"] if loaded_tons is None else loaded_tons,
        "cut_position": cut_position,
    }
    payload.update(overrides)
    return payload


def create_freight_contract_payload(shipper_id, commodity_id, **overrides) -> dict:
    payload = {
        "shipper_id": shipper_id,
        "commodity_id": commodity_id,
        "contracted_tons": TEST_DEFAULTS["LOADED_TONS"],
        "origin_mile": TEST_DEFAULTS["ORIGIN_MILE"],
        "destination_mile": TEST_DEFAULTS["DESTINATION_MILE"],
        "laytime_hours": TEST_DEFAULTS["LAYTIME_HOURS"],
        "declared_value_cents_per_ton": TEST_DEFAULTS["DECLARED_VALUE_CENTS_PER_TON"],
    }
    payload.update(overrides)
    return payload


def create_cargo_claim_payload(
    freight_contract_id,
    barge_assignment_id,
    claim_type="SHORTAGE",
    claimed_tons=13,
    claimed_amount_cents=300_000,
    **overrides,
) -> dict:
    payload = {
        "freight_contract_id": freight_contract_id,
        "barge_assignment_id": barge_assignment_id,
        "claim_type": claim_type,
        "claimed_tons": claimed_tons,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload
