"""Payload factories — one per entity, input fields only."""

_union_seq = {"n": 0}


def next_union_code() -> str:
    _union_seq["n"] += 1
    return f"U-{_union_seq['n']:06d}"


def create_union_payload(**overrides) -> dict:
    defaults = {"name": "Test Union", "union_code": next_union_code()}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "title": "CBA",
        "effective_date": "2026-06-01T00:00:00Z",
        "expiration_date": "2029-05-31T00:00:00Z",
        "headcount_baseline": 100,
        "fte_projected": 120,
        "avg_loaded_wage_cents": 5000,
        "costing_envelope_cents": 1_000_000_000_000,
        "deadline_mode": "BUSINESS",
    }
    defaults.update(overrides)
    return defaults


def create_clause_payload(**overrides) -> dict:
    defaults = {
        "article_ref": "12.1",
        "title": "Clause title",
        "body_text": "Clause body",
        "is_economic": False,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {
        "mediator_id": "med-1",
        "lead_negotiator_id": "ln-1",
        "location": "Room 1",
        "start_at": "2026-06-01T10:00:00Z",
        "end_at": "2026-06-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(**overrides) -> dict:
    defaults = {
        "side": "EMPLOYER",
        "title": "Proposal",
        "proposal_type": "ECONOMIC",
    }
    defaults.update(overrides)
    return defaults


def create_costing_scenario_payload(**overrides) -> dict:
    defaults = {
        "name": "scenario",
        "scenario_mode": "FINAL",
        "term_years": 3,
    }
    defaults.update(overrides)
    return defaults


def create_ratification_vote_payload(**overrides) -> dict:
    defaults = {
        "eligible_voter_count": 10,
        "ballot_close_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_side_letter_payload(**overrides) -> dict:
    defaults = {
        "letter_type": "SIDE_LETTER",
        "title": "Side letter",
        "effective_start": "2026-01-01T00:00:00Z",
        "effective_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_past_practice_payload(**overrides) -> dict:
    defaults = {
        "title": "Practice",
        "description": "Documented practice",
        "first_observed_date": "2023-05-01T00:00:00Z",
        "last_observed_date": "2025-05-01T00:00:00Z",
        "occurrence_count": 8,
    }
    defaults.update(overrides)
    return defaults


def create_information_request_payload(**overrides) -> dict:
    defaults = {
        "subject": "Records request",
        "received_at": "2026-05-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_expiration_task_payload(**overrides) -> dict:
    defaults = {
        "title": "Task",
        "task_type": "NOTICE_DEADLINE",
        "due_offset_days": -60,
        "assignee_user_id": "mgr-1",
    }
    defaults.update(overrides)
    return defaults
