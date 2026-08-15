"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "STATION_CODE": "JFK",
    "STATION_NAME": "New York JFK",
    "BAGS_HANDLED_TOTAL": 1000000,
    "CARRIER_CODE": "AA",
    "CARRIER_NAME": "Air Alpha",
    "COURIER_NAME": "Speedy Courier",
    "TURNAROUND_BUFFER_MINUTES": 60,
    "VENDOR_NAME": "FixIt Repairs",
    "BENCH_CAPACITY": 2,
    "PASSENGER_NAME": "Pat Flyer",
    "WEIGHT_KG": 20,
    "PICKUP_AT": "2026-08-02T10:00:00Z",
    "TRAVEL_MINUTES": 120,
    "DELIVERY_ADDRESS": "1 Main St",
    "INTAKE_DATE": "2026-08-05",
    "PROMISED_DATE": "2026-08-12",
    "PURCHASE_PRICE_CENTS": 100000,
    "PURCHASE_DATE": "2024-08-01",
    "REPAIR_ESTIMATE_CENTS": 40000,
}


def _seq() -> int:
    return next(_counter)


def unique_tag_number() -> str:
    """Ten-digit tag number, unique per call."""
    return f"0001{_seq():06d}"[:10]


def unique_report_reference() -> str:
    return f"JFKAA{_seq():05d}"[:11]


def unique_email() -> str:
    return f"passenger{_seq():06d}@example.com"


def unique_station_code() -> str:
    return f"S{_seq():02d}"[:3]


def unique_carrier_code() -> str:
    return f"C{_seq():02d}"[:3]


def create_station_payload(**overrides) -> dict:
    defaults = {
        "station_code": unique_station_code(),
        "name": DEFAULTS["STATION_NAME"],
        "bags_handled_total": DEFAULTS["BAGS_HANDLED_TOTAL"],
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "carrier_code": unique_carrier_code(),
        "name": DEFAULTS["CARRIER_NAME"],
        "is_interline_partner": False,
    }
    defaults.update(overrides)
    return defaults


def create_courier_service_payload(serves_station_ids, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["COURIER_NAME"],
        "serves_station_ids": list(serves_station_ids),
        "turnaround_buffer_minutes": DEFAULTS["TURNAROUND_BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_repair_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENDOR_NAME"],
        "bench_capacity": DEFAULTS["BENCH_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_passenger_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PASSENGER_NAME"],
        "email": unique_email(),
        "tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_bag_tag_payload(passenger_id, routing_carrier_ids, **overrides) -> dict:
    defaults = {
        "tag_number": unique_tag_number(),
        "passenger_id": passenger_id,
        "routing_carrier_ids": list(routing_carrier_ids),
        "is_international": False,
        "weight_kg": DEFAULTS["WEIGHT_KG"],
        "declared_value_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(passenger_id, bag_tag_id, station_id, **overrides) -> dict:
    defaults = {
        "report_reference": unique_report_reference(),
        "passenger_id": passenger_id,
        "bag_tag_id": bag_tag_id,
        "station_id": station_id,
        "type": "DELAYED",
    }
    defaults.update(overrides)
    return defaults


def create_tracing_event_payload(carrier_id, station_id, event_type, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "station_id": station_id,
        "event_type": event_type,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(report_id, courier_service_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "courier_service_id": courier_service_id,
        "pickup_at": DEFAULTS["PICKUP_AT"],
        "travel_minutes": DEFAULTS["TRAVEL_MINUTES"],
        "delivery_address": DEFAULTS["DELIVERY_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(report_id, vendor_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "vendor_id": vendor_id,
        "intake_date": DEFAULTS["INTAKE_DATE"],
        "promised_date": DEFAULTS["PROMISED_DATE"],
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "purchase_date": DEFAULTS["PURCHASE_DATE"],
        "repair_estimate_cents": DEFAULTS["REPAIR_ESTIMATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def make_receipt(incurred_on, amount_minor, currency_code="USD", description="expense") -> dict:
    return {
        "incurred_on": incurred_on,
        "description": description,
        "amount_minor": amount_minor,
        "currency_code": currency_code,
    }


def create_expense_claim_payload(report_id, receipts, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "receipts": receipts,
    }
    defaults.update(overrides)
    return defaults
