"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_MAX_STRIKES,
    OPT_IN_BASE_FEE_CENTS,
    SEASON_END_DATE,
    SEASON_START_DATE,
    SEASON_YEAR,
    UNIVERSAL_FLAT_CREDIT_CENTS,
)


def create_service_zone_payload(**overrides) -> dict:
    defaults = {
        "name": "North",
        "service_model": "OPT_IN",
        "season_start_date": SEASON_START_DATE,
        "season_end_date": SEASON_END_DATE,
        "base_seasonal_fee_cents": OPT_IN_BASE_FEE_CENTS,
        "universal_flat_credit_cents": UNIVERSAL_FLAT_CREDIT_CENTS,
        "max_strikes_per_season": DEFAULT_MAX_STRIKES,
    }
    defaults.update(overrides)
    return defaults


def create_household_payload(zone_id: str, **overrides) -> dict:
    defaults = {"address_line": "1 Oak St", "zone_id": zone_id}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(household_id: str, expected_household_version: int, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "season_year": SEASON_YEAR,
        "expected_household_version": expected_household_version,
    }
    defaults.update(overrides)
    return defaults


def create_cart_payload(household_id: str, subscription_id: str, size_gallons=64, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "subscription_id": subscription_id,
        "size_gallons": size_gallons,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(zone_id: str, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "weekday": "MONDAY",
        "effective_start_date": SEASON_START_DATE,
        "effective_end_date": SEASON_END_DATE,
        "max_stops": 10,
        "max_tonnage_lbs": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_ticket_payload(subscription_id: str, route_id: str, service_date: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "route_id": route_id,
        "service_date": service_date,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(pickup_ticket_id: str, result="TAGGED_REJECTED", violation_codes=None, **overrides) -> dict:
    if violation_codes is None:
        violation_codes = [] if result == "PASSED" else ["PLASTIC_BAG"]
    defaults = {
        "pickup_ticket_id": pickup_ticket_id,
        "result": result,
        "violation_codes": violation_codes,
    }
    defaults.update(overrides)
    return defaults


def create_surge_event_payload(zone_id: str, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "event_type": "LEAF_SURGE",
        "service_date": "2026-11-07",
        "capacity_slots": 5,
        "booking_window_start": "2026-10-01T00:00:00Z",
        "booking_window_end": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_surge_booking_payload(surge_event_id: str, household_id: str, expected_surge_event_version: int, **overrides) -> dict:
    defaults = {
        "surge_event_id": surge_event_id,
        "household_id": household_id,
        "quantity_bundles": 2,
        "expected_surge_event_version": expected_surge_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Compost Central",
        "daily_receiving_capacity_lbs": 50000,
        "safety_contamination_item_limit": 5,
    }
    defaults.update(overrides)
    return defaults


def create_facility_delivery_payload(facility_id: str, route_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "route_id": route_id,
        "delivery_date": "2026-06-15",
        "window_start": "2026-06-15T09:00:00Z",
        "window_end": "2026-06-15T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_receive_payload(outcome="ACCEPT", gross_weight_lbs=1000, contaminated_item_count=0, **overrides) -> dict:
    defaults = {
        "outcome": outcome,
        "gross_weight_lbs": gross_weight_lbs,
        "contaminated_item_count": contaminated_item_count,
    }
    defaults.update(overrides)
    return defaults


def create_giveback_event_payload(zone_id: str, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "event_date": "2026-11-15",
        "per_household_cap_gallons": 10,
    }
    defaults.update(overrides)
    return defaults


def create_compost_claim_payload(giveback_event_id: str, household_id: str, gallons: int, **overrides) -> dict:
    defaults = {
        "giveback_event_id": giveback_event_id,
        "household_id": household_id,
        "gallons": gallons,
    }
    defaults.update(overrides)
    return defaults


def create_outreach_campaign_payload(**overrides) -> dict:
    defaults = {
        "channel": "MAIL",
        "topic": "ACCEPTABLE_MATERIALS",
        "budget_cents": 100000,
        "audience_size": 1000,
        "cost_per_impression_cents": 100,
        "end_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults
