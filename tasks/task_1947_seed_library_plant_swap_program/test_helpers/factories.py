"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": f"Site {_seq()}",
        "site_type": "LIBRARY_BRANCH",
        "region_zone": TEST_DEFAULTS["ZONE"],
        "label_stock_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(home_site_id: str, **overrides) -> dict:
    defaults = {
        "email": f"member{_seq()}@example.com",
        "full_name": "Test Member",
        "home_site_id": home_site_id,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "email": f"volunteer{_seq()}@example.com",
        "full_name": "Test Volunteer",
    }
    defaults.update(overrides)
    return defaults


def create_seed_variety_payload(**overrides) -> dict:
    defaults = {
        "variety_name": f"Variety {_seq()}",
        "species": "Solanum lycopersicum",
        "category": "VEGETABLE",
        "approved_zones": [TEST_DEFAULTS["ZONE"]],
        "invasive_flag": False,
        "rarity_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_seed_lot_payload(variety_id: str, home_site_id: str, **overrides) -> dict:
    defaults = {
        "variety_id": variety_id,
        "home_site_id": home_site_id,
        "lot_code": f"LOT-{_seq()}",
        "harvest_year": TEST_DEFAULTS["HARVEST_YEAR"],
        "seeds_received": 1000,
        "provisional_viability_pct": 90.00,
    }
    defaults.update(overrides)
    return defaults


def record_germination_test_payload(**overrides) -> dict:
    defaults = {
        "seeds_tested": 100,
        "sprouted_count": 90,
    }
    defaults.update(overrides)
    return defaults


def pack_payload(**overrides) -> dict:
    defaults = {
        "packet_count": 1,
        "seeds_per_packet": 20,
    }
    defaults.update(overrides)
    return defaults


def create_checkout_payload(member_id: str, packet_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "packet_id": packet_id,
    }
    defaults.update(overrides)
    return defaults


def create_swap_event_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "title": f"Swap Event {_seq()}",
        "start_at": "2026-09-05T10:00:00Z",
        "end_at": "2026-09-05T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def intake_item_payload(member_id: str, variety_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "variety_id": variety_id,
        "item_type": "SEED_PACKET",
        "condition": "GOOD",
    }
    defaults.update(overrides)
    return defaults


def redeem_credits_payload(member_id: str, credits: int, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "credits": credits,
    }
    defaults.update(overrides)
    return defaults


def create_packing_session_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "title": f"Packing Session {_seq()}",
        "start_at": "2026-10-11T09:00:00Z",
        "end_at": "2026-10-11T11:00:00Z",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def sign_up_payload(volunteer_id: str, **overrides) -> dict:
    defaults = {"volunteer_id": volunteer_id}
    defaults.update(overrides)
    return defaults
