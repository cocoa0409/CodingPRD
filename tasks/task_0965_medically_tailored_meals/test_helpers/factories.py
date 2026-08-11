"""Payload factories — one per entity, input fields only (PRD §3).

Named menu-item recipes mirror the catalog meals used across the workflow
chains. Nutrient values only matter to the freeze gates; billing prices off
the payer rate card, never off `base_cost_cents` (PRD §3.4, §3.7).
"""

DEFAULTS = {
    "MEMBER_FULL_NAME": "Test Member",
    "PAYER_TYPE": "MEDICAID_WAIVER",
    "PAYER_MEMBER_ID": "W-000",
    "INCOME_FPL_PERCENT": 130,
    "HOUSEHOLD_SIZE": 2,
    "DIAGNOSIS_CODES": ["N18.3"],
    "REFERRED_DIET_TYPE": "RENAL",
    "REFERRAL_EXPIRES_AT": "2026-06-30",
    "MEALS_PER_WEEK": 10,
    "EFFECTIVE_FROM": "2026-01-01",
    "EFFECTIVE_TO": "2026-12-31",
    "WEEK_START_DATE": "2026-05-04",
    "DRIVER_ID": "drv-1",
    "ROUTE_DATE": "2026-05-06",
    "START_TIME": "08:00",
    "END_TIME": "12:00",
    "CAPACITY_STOPS": 20,
    "AUTHORIZED_UNITS": 4,
    "MAX_AMOUNT_CENTS": 500_000,
    "AUTH_START_DATE": "2026-01-01",
    "AUTH_END_DATE": "2026-12-31",
    "ASSESSED_AT": "2026-04-20",
    "WEIGHT_KG": 75.0,
    "HBA1C_PCT": 7.0,
}

# Named catalog meals (input fields only).
MENU_ITEM_RECIPES = {
    "rice_bowl": {
        "name": "Rice Bowl", "sodium_mg": 400, "potassium_mg": 300,
        "phosphorus_mg": 150, "carbs_g": 40, "protein_g": 20,
        "allergen_codes": [], "base_cost_cents": 700,
    },
    "broth_soup": {
        "name": "Broth Soup", "sodium_mg": 100, "potassium_mg": 100,
        "phosphorus_mg": 50, "carbs_g": 10, "protein_g": 10,
        "allergen_codes": [], "base_cost_cents": 600,
    },
    "chicken_plate": {
        "name": "Chicken Plate", "sodium_mg": 600, "potassium_mg": 500,
        "phosphorus_mg": 300, "carbs_g": 45, "protein_g": 35,
        "allergen_codes": [], "base_cost_cents": 900,
    },
    "lentil_stew": {
        "name": "Lentil Stew", "sodium_mg": 1500, "potassium_mg": 2500,
        "phosphorus_mg": 700, "carbs_g": 40, "protein_g": 20,
        "allergen_codes": [], "base_cost_cents": 800,
    },
    "banana": {
        "name": "Banana", "sodium_mg": 100, "potassium_mg": 2000,
        "phosphorus_mg": 50, "carbs_g": 10, "protein_g": 5,
        "allergen_codes": [], "base_cost_cents": 200,
    },
    "peanut_chicken": {
        "name": "Peanut Chicken", "sodium_mg": 100, "potassium_mg": 100,
        "phosphorus_mg": 50, "carbs_g": 10, "protein_g": 15,
        "allergen_codes": ["PEANUT"], "base_cost_cents": 800,
    },
    "light_snack": {
        "name": "Light Snack", "sodium_mg": 100, "potassium_mg": 100,
        "phosphorus_mg": 50, "carbs_g": 10, "protein_g": 15,
        "allergen_codes": [], "base_cost_cents": 300,
    },
}


def create_member_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["MEMBER_FULL_NAME"],
        "payer_type": DEFAULTS["PAYER_TYPE"],
        "payer_member_id": DEFAULTS["PAYER_MEMBER_ID"],
        "allergies": [],
        "income_fpl_percent": DEFAULTS["INCOME_FPL_PERCENT"],
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
    }
    payload.update(overrides)
    return payload


def create_referral_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "diagnosis_codes": list(DEFAULTS["DIAGNOSIS_CODES"]),
        "referred_diet_type": DEFAULTS["REFERRED_DIET_TYPE"],
        "expires_at": DEFAULTS["REFERRAL_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_prescription_payload(member_id: str, referral_id: str, **overrides) -> dict:
    # Default nutrient envelope keeps every standard freeze chain compliant:
    # daily_protein_g_min 4 (weekly floor 28) is satisfied by the smallest
    # standard basket (Rice Bowl x1 + Broth Soup x1 = 30 g/week).
    payload = {
        "member_id": member_id,
        "referral_id": referral_id,
        "diet_type": DEFAULTS["REFERRED_DIET_TYPE"],
        "daily_sodium_mg_max": 2000,
        "daily_potassium_mg_max": 2000,
        "daily_phosphorus_mg_max": 1000,
        "daily_carbs_g_max": 250,
        "daily_protein_g_min": 4,
        "excluded_allergens": [],
        "meals_per_week": DEFAULTS["MEALS_PER_WEEK"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_menu_item_payload(recipe: str = "rice_bowl", **overrides) -> dict:
    payload = dict(MENU_ITEM_RECIPES[recipe])
    payload.update(overrides)
    return payload


def create_menu_cycle_payload(member_id: str, prescription_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "prescription_id": prescription_id,
        "week_start_date": DEFAULTS["WEEK_START_DATE"],
    }
    payload.update(overrides)
    return payload


def create_cycle_item_payload(menu_item_id: str, quantity: int = 1, **overrides) -> dict:
    payload = {"menu_item_id": menu_item_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_route_payload(**overrides) -> dict:
    payload = {
        "driver_id": DEFAULTS["DRIVER_ID"],
        "route_date": DEFAULTS["ROUTE_DATE"],
        "start_time": DEFAULTS["START_TIME"],
        "end_time": DEFAULTS["END_TIME"],
        "capacity_stops": DEFAULTS["CAPACITY_STOPS"],
    }
    payload.update(overrides)
    return payload


def create_delivery_payload(member_id: str, menu_cycle_id: str, route_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "menu_cycle_id": menu_cycle_id,
        "route_id": route_id,
        "service_date": DEFAULTS["ROUTE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_cold_chain_reading_payload(recorded_at: str, temp_celsius: float, **overrides) -> dict:
    payload = {"recorded_at": recorded_at, "temp_celsius": temp_celsius}
    payload.update(overrides)
    return payload


def create_reauthorization_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "authorized_units": DEFAULTS["AUTHORIZED_UNITS"],
        "max_amount_cents": DEFAULTS["MAX_AMOUNT_CENTS"],
        "start_date": DEFAULTS["AUTH_START_DATE"],
        "end_date": DEFAULTS["AUTH_END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_outcome_assessment_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "assessed_at": DEFAULTS["ASSESSED_AT"],
        "weight_kg": DEFAULTS["WEIGHT_KG"],
        "hba1c_pct": DEFAULTS["HBA1C_PCT"],
    }
    payload.update(overrides)
    return payload


def create_claim_payload(member_id: str, menu_cycle_id: str, authorization_id: str,
                         expected_reauthorization_version: int, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "menu_cycle_id": menu_cycle_id,
        "authorization_id": authorization_id,
        "expected_reauthorization_version": expected_reauthorization_version,
    }
    payload.update(overrides)
    return payload
