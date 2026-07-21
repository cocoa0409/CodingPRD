"""Payload factories -- one per entity, input fields only."""
import itertools
import uuid

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Short unique token so natural keys never collide inside one test."""
    return f"{next(_counter):03d}{uuid.uuid4().hex[:6]}"


def unique_email(prefix: str = "donor") -> str:
    return f"{prefix}-{unique_suffix()}@example.com"


def unique_ein() -> str:
    token = unique_suffix()[-7:]
    return f"91-{token.upper()}"


def unique_vin() -> str:
    return f"VIN{unique_suffix().upper()}"[:17].ljust(17, "0")


def create_charity_payload(**overrides) -> dict:
    payload = {
        "name": "Wheels For Hope",
        "ein": unique_ein(),
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_donor_payload(**overrides) -> dict:
    payload = {
        "email": unique_email(),
        "full_name": "Dora Nate",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_tow_vendor_payload(**overrides) -> dict:
    payload = {
        "name": "Hauler One",
        "service_state_code": "CA",
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
        "daily_capacity_slots": TEST_DEFAULTS["DAILY_CAPACITY_SLOTS"],
    }
    payload.update(overrides)
    return payload


def create_venue_payload(**overrides) -> dict:
    payload = {
        "name": "Bay Auto Auction",
        "venue_type": "AUCTION",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_donation_payload(donor_id: str, charity_id: str, **overrides) -> dict:
    payload = {
        "donor_id": donor_id,
        "charity_id": charity_id,
        "intake_channel": "WEB",
        "declared_condition": "GOOD",
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(donation_id: str, **overrides) -> dict:
    payload = {
        "donation_id": donation_id,
        "vin": unique_vin(),
        "year": 2016,
        "make": "Honda",
        "model": "Accord",
        "base_book_value_cents": TEST_DEFAULTS["BASE_BOOK_VALUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_title_record_payload(donation_id: str, **overrides) -> dict:
    payload = {
        "donation_id": donation_id,
        "title_number": f"CA-TTL-{unique_suffix().upper()}",
        "owner_name": "Dora Nate",
    }
    payload.update(overrides)
    return payload


def create_pickup_order_payload(
    donation_id: str, tow_vendor_id: str, expected_donation_version: int, **overrides
) -> dict:
    payload = {
        "donation_id": donation_id,
        "tow_vendor_id": tow_vendor_id,
        "scheduled_start_utc": "2026-07-06T09:00:00Z",
        "scheduled_end_utc": "2026-07-06T11:00:00Z",
        "expected_donation_version": expected_donation_version,
    }
    payload.update(overrides)
    return payload


def create_auction_lot_payload(donation_id: str, venue_id: str, **overrides) -> dict:
    payload = {
        "donation_id": donation_id,
        "venue_id": venue_id,
        "lot_number": f"L-{unique_suffix().upper()}",
        "reserve_price_cents": TEST_DEFAULTS["RESERVE_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_tax_receipt_payload(donation_id: str, **overrides) -> dict:
    payload = {"donation_id": donation_id}
    payload.update(overrides)
    return payload


def create_remittance_batch_payload(charity_id: str, **overrides) -> dict:
    payload = {
        "charity_id": charity_id,
        "period_start_utc": "2026-07-01T00:00:00Z",
        "period_end_utc": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload
