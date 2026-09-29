"""Payload factories — one per write endpoint, input fields only."""

DEFAULTS = {
    "COMMUNITY_NAME": "Cedar Ridge Senior Living",
    "CARE_LEVELS_OFFERED": [
        "INDEPENDENT_LIVING",
        "ASSISTED_LIVING",
        "MEMORY_CARE",
        "SKILLED_NURSING",
    ],
    "VENUE_NAME": "Main Dining Room",
    "RESIDENT_NAME": "Eleanor Whitfield",
    "BASELINE_WEIGHT_KG": 80.0,
    "SEAT_CAPACITY": 10,
    "MENU_ITEM_NAME": "Roast Chicken Plate",
}


# --------------------------------------------------------------------------
# Program setup
# --------------------------------------------------------------------------
def create_community_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["COMMUNITY_NAME"],
        "care_levels_offered": list(DEFAULTS["CARE_LEVELS_OFFERED"]),
    }
    payload.update(overrides)
    return payload


def create_venue_payload(community_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "name": DEFAULTS["VENUE_NAME"],
        "venue_kind": "MAIN_DINING",
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
        "care_levels_served": list(DEFAULTS["CARE_LEVELS_OFFERED"]),
    }
    payload.update(overrides)
    return payload


def create_resident_payload(community_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "full_name": DEFAULTS["RESIDENT_NAME"],
        "care_level": "ASSISTED_LIVING",
        "baseline_weight_kg": DEFAULTS["BASELINE_WEIGHT_KG"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Diet orders and substitution rules
# --------------------------------------------------------------------------
def create_diet_order_payload(
    resident_id: str, expected_resident_version: int, **overrides
) -> dict:
    payload = {
        "resident_id": resident_id,
        "texture_level": "REGULAR",
        "liquid_consistency": "THIN",
        "expected_resident_version": expected_resident_version,
    }
    payload.update(overrides)
    return payload


def dietitian_review_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resubmit_diet_order_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def discontinue_diet_order_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def create_substitution_rule_payload(**overrides) -> dict:
    payload = {
        "trigger_type": "ALLERGEN",
        "match_value": "SHELLFISH",
        "replacement_item_code": "SAFE-ALT",
        "priority_rank": 1,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Menu cycles, items, extensions, ballots
# --------------------------------------------------------------------------
def create_menu_cycle_payload(community_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "cycle_number": 1,
        "week_count": 1,
        "effective_start_date": "2026-08-01",
        "effective_end_date": "2026-08-31",
    }
    payload.update(overrides)
    return payload


def create_menu_item_payload(**overrides) -> dict:
    payload = {
        "item_code": "CHICKEN-PLATE",
        "name": DEFAULTS["MENU_ITEM_NAME"],
        "day_index": 1,
        "meal_period": "LUNCH",
        "base_texture": "REGULAR",
    }
    payload.update(overrides)
    return payload


def create_therapeutic_extension_payload(diet_code: str, **overrides) -> dict:
    payload = {"diet_code": diet_code}
    payload.update(overrides)
    return payload


def review_extension_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def refresh_menu_cycle_payload(refresh_reason: str = "Committee-driven rotation refresh",
                               **overrides) -> dict:
    payload = {"refresh_reason": refresh_reason}
    payload.update(overrides)
    return payload


def cast_ballot_payload(resident_id: str, menu_item_code: str, sentiment: str,
                        **overrides) -> dict:
    payload = {
        "resident_id": resident_id,
        "menu_item_code": menu_item_code,
        "sentiment": sentiment,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Reservations
# --------------------------------------------------------------------------
def create_reservation_payload(
    resident_id: str,
    venue_id: str,
    service_date: str,
    meal_period: str,
    seat_start_utc: str,
    expected_venue_version: int,
    **overrides,
) -> dict:
    payload = {
        "resident_id": resident_id,
        "venue_id": venue_id,
        "service_date": service_date,
        "meal_period": meal_period,
        "seat_start_utc": seat_start_utc,
        "party_size": 1,
        "expected_venue_version": expected_venue_version,
    }
    payload.update(overrides)
    return payload


def release_reservation_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Meal tickets
# --------------------------------------------------------------------------
def create_meal_ticket_payload(
    venue_id: str, ticket_type: str, service_date: str, meal_period: str, **overrides
) -> dict:
    payload = {
        "venue_id": venue_id,
        "ticket_type": ticket_type,
        "service_date": service_date,
        "meal_period": meal_period,
    }
    payload.update(overrides)
    return payload


def void_meal_ticket_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Temperature logs
# --------------------------------------------------------------------------
def create_temperature_log_payload(
    probe_point: str, temperature_f: float, **overrides
) -> dict:
    payload = {"probe_point": probe_point, "temperature_f": temperature_f}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Intake observations and plan-of-care reviews
# --------------------------------------------------------------------------
def create_intake_observation_payload(
    observation_date: str, meal_period: str, intake_pct: float, **overrides
) -> dict:
    payload = {
        "observation_date": observation_date,
        "meal_period": meal_period,
        "intake_pct": intake_pct,
    }
    payload.update(overrides)
    return payload


def complete_review_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Reconciliations
# --------------------------------------------------------------------------
def create_reconciliation_payload(
    community_id: str, period_start_date: str, period_end_date: str, **overrides
) -> dict:
    payload = {
        "community_id": community_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
    }
    payload.update(overrides)
    return payload


def finalize_reconciliation_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload
