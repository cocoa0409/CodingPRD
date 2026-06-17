"""Payload factories — one per entity, input fields only.

Defaults mirror the canonical rate card / catalog item / unit / account used
across the design indices (daily 4000, weekly 20000, four_week 60000, deposit
50000, waiver 1500, fuel 200/L, cleaning 8000, late_mult 1.5; HEAVY_EQUIPMENT
item, fuel_capacity 40, service_due 1000, credit_limit 1000000).
"""

DEFAULTS = {
    "RATE_CARD_NAME": "Std",
    "DAILY_RATE_CENTS": 4000,
    "WEEKLY_RATE_CENTS": 20000,
    "FOUR_WEEK_RATE_CENTS": 60000,
    "DEPOSIT_CENTS": 50000,
    "DAMAGE_WAIVER_DAILY_CENTS": 1500,
    "FUEL_REFILL_CENTS_PER_LITER": 200,
    "CLEANING_FEE_CENTS": 8000,
    "LATE_FEE_MULTIPLIER": 1.5,
    "CATALOG_NAME": "Mini Excavator",
    "CATEGORY": "HEAVY_EQUIPMENT",
    "FUEL_CAPACITY_LITERS": 40,
    "SERVICE_DUE_AT_DAYS": 1000,
    "COMPANY_NAME": "Acme",
    "CREDIT_LIMIT_CENTS": 1_000_000,
    "TRUCK_NAME": "Truck-1",
    "BUFFER_MINUTES": 60,
}


def create_rate_card_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RATE_CARD_NAME"],
        "daily_rate_cents": DEFAULTS["DAILY_RATE_CENTS"],
        "weekly_rate_cents": DEFAULTS["WEEKLY_RATE_CENTS"],
        "four_week_rate_cents": DEFAULTS["FOUR_WEEK_RATE_CENTS"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
        "damage_waiver_daily_cents": DEFAULTS["DAMAGE_WAIVER_DAILY_CENTS"],
        "fuel_refill_cents_per_liter": DEFAULTS["FUEL_REFILL_CENTS_PER_LITER"],
        "cleaning_fee_cents": DEFAULTS["CLEANING_FEE_CENTS"],
        "late_fee_multiplier": DEFAULTS["LATE_FEE_MULTIPLIER"],
    }
    defaults.update(overrides)
    return defaults


def create_catalog_item_payload(rate_card_id: str, **overrides) -> dict:
    defaults = {
        "rate_card_id": rate_card_id,
        "sku": "MX15",
        "name": DEFAULTS["CATALOG_NAME"],
        "category": DEFAULTS["CATEGORY"],
        "requires_delivery": False,
        "fuel_capacity_liters": DEFAULTS["FUEL_CAPACITY_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(catalog_item_id: str, **overrides) -> dict:
    defaults = {
        "catalog_item_id": catalog_item_id,
        "asset_tag": "EU-1",
        "service_due_at_days": DEFAULTS["SERVICE_DUE_AT_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_contractor_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_truck_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TRUCK_NAME"],
        "buffer_minutes": DEFAULTS["BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(contractor_account_id: str, catalog_item_id: str,
                               **overrides) -> dict:
    defaults = {
        "contractor_account_id": contractor_account_id,
        "catalog_item_id": catalog_item_id,
        "fulfillment_method": "PICKUP",
        "rental_start_date": "2026-06-01",
        "rental_end_date": "2026-06-10",
        "damage_waiver_opted": False,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(delivery_truck_id: str, delivery_window_start: str,
                            delivery_window_end: str, **overrides) -> dict:
    defaults = {
        "delivery_truck_id": delivery_truck_id,
        "delivery_window_start": delivery_window_start,
        "delivery_window_end": delivery_window_end,
    }
    defaults.update(overrides)
    return defaults


def create_return_inspection_payload(rental_agreement_id: str, **overrides) -> dict:
    defaults = {
        "rental_agreement_id": rental_agreement_id,
        "return_fuel_level_liters": 40,
        "cleanliness": "CLEAN",
        "damage_assessed_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_ticket_payload(equipment_unit_id: str, **overrides) -> dict:
    defaults = {
        "equipment_unit_id": equipment_unit_id,
        "reason": "SCHEDULED_SERVICE",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
