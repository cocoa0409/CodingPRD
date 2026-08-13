"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "DONOR_LEGAL_NAME": "Test Bistro",
    "DONOR_EIN": "123456789",
    "DONOR_EMAIL": "ops@bistro.example",
    "AGENCY_NAME": "Test Agency",
    "DRIVER_NAME": "V One",
    "DRIVER_EMAIL": "v1@example.com",
    "VEHICLE_CAPACITY_LBS": 500,
    "COOLER_SLOT_COUNT": 2,
    "COOLER_LABEL": "C1",
    "COOLER_LITERS": 30,
    "OFFER_CATEGORY": "COLD_HELD",
    "OFFER_ESTIMATED_LBS": 50,
    "PICKUP_WINDOW_START": "2026-08-02T10:00:00Z",
    "PICKUP_WINDOW_END": "2026-08-02T12:00:00Z",
    "WINDOW_START": "2026-08-02T09:00:00Z",
    "WINDOW_END": "2026-08-02T15:00:00Z",
}


def create_donor_site_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["DONOR_LEGAL_NAME"],
        "ein": DEFAULTS["DONOR_EIN"],
        "contact_email": DEFAULTS["DONOR_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_recipient_agency_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["AGENCY_NAME"],
        "accepts_categories": ["COLD_HELD"],
        "capacity_cold_held_lbs": 100,
        "capacity_hot_held_lbs": 0,
        "capacity_produce_lbs": 0,
        "capacity_shelf_stable_lbs": 0,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_driver_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["DRIVER_NAME"],
        "email": DEFAULTS["DRIVER_EMAIL"],
        "vehicle_capacity_lbs": DEFAULTS["VEHICLE_CAPACITY_LBS"],
        "cooler_slot_count": DEFAULTS["COOLER_SLOT_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_availability_window_payload(**overrides) -> dict:
    defaults = {
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_cooler_payload(**overrides) -> dict:
    defaults = {
        "label": DEFAULTS["COOLER_LABEL"],
        "capacity_liters": DEFAULTS["COOLER_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_donation_offer_payload(**overrides) -> dict:
    defaults = {
        "food_category": DEFAULTS["OFFER_CATEGORY"],
        "estimated_weight_lbs": DEFAULTS["OFFER_ESTIMATED_LBS"],
        "pickup_window_start": DEFAULTS["PICKUP_WINDOW_START"],
        "pickup_window_end": DEFAULTS["PICKUP_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    """The common 2026 rate card used across tax tests (PRD §3.8)."""
    defaults = {
        "effective_start": "2026-01-01T00:00:00Z",
        "effective_end": "2027-01-01T00:00:00Z",
        "cold_held_fmv_cents_per_lb": 300,
        "cold_held_basis_cents_per_lb": 100,
        "hot_held_fmv_cents_per_lb": 250,
        "hot_held_basis_cents_per_lb": 90,
        "produce_fmv_cents_per_lb": 180,
        "produce_basis_cents_per_lb": 60,
        "shelf_stable_fmv_cents_per_lb": 120,
        "shelf_stable_basis_cents_per_lb": 50,
    }
    defaults.update(overrides)
    return defaults


def issue_tax_receipt_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
