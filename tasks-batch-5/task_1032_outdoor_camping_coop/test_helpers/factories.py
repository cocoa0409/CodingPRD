"""Payload factories — one per entity, input fields only.

Each factory returns a dict with sensible defaults that individual tests
override via **overrides.
"""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": _uniq("member") + "@example.com",
        "full_name": "Test Member",
    }
    defaults.update(overrides)
    return defaults


def create_gear_sku_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Gear",
        "category": "TENT",
        "retail_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_gear_unit_payload(gear_sku_id: str, **overrides) -> dict:
    defaults = {
        "gear_sku_id": gear_sku_id,
        "serial_number": _uniq("SN"),
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(member_id: str, gear_unit_id: str, start_at: str,
                          due_at: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "gear_unit_id": gear_unit_id,
        "start_at": start_at,
        "due_at": due_at,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(member_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(member_id: str, gear_sku_id: str,
                            described_condition: str, payout_method: str,
                            **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "gear_sku_id": gear_sku_id,
        "described_condition": described_condition,
        "payout_method": payout_method,
    }
    defaults.update(overrides)
    return defaults


def create_class_trip_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Trip",
        "category": "CLASS",
        "start_at": "2026-07-20T08:00:00Z",
        "end_at": "2026-07-20T12:00:00Z",
        "capacity": 3,
        "price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(member_id: str, class_trip_id: str,
                           expected_classtrip_version: int, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "class_trip_id": class_trip_id,
        "expected_classtrip_version": expected_classtrip_version,
    }
    defaults.update(overrides)
    return defaults


def create_permit_allocation_payload(**overrides) -> dict:
    defaults = {
        "park_name": "Test Park",
        "season_start": "2026-08-01T00:00:00Z",
        "season_end": "2026-08-31T23:59:59Z",
        "total_quota": 5,
        "price_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_permit_pass_payload(member_id: str, permit_allocation_id: str,
                               entry_date: str, expected_allocation_version: int,
                               **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "permit_allocation_id": permit_allocation_id,
        "entry_date": entry_date,
        "expected_allocation_version": expected_allocation_version,
    }
    defaults.update(overrides)
    return defaults
