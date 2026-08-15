"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

from .constants import CAMPAIGN_DEFAULTS, EVENT_WINDOW

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_campaign_payload(**overrides) -> dict:
    defaults = dict(CAMPAIGN_DEFAULTS)
    defaults["season_year"] = 2026  # tests override + re-clock when reusing a year
    defaults.update(overrides)
    return defaults


def create_agency_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "agency_code": f"AG{n:03d}",
        "legal_name": f"Partner Agency {n}",
        "referral_quota": 50,
        "contact_email": f"agency{n}@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(agency_id: str, campaign_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "agency_id": agency_id,
        "campaign_id": campaign_id,
        "primary_caregiver_name": f"Caregiver {n}",
        "caregiver_dob": "1990-01-01",
        "household_size": 2,
        "address_text": f"{n} Main St",
        "phone_last4": f"{1000 + (n % 9000):04d}",
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "first_name": f"Kid{n}",
        "dob": "2020-01-01",
        "gender": "X",
        "clothing_size": "youth M",
        "interest_tags": ["lego"],
    }
    defaults.update(overrides)
    return defaults


def create_wish_item_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "description": f"Wish item {n}",
        "category": "TOY",
        "estimated_price_cents": 3000,
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "email": f"donor{n}@example.com",
        "display_name": f"Donor {n}",
        "max_adoptions_per_season": 5,
        "thank_you_opt_in": False,
    }
    defaults.update(overrides)
    return defaults


def create_adoption_payload(campaign_id: str, donor_id: str, family_id: str,
                            expected_family_version: int, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "donor_id": donor_id,
        "family_id": family_id,
        "scope": "WHOLE_FAMILY",
        "expected_family_version": expected_family_version,
    }
    defaults.update(overrides)
    return defaults


def create_gift_payload(adoption_id: str, child_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "adoption_id": adoption_id,
        "child_id": child_id,
        "description": f"Gift {n}",
        "declared_value_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_event_payload(campaign_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "campaign_id": campaign_id,
        "site_name": f"Distribution Hall {n}",
        "start_at": EVENT_WINDOW["start_at"],
        "end_at": EVENT_WINDOW["end_at"],
        "capacity_slots": 100,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_slot_payload(event_id: str, family_id: str,
                                     expected_event_version: int,
                                     **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "family_id": family_id,
        "window_start": "2026-12-18T10:00:00Z",
        "window_end": "2026-12-18T11:00:00Z",
        "lane": "A",
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults
