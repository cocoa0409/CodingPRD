"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
import itertools

from .constants import EDITION_CALENDAR

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_edition_payload(**overrides) -> dict:
    defaults = {
        "year": 2027,
        "host_country_code": "US",
        "rsvp_window_days": 7,
        "hotel_nights_pool": 10,
        "travel_budget_cents": 400000,
        "prize_pool_cents": 5000000,
    }
    defaults.update(EDITION_CALENDAR)
    defaults.update(overrides)
    return defaults


def create_category_config_payload(edition_id, **overrides) -> dict:
    defaults = {
        "edition_id": edition_id,
        "category": "SHORT_FILM",
        "min_runtime_minutes": 1,
        "max_runtime_minutes": 40,
        "premiere_requirement": "NONE",
        "completion_cutoff": "2025-01-01",
        "early_fee_cents": 4000,
        "regular_fee_cents": 5500,
        "late_fee_cents": 7000,
        "screener_count_required": 2,
    }
    defaults.update(overrides)
    return defaults


def create_submitter_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "legal_name": f"Submitter {n}",
        "email": f"submitter{n}@example.com",
        "country_of_residence": "US",
    }
    defaults.update(overrides)
    return defaults


def create_programmer_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "display_name": f"Programmer {n}",
        "email": f"programmer{n}@example.com",
        "seniority": "STAFF",
        "categories_covered": ["SHORT_FILM"],
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(edition_id, **overrides) -> dict:
    defaults = {
        "edition_id": edition_id,
        "category": "SHORT_FILM",
        "title": _uniq("Film"),
        "runtime_minutes": 20,
        "completion_date": "2025-06-01",
        "premiere_status": "WORLD",
        "production_company": "A Co",
        "format": "DCP_2K",
    }
    defaults.update(overrides)
    return defaults


def create_score_payload(**overrides) -> dict:
    defaults = {
        "originality": 8,
        "craft": 8,
        "story": 8,
        "overall": 8,
        "recommendation": "ADVOCATE",
    }
    defaults.update(overrides)
    return defaults


def create_slate_payload(edition_id, **overrides) -> dict:
    defaults = {
        "edition_id": edition_id,
        "section": "SHORTS",
        "capacity_slots": 1,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(edition_id, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "edition_id": edition_id,
        "name": f"Venue {n}",
        "seat_capacity": 500,
        "formats_supported": ["DCP_2K", "DCP_4K"],
        "turnover_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(venue_id, expected_venue_version, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "slot_type": "PREMIERE",
        "start_at": "2027-01-22T17:00:00Z",
        "end_at": "2027-01-22T18:00:00Z",
        "expected_venue_version": expected_venue_version,
    }
    defaults.update(overrides)
    return defaults


def submit_travel_payload(**overrides) -> dict:
    defaults = {
        "delegate_count": 1,
        "origin_country_code": "US",
        "hotel_nights_requested": 2,
    }
    defaults.update(overrides)
    return defaults


def issue_agreement_payload(**overrides) -> dict:
    defaults = {
        "rights_scope": "FESTIVAL_WORLD",
        "licensed_screening_count": 3,
        "exclusivity_until": "2027-03-01T00:00:00Z",
        "revenue_share_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_juror_payload(edition_id, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "edition_id": edition_id,
        "display_name": f"Juror {n}",
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(edition_id, assigned_juror_ids, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "edition_id": edition_id,
        "name": f"Award {n}",
        "section": "SHORTS",
        "prize_cents": 2500000,
        "assigned_juror_ids": assigned_juror_ids,
    }
    defaults.update(overrides)
    return defaults
