"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import POLICY_DEFAULTS

_email_counter = itertools.count(1)


def unique_email(prefix="t") -> str:
    """Emails must be unique among ACTIVE travelers (PRD §3.1)."""
    return f"{prefix}{next(_email_counter)}@ex.com"


def create_travel_policy_payload(**overrides) -> dict:
    defaults = dict(POLICY_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_traveler_payload(policy_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Test Traveler",
        "email": unique_email(),
        "grade": "STANDARD",
        "policy_id": policy_id,
        "home_iata": "JFK",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Vendor",
        "vendor_type": "AIR",
        "is_preferred": True,
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_negotiated_rate_payload(vendor_id: str, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "rate_code": "R1",
        "origin": "JFK",
        "destination": "LHR",
        "negotiated_fare_cents": 250000,
        "market_fare_cents": 400000,
        "cap_usage_count": 5,
        "valid_from": "2026-06-01T00:00:00Z",
        "valid_to": "2026-12-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_trip_request_payload(traveler_id: str, **overrides) -> dict:
    defaults = {
        "traveler_id": traveler_id,
        "origin": "JFK",
        "destination": "LHR",
        "depart_date": "2026-08-01T09:00:00Z",
        "return_date": "2026-08-05T09:00:00Z",
        "purpose": "biz",
        "market_estimate_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(trip_request_id: str, vendor_id: str,
                           expected_trip_request_version: int, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "vendor_id": vendor_id,
        "segment_type": "AIR",
        "fare_basis": "REFUNDABLE",
        "fare_cents": 250000,
        "depart_datetime": "2026-08-01T09:00:00Z",
        "return_datetime": "2026-08-01T20:00:00Z",
        "expected_trip_request_version": expected_trip_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_group_booking_payload(vendor_id: str, organizer_traveler_id: str, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "organizer_traveler_id": organizer_traveler_id,
        "block_size": 3,
        "start_date": "2026-08-01T00:00:00Z",
        "end_date": "2026-08-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def exchange_booking_payload(new_fare_cents: int, **overrides) -> dict:
    defaults = {"new_fare_cents": new_fare_cents}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(vendor_id: str, invoiced_total_cents: int, lines: list,
                           billing_period: str = "2026-08", **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "billing_period": billing_period,
        "invoiced_total_cents": invoiced_total_cents,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults
