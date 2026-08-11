"""Payload factories — one per entity, input fields only.

The standard customer profile (175 cm / 70 kg / boot sole 300 mm / TYPE_2 /
born 1996-01-15) yields a fitment DIN of 5.75 under the PRD formula at the
default logical-clock date.
"""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "CUSTOMER_DOB": "1996-01-15",
    "CUSTOMER_HEIGHT_CM": 175,
    "CUSTOMER_WEIGHT_KG": 70,
    "CUSTOMER_BOOT_SOLE_MM": 300,
    "CUSTOMER_SKIER_TYPE": "TYPE_2",
    "GEAR_TYPE": "SKI",
    "TIER": "STANDARD",
    "DIN_MIN": 2,
    "DIN_MAX": 10,
    "PURCHASE_PRICE_CENTS": 60000,
    "BASE_DAILY_RATE_CENTS": 4000,
    "START_DATE": "2026-12-10",
    "END_DATE": "2026-12-12",
    "PICKUP_METHOD": "SHOP",
    "SEASON_START_DATE": "2026-11-01",
    "SEASON_END_DATE": "2027-03-31",
    "PACKAGE_TIER": "JUNIOR_SKI",
    "LEASE_DEPOSIT_CENTS": 10000,
    "DEMO_DATE": "2026-12-01",
    "FEE_PAID_CENTS": 5000,
    "WINDOW_DATE": "2026-12-20",
    "WINDOW_START": "10:00",
    "WINDOW_END": "12:00",
    "LOCATION_LABEL": "CANYON",
    "VAN_CAPACITY": 4,
    "CAPACITY_DATE": "2026-12-01",
    "CAPACITY_BASE": 480,
    "CAPACITY_RUSH": 120,
}


def _n() -> int:
    return next(_counter)


def create_customer_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Test Customer {n}",
        "email": f"customer{n}@example.com",
        "date_of_birth": DEFAULTS["CUSTOMER_DOB"],
        "height_cm": DEFAULTS["CUSTOMER_HEIGHT_CM"],
        "weight_kg": DEFAULTS["CUSTOMER_WEIGHT_KG"],
        "boot_sole_mm": DEFAULTS["CUSTOMER_BOOT_SOLE_MM"],
        "skier_type": DEFAULTS["CUSTOMER_SKIER_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_item_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "gear_type": DEFAULTS["GEAR_TYPE"],
        "size_label": f"{160 + (n % 15)}cm",
        "tier": DEFAULTS["TIER"],
        "din_min": DEFAULTS["DIN_MIN"],
        "din_max": DEFAULTS["DIN_MAX"],
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "base_daily_rate_cents": DEFAULTS["BASE_DAILY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
        "pickup_method": DEFAULTS["PICKUP_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_item_payload(**overrides) -> dict:
    defaults = {
        "gear_type_requested": DEFAULTS["GEAR_TYPE"],
        "tier_requested": DEFAULTS["TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_tune_ticket_payload(customer_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "customer_id": customer_id,
        "own_gear_description": f"customer-owned gear {n}",
        "services": ["WAX"],
        "rush": False,
    }
    defaults.update(overrides)
    return defaults


def create_season_lease_payload(junior_customer_id: str, guardian_customer_id: str, **overrides) -> dict:
    defaults = {
        "junior_customer_id": junior_customer_id,
        "guardian_customer_id": guardian_customer_id,
        "season_start_date": DEFAULTS["SEASON_START_DATE"],
        "season_end_date": DEFAULTS["SEASON_END_DATE"],
        "package_tier": DEFAULTS["PACKAGE_TIER"],
        "deposit_cents": DEFAULTS["LEASE_DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_demo_credit_payload(customer_id: str, equipment_item_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "equipment_item_id": equipment_item_id,
        "demo_date": DEFAULTS["DEMO_DATE"],
        "fee_paid_cents": DEFAULTS["FEE_PAID_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(customer_id: str, equipment_item_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "equipment_item_id": equipment_item_id,
    }
    defaults.update(overrides)
    return defaults


def create_damage_assessment_payload(reservation_id: str, equipment_item_id: str, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "equipment_item_id": equipment_item_id,
        "severity": "COSMETIC",
    }
    defaults.update(overrides)
    return defaults


def create_pickup_window_payload(**overrides) -> dict:
    defaults = {
        "service_date": DEFAULTS["WINDOW_DATE"],
        "start_time": DEFAULTS["WINDOW_START"],
        "end_time": DEFAULTS["WINDOW_END"],
        "location_label": DEFAULTS["LOCATION_LABEL"],
        "van_capacity": DEFAULTS["VAN_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_pickup_booking_payload(pickup_window_id: str, reservation_id: str, **overrides) -> dict:
    defaults = {
        "pickup_window_id": pickup_window_id,
        "reservation_id": reservation_id,
    }
    defaults.update(overrides)
    return defaults


def create_shop_day_capacity_payload(**overrides) -> dict:
    defaults = {
        "service_date": DEFAULTS["CAPACITY_DATE"],
        "base_labor_minutes": DEFAULTS["CAPACITY_BASE"],
        "rush_reserved_minutes": DEFAULTS["CAPACITY_RUSH"],
    }
    defaults.update(overrides)
    return defaults
