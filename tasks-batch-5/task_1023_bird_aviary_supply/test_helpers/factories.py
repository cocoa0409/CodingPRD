"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "CUSTOMER_EMAIL": "test@example.com",
    "COMMON_NAME": "African Grey Parrot",
    "SCIENTIFIC_NAME": "Psittacus erithacus",
    "PERMIT_NUMBER": "CITES-TEST",
    "BAND_CODE": "BAND-001",
    "CAGE_LABEL": "Test Cage",
    "STATION_LABEL": "Test Station",
    "SKU": "SKU-TEST",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": DEFAULTS["CUSTOMER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_species_payload(**overrides) -> dict:
    defaults = {
        "common_name": DEFAULTS["COMMON_NAME"],
        "scientific_name": DEFAULTS["SCIENTIFIC_NAME"],
        "cites_appendix": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(species_id, **overrides) -> dict:
    defaults = {
        "species_id": species_id,
        "permit_number": DEFAULTS["PERMIT_NUMBER"],
        "valid_until": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bird_payload(species_id, **overrides) -> dict:
    defaults = {
        "species_id": species_id,
        "band_code": DEFAULTS["BAND_CODE"],
        "list_price_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_cage_payload(**overrides) -> dict:
    defaults = {
        "label": DEFAULTS["CAGE_LABEL"],
        "cage_class": "HOUSING",
        "capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(customer_id, cage_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "cage_id": cage_id,
        "planned_check_in": "2026-07-03T00:00:00Z",
        "planned_check_out": "2026-07-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    defaults = {
        "label": DEFAULTS["STATION_LABEL"],
        "service_types": ["WING_TRIM", "NAIL_TRIM"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(customer_id, grooming_station_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "grooming_station_id": grooming_station_id,
        "service_type": "WING_TRIM",
        "slot_start": "2026-07-10T10:00:00Z",
        "slot_end": "2026-07-10T10:30:00Z",
        "fee_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "tier": "STANDARD",
        "bird_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["SKU"],
        "feed_kind": "DRY",
        "quantity_on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id, cage_item_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "cage_item_id": cage_item_id,
        "build_qty": 1,
        "line_items": [{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}],
    }
    defaults.update(overrides)
    return defaults
