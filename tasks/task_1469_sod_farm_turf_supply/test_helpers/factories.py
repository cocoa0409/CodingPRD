"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "PRICE_CONFIG_NAME": "Std 2026",
    "VARIETY_NAME": "Tifway 419 Bermuda",
    "FIELD_NAME": "North 40",
    "FIELD_SQFT": 40000,
    # READY at the default clock (age 92 days) with a passing quality gate.
    "PLANTED_AT": "2026-05-01T00:00:00Z",
    "MOW_COUNT": 4,
    "LAST_MOWED_AT": "2026-07-31T06:00:00Z",
    "SOIL_MOISTURE_PCT": 45,
    "HEALTH_SCORE": 82,
    "CUSTOMER_NAME": "Aria Nguyen",
    "CUSTOMER_EMAIL": "aria@example.com",
    "CUSTOMER_PHONE": "555-0101",
    "CUSTOMER_ZONE": 2,
    "CUSTOMER_ADDRESS": "12 Oak Ln",
    "CREW_NAME": "Alpha Install",
    "DELIVERY_DATE": "2026-08-03",
    "WINDOW_START": "2026-08-03T08:00:00Z",
    "HARVEST_START": "2026-08-03T06:00:00Z",
    "HARVEST_END": "2026-08-03T06:45:00Z",
}


def create_price_config_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["PRICE_CONFIG_NAME"]}
    defaults.update(overrides)
    return defaults


def create_variety_config_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["VARIETY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "phone": DEFAULTS["CUSTOMER_PHONE"],
        "freight_zone": DEFAULTS["CUSTOMER_ZONE"],
        "address": DEFAULTS["CUSTOMER_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CREW_NAME"],
        "service_zones": [2],
    }
    defaults.update(overrides)
    return defaults


def create_field_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FIELD_NAME"],
        "field_sqft": DEFAULTS["FIELD_SQFT"],
        "last_planted_at": DEFAULTS["PLANTED_AT"],
        "mow_count": DEFAULTS["MOW_COUNT"],
        "last_mowed_at": DEFAULTS["LAST_MOWED_AT"],
        "soil_moisture_pct": DEFAULTS["SOIL_MOISTURE_PCT"],
        "health_score": DEFAULTS["HEALTH_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def quote_line(variety_id, grade, pallet_count, shortfall_slabs=0, shortfall_rolls=0) -> dict:
    return {
        "variety_id": variety_id,
        "grade": grade,
        "pallet_count": pallet_count,
        "shortfall_slabs": shortfall_slabs,
        "shortfall_rolls": shortfall_rolls,
    }


def create_quote_payload(customer_id, lines, z1, z2, z3, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "delivery_date": DEFAULTS["DELIVERY_DATE"],
        "settlement_method": "CARD",
        "z1_pallets": z1,
        "z2_pallets": z2,
        "z3_pallets": z3,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_harvest_batch_payload(field_id, expected_field_version, **overrides) -> dict:
    defaults = {
        "field_id": field_id,
        "grade": "PREMIUM",
        "pallet_count": 5,
        "shortfall_slabs": 0,
        "shortfall_rolls": 0,
        "scheduled_date": DEFAULTS["DELIVERY_DATE"],
        "expected_field_version": expected_field_version,
    }
    defaults.update(overrides)
    return defaults


def complete_harvest_batch_payload(**overrides) -> dict:
    defaults = {
        "actual_harvest_start": DEFAULTS["HARVEST_START"],
        "actual_harvest_end": DEFAULTS["HARVEST_END"],
    }
    defaults.update(overrides)
    return defaults


def confirm_order_payload(**overrides) -> dict:
    defaults = {"delivery_window_start": DEFAULTS["WINDOW_START"]}
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount, method="CARD") -> dict:
    return {"amount": amount, "method": method}


def create_reseed_plan_payload(**overrides) -> dict:
    defaults = {"planned_date": "2026-08-02"}
    defaults.update(overrides)
    return defaults


def complete_reseed_plan_payload(actual_seed_lbs) -> dict:
    return {"actual_seed_lbs": actual_seed_lbs}


def create_truck_block_payload(**overrides) -> dict:
    defaults = {
        "freight_zone": 1,
        "window_start": "2026-08-04T08:00:00Z",
        "window_end": "2026-08-04T10:00:00Z",
        "reason": "",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(weather_case="W1") -> dict:
    return {"weather_case": weather_case}


def create_watering_log_payload(log_date, moisture_reading) -> dict:
    return {"log_date": log_date, "moisture_reading": moisture_reading}


def create_crew_referral_payload(crew_id) -> dict:
    return {"crew_id": crew_id}


def schedule_crew_payload(scheduled_date) -> dict:
    return {"scheduled_date": scheduled_date}
