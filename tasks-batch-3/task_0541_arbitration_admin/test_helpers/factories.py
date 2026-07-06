"""Payload factories — one per entity, input fields only."""


def create_case_payload(**overrides) -> dict:
    defaults = {
        "case_type": "ARBITRATION",
        "title": "Test Case",
        "claim_amount_cents": 500_000,
        "panel_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_party_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "role": "CLAIMANT",
        "display_name": "Test Party",
        "share_pct": 50,
    }
    defaults.update(overrides)
    return defaults


def create_neutral_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Neutral",
        "neutral_type": "ARBITRATOR",
        "hourly_rate_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def add_candidate_payload(**overrides) -> dict:
    defaults = {
        "neutral_id": None,
        "expected_case_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_ranking_payload(**overrides) -> dict:
    defaults = {
        "candidate_id": None,
        "party_id": None,
        "action": "RANK",
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(**overrides) -> dict:
    defaults = {
        "hearing_type": "EVIDENTIARY",
        "start_at": "2026-06-20T09:00:00Z",
        "end_at": "2026-06-20T11:00:00Z",
        "location": "Room A",
    }
    defaults.update(overrides)
    return defaults


def create_exchange_payload(**overrides) -> dict:
    defaults = {
        "exchange_type": "EXHIBITS",
        "due_at": "2026-06-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_fee_charge_payload(**overrides) -> dict:
    defaults = {
        "neutral_id": None,
        "hours": 1,
        "expected_case_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(**overrides) -> dict:
    defaults = {
        "award_type": "MONETARY",
        "award_amount_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {
        "award_id": None,
        "ground": "PROCEDURAL",
    }
    defaults.update(overrides)
    return defaults
