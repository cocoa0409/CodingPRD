"""Payload factories — one per entity, input fields only."""
import itertools
import uuid

from .constants import (
    BOOKING_END,
    BOOKING_START,
    CONTEST_END,
    CONTEST_START,
    SLOT_END,
    SLOT_START,
)

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}-{uuid.uuid4().hex[:8]}"


def create_contest_event_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("CosCon"),
        "start_at": CONTEST_START,
        "end_at": CONTEST_END,
        "prize_budget_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_category_payload(contest_id, **overrides) -> dict:
    defaults = {
        "contest_id": contest_id,
        "name": _unique("Armor"),
        "skill_division": "MASTERS",
        "max_entries": 5,
        "tabulation_method": "WEIGHTED_MEAN",
        "prize_purse_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_contestant_payload(**overrides) -> dict:
    defaults = {
        "full_name": _unique("Cosplayer"),
        "email": f"{_unique('c')}@x.com",
        "birth_date": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_judge_payload(contest_id, category_ids, **overrides) -> dict:
    defaults = {
        "contest_id": contest_id,
        "display_name": _unique("Judge"),
        "category_ids": list(category_ids),
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(contestant_id, category_id, **overrides) -> dict:
    defaults = {
        "contestant_id": contestant_id,
        "category_id": category_id,
        "title": _unique("Entry"),
        "prop_declarations": [],
    }
    defaults.update(overrides)
    return defaults


def create_prejudging_slot_payload(category_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "panel_name": "P1",
        "start_at": SLOT_START,
        "end_at": SLOT_END,
    }
    defaults.update(overrides)
    return defaults


def create_scoresheet_payload(entry_id, **overrides) -> dict:
    defaults = {
        "entry_id": entry_id,
        "phase": "STAGE",
        "craftsmanship": 8,
        "accuracy": 8,
        "presentation": 8,
    }
    defaults.update(overrides)
    return defaults


def create_performance_slot_payload(entry_id, sequence_number, **overrides) -> dict:
    defaults = {
        "entry_id": entry_id,
        "sequence_number": sequence_number,
        "duration_seconds": 120,
    }
    defaults.update(overrides)
    return defaults


def create_prize_award_payload(category_id, rank, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "rank": rank,
    }
    defaults.update(overrides)
    return defaults


def create_green_room_booking_payload(contestant_id, contest_id, **overrides) -> dict:
    defaults = {
        "contestant_id": contestant_id,
        "contest_id": contest_id,
        "room_name": "NORTH",
        "start_at": BOOKING_START,
        "end_at": BOOKING_END,
    }
    defaults.update(overrides)
    return defaults
