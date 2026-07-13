"""Payload factories — one per entity, input fields only.

Uniqueness-constrained codes (hin, sku, bay_code, berth_code) are auto-generated
from a process-wide counter so a single test may create many entities without
collision. Callers override any field via keyword.
"""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def unique_hin() -> str:
    # PRD §3.1: 12-character Hull Identification Number, unique across units.
    return f"HIN{_seq():09d}"


def unique_sku() -> str:
    return f"SKU{_seq():09d}"


def unique_bay_code() -> str:
    return f"BAY{_seq():06d}"


def unique_berth_code() -> str:
    return f"BR{_seq():06d}"


def create_unit_payload(**overrides) -> dict:
    payload = {
        "hin": unique_hin(),
        "make": "Sea Ray",
        "model": "SLX",
        "model_year": 2024,
        "unit_type": "BOAT",
        "length_ft": 25,
        "cost_cents": 6000000,
        "list_price_cents": 7500000,
        "acquisition_type": "CASH",
    }
    payload.update(overrides)
    return payload


def create_floor_plan_payload(unit_id, expected_unit_version, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "lender_name": "Marine Credit",
        "principal_cents": 8000000,
        "apr_bps": 950,
        "advanced_at": "2026-03-01T00:00:00Z",
        "curtailment_pct_bps": 1000,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def create_deal_payload(unit_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "customer_name": "Grace",
        "sale_price_cents": 5000000,
        "financing_type": "CASH",
        "tax_rate_bps": 700,
        "doc_fee_cents": 39900,
        "down_payment_cents": 2000000,
    }
    payload.update(overrides)
    return payload


def create_consignment_payload(unit_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "consignor_name": "Yuri",
        "agreed_floor_cents": 5000000,
        "commission_bps": 1200,
    }
    payload.update(overrides)
    return payload


def create_service_bay_payload(**overrides) -> dict:
    payload = {
        "bay_code": unique_bay_code(),
        "bay_type": "MECHANICAL",
    }
    payload.update(overrides)
    return payload


def create_repair_order_payload(unit_id, service_bay_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "service_bay_id": service_bay_id,
        "customer_name": "Ada",
        "ro_type": "CUSTOM",
        "labor_rate_cents_per_hour": 11000,
        "tax_rate_bps": 700,
        "scheduled_start": "2026-06-02T09:00:00Z",
        "scheduled_end": "2026-06-02T12:00:00Z",
        "estimated_hours": 2.0,
    }
    payload.update(overrides)
    return payload


def create_service_line_payload(repair_order_id, line_type, **overrides) -> dict:
    payload = {
        "repair_order_id": repair_order_id,
        "line_type": line_type,
    }
    payload.update(overrides)
    return payload


def create_part_payload(**overrides) -> dict:
    payload = {
        "sku": unique_sku(),
        "name": "Impeller",
        "on_hand_qty": 10,
        "unit_cost_cents": 2000,
        "list_price_cents": 4599,
        "reorder_point": 2,
    }
    payload.update(overrides)
    return payload


def create_berth_payload(**overrides) -> dict:
    payload = {
        "berth_code": unique_berth_code(),
        "berth_type": "WET_SLIP",
        "max_length_ft": 40,
    }
    payload.update(overrides)
    return payload


def create_slip_reservation_payload(berth_id, unit_id, **overrides) -> dict:
    payload = {
        "berth_id": berth_id,
        "unit_id": unit_id,
        "start_date": "2026-06-01T00:00:00Z",
        "end_date": "2026-06-05T00:00:00Z",
        "daily_rate_cents": 5000,
    }
    payload.update(overrides)
    return payload
