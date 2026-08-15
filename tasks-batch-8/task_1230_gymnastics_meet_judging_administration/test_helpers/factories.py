"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import (
    APPARATUS_ORDER, MEET_END, MEET_START, SESSION_END, SESSION_START,
)

# Counters keep human-supplied identifiers unique within a test run. The server
# database is empty at the start of every test, so cross-test reuse is safe.
_meet_counter = itertools.count(1)
_session_counter = itertools.count(1)
_squad_counter = itertools.count(1)
_gymnast_counter = itertools.count(1)
_coach_counter = itertools.count(1)
_judge_counter = itertools.count(1)
_ticket_counter = itertools.count(1)


def create_meet_payload(**overrides) -> dict:
    n = next(_meet_counter)
    defaults = {
        "meet_name": f"Test Meet {n}",
        "sanction_year": 2026,
        "sanction_number": f"USAG-2026-{n:04d}",
        "venue_name": "Arena One",
        "start_date": MEET_START,
        "end_date": MEET_END,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    n = next(_session_counter)
    defaults = {
        "session_label": f"Session {n}",
        "level_band": "L9",
        "scheduled_start": SESSION_START,
        "scheduled_end": SESSION_END,
        "apparatus_set": [
            {"apparatus": app, "flight_count": 1} for app in APPARATUS_ORDER
        ],
    }
    defaults.update(overrides)
    return defaults


def create_squad_payload(**overrides) -> dict:
    n = next(_squad_counter)
    defaults = {
        "squad_label": f"Squad {chr(ord('A') + (n - 1) % 26)}",
        "starting_apparatus": "VAULT",
    }
    defaults.update(overrides)
    return defaults


def create_gymnast_payload(**overrides) -> dict:
    n = next(_gymnast_counter)
    defaults = {
        "usag_member_number": f"A{n:07d}",
        "legal_name": f"Gymnast {n}",
        "date_of_birth": "2010-01-01T00:00:00Z",
        "competitive_level": "L9",
        "home_gym": "Metro",
    }
    defaults.update(overrides)
    return defaults


def create_athlete_entry_payload(gymnast_id, **overrides) -> dict:
    defaults = {"gymnast_id": gymnast_id}
    defaults.update(overrides)
    return defaults


def create_coach_payload(**overrides) -> dict:
    n = next(_coach_counter)
    defaults = {
        "usag_coach_number": f"C{n:07d}",
        "legal_name": f"Coach {n}",
        "affiliated_gym": "Metro",
        "background_check_expiry": "2027-01-01T00:00:00Z",
        "safety_cert_expiry": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_coach_pass_payload(coach_id, **overrides) -> dict:
    defaults = {"coach_id": coach_id}
    defaults.update(overrides)
    return defaults


def create_judge_payload(**overrides) -> dict:
    n = next(_judge_counter)
    defaults = {
        "usag_judge_number": f"J{n:07d}",
        "legal_name": f"Judge {n}",
        "rating": "BREVET",
        "affiliated_gym": "Neutral Club",
        "availability_start": "2026-05-02T00:00:00Z",
        "availability_end": "2026-05-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_judge_panel_payload(meet_id, apparatus, **overrides) -> dict:
    defaults = {"meet_id": meet_id, "apparatus": apparatus}
    defaults.update(overrides)
    return defaults


def create_score_payload(rotation_id, apparatus, difficulty_score, execution_score,
                         neutral_deduction=None, **overrides) -> dict:
    defaults = {
        "rotation_id": rotation_id,
        "apparatus": apparatus,
        "difficulty_score": difficulty_score,
        "execution_score": execution_score,
    }
    if neutral_deduction is not None:
        defaults["neutral_deduction"] = neutral_deduction
    defaults.update(overrides)
    return defaults


def create_inquiry_payload(coach_id, **overrides) -> dict:
    defaults = {"filed_by_coach_id": coach_id}
    defaults.update(overrides)
    return defaults


def create_resolve_payload(expected_inquiry_version, resolution, **overrides) -> dict:
    defaults = {
        "expected_inquiry_version": expected_inquiry_version,
        "resolution": resolution,
    }
    defaults.update(overrides)
    return defaults


def create_warmup_block_payload(squad_id, apparatus, block_start, block_end, **overrides) -> dict:
    defaults = {
        "squad_id": squad_id,
        "apparatus": apparatus,
        "block_start": block_start,
        "block_end": block_end,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    n = next(_ticket_counter)
    defaults = {
        "holder_name": f"Holder {n}",
        "holder_email": f"holder{n}@example.com",
        "ticket_class": "GENERAL_ADMISSION",
        "price_cents": 2500,
    }
    defaults.update(overrides)
    return defaults
