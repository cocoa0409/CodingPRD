"""Payload factories with valid defaults for every writable resource.

Each factory returns a payload that passes every field-shape rule in the PRD, so
a test only overrides the one or two fields it is actually exercising.
"""

import itertools
from typing import Any, Dict, List, Optional

from .types import (
    AddonService,
    CertType,
    ClubTier,
    DayPart,
    EquipmentType,
    ProductCategory,
    ProgramTier,
)

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def manufacturer_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload = {
        "legal_name": f"Northvale Foods LLC {n}",
        "billing_email": f"ap{n}@northvale.example",
        "program_tier": ProgramTier.STANDARD,
        "credit_limit_cents": 5_000_000,
        "credit_terms_days": 30,
    }
    payload.update(overrides)
    return payload


def club_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload = {
        "club_number": f"C{4000 + (n % 6000):04d}",
        "name": f"Riverbend Club {n}",
        "region_code": "MW",
        "club_tier": ClubTier.STANDARD,
        "daily_event_capacity": 6,
        "food_station_count": 3,
        "health_permit_expires_on": "2027-12-31",
    }
    payload.update(overrides)
    return payload


def food_product_payload(manufacturer_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload = {
        "manufacturer_id": manufacturer_id,
        "sku": f"NV-FOOD-{n:04d}",
        "name": f"Aged Cheddar Bites {n}",
        "category": ProductCategory.DAIRY,
        "requires_food_handling": True,
        "requires_heat_equipment": False,
        "allergen_flag": False,
        "unit_cost_cents": 210,
        "samples_per_case": 60,
        "weekly_sample_case_pool": 40,
    }
    payload.update(overrides)
    return payload


def non_food_product_payload(manufacturer_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload = {
        "manufacturer_id": manufacturer_id,
        "sku": f"NV-NONFOOD-{n:04d}",
        "name": f"Countertop Demo Kit {n}",
        "category": ProductCategory.HOUSEHOLD,
        "requires_food_handling": False,
        "requires_heat_equipment": False,
        "allergen_flag": False,
        "unit_cost_cents": 1500,
        "samples_per_case": 4,
        "weekly_sample_case_pool": 30,
    }
    payload.update(overrides)
    return payload


def baseline_payload(club_id: str, product_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "club_id": club_id,
        "product_id": product_id,
        "baseline_weekly_units": 140,
        "baseline_unit_price_cents": 1299,
        "baseline_week_start_date": "2026-09-14",
    }
    payload.update(overrides)
    return payload


def demonstrator_payload(home_club_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload = {
        "home_club_id": home_club_id,
        "full_name": f"Dana Roth {n}",
        "hourly_rate_cents": 2400,
    }
    payload.update(overrides)
    return payload


def certification_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload = {
        "cert_type": CertType.FOOD_HANDLER,
        "certificate_number": f"FH-2026-{n:04d}",
        "issued_on": "2026-02-01",
        "expires_on": "2027-02-01",
    }
    payload.update(overrides)
    return payload


def equipment_unit_payload(club_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload = {
        "club_id": club_id,
        "asset_tag": f"EQ-{n:05d}",
        "equipment_type": EquipmentType.REFRIGERATED_CART,
    }
    payload.update(overrides)
    return payload


def demo_event_payload(
    manufacturer_id: str,
    club_id: str,
    product_id: str,
    event_date: str = "2026-09-14",
    day_part: str = DayPart.MIDDAY,
    requested_sample_cases: int = 6,
    addon_services: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "manufacturer_id": manufacturer_id,
        "club_id": club_id,
        "product_id": product_id,
        "event_date": event_date,
        "day_part": day_part,
        "requested_sample_cases": requested_sample_cases,
        "addon_services": addon_services if addon_services is not None else [],
    }
    payload.update(overrides)
    return payload


def reservation_payload(
    equipment_unit_id: str,
    demo_event_id: str,
    window_start_utc: str,
    window_end_utc: str,
) -> Dict[str, Any]:
    return {
        "equipment_unit_id": equipment_unit_id,
        "demo_event_id": demo_event_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }


def shipment_payload(cases_shipped: int, carrier_reference: str) -> Dict[str, Any]:
    return {"cases_shipped": cases_shipped, "carrier_reference": carrier_reference}


def reconciliation_payload(
    units_sampled: int, units_wasted: int, units_returned: int
) -> Dict[str, Any]:
    return {
        "units_sampled": units_sampled,
        "units_wasted": units_wasted,
        "units_returned": units_returned,
    }


def lift_measurement_payload(
    measurement_variant: str,
    units_sold_in_window: int,
    expected_demo_event_version: int,
) -> Dict[str, Any]:
    return {
        "measurement_variant": measurement_variant,
        "units_sold_in_window": units_sold_in_window,
        "expected_demo_event_version": expected_demo_event_version,
    }


def history_entry(
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    assignment_status: str,
    role: str,
    check_in_at: Optional[str] = None,
    check_out_at: Optional[str] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "assignment_status": assignment_status,
        "role": role,
    }
    if check_in_at is not None:
        entry["check_in_at"] = check_in_at
    if check_out_at is not None:
        entry["check_out_at"] = check_out_at
    return entry


ALL_ADDON_SERVICES = [
    AddonService.EXTRA_TABLE,
    AddonService.VIDEO_LOOP,
    AddonService.ALLERGEN_SIGNAGE,
    AddonService.PREMIUM_PLACEMENT,
    AddonService.BILINGUAL_DEMONSTRATOR,
]
