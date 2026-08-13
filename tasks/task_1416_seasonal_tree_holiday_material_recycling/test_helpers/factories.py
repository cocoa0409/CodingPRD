"""Payload factories — one per entity, input fields only (PRD Section 4)."""
from .constants import (
    CLAIM_CLOSE_AT,
    CLAIM_OPEN_AT,
    PICKUP_END,
    PICKUP_START,
    RUN_END,
    RUN_START,
    SITE_CLOSE_DATE,
    SITE_OPEN_DATE,
    TEST_DEFAULTS,
    WINDOW_END,
    WINDOW_START,
    ZONE_COLLECTION_DATE,
)

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_program_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"TreeCycle {n}",
        "season_label": "Winter 2027",
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(program_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "program_id": program_id,
        "name": f"North Lot {n}",
        "address": f"{n} Pine Ave",
        "capacity_cy": TEST_DEFAULTS["SITE_CAPACITY_CY"],
        "open_date": SITE_OPEN_DATE,
        "close_date": SITE_CLOSE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(program_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "program_id": program_id,
        "zone_code": f"NW-{n}",
        "collection_date": ZONE_COLLECTION_DATE,
        "daily_tree_capacity": TEST_DEFAULTS["ZONE_DAILY_TREE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_household_payload(program_id: str, zone_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "program_id": program_id,
        "zone_id": zone_id,
        "address": f"{n} Oak St",
        "contact_email": f"household{n}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(household_id: str, zone_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "zone_id": zone_id,
        "tree_count": 1,
        "size_class": "SMALL",
        "prep_attestation": True,
    }
    defaults.update(overrides)
    return defaults


def create_intake_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "source_type": "CITY_CREW",
        "tree_count": 10,
        "size_class": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "category": "OTHER",
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(program_id: str, site_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "site_id": site_id,
        "scheduled_start": RUN_START,
        "scheduled_end": RUN_END,
        "material_class": "MIXED_LOAD",
    }
    defaults.update(overrides)
    return defaults


def create_mulch_event_payload(program_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "program_id": program_id,
        "name": f"Mulch Day {n}",
        "claim_open_at": CLAIM_OPEN_AT,
        "claim_close_at": CLAIM_CLOSE_AT,
        "pickup_start": PICKUP_START,
        "pickup_end": PICKUP_END,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(event_id: str, household_id: str, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "household_id": household_id,
        "requested_cy": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(program_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "program_id": program_id,
        "full_name": f"Vol {n}",
        "email": f"vol{n}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(volunteer_id: str, site_id: str, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "site_id": site_id,
        "start_at": "2027-01-09T09:00:00Z",
        "end_at": "2027-01-09T12:00:00Z",
        "shift_role": "LOADER",
    }
    defaults.update(overrides)
    return defaults
