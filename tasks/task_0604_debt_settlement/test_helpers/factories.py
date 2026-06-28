"""Payload factories — one per resource, input fields only."""


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Debtor",
        "email": "debtor@example.com",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(client_id: str, **overrides) -> dict:
    # Only client_id and monthly_deposit_amount are required; the rest are optional
    # with server-side defaults (target 0.50, deposit_day 1, reserve_floor 0).
    defaults = {
        "client_id": client_id,
        "monthly_deposit_amount": 600,
    }
    defaults.update(overrides)
    return defaults


def create_debt_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "creditor_name": "Test Creditor",
        "account_number": "ACC-1",
        "original_balance": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(program_id: str, scheduled_for: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "scheduled_for": scheduled_for,
        "amount": 600,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(program_id: str, debt_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "debt_id": debt_id,
        "offer_pct": 0.40,
        "due_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def accept_offer_payload(expected_program_version: int, **overrides) -> dict:
    defaults = {"expected_program_version": expected_program_version}
    defaults.update(overrides)
    return defaults


def create_settlement_payload(program_id: str, offer_id: str, **overrides) -> dict:
    defaults = {"program_id": program_id, "offer_id": offer_id}
    defaults.update(overrides)
    return defaults


def create_lawsuit_payload(program_id: str, debt_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "debt_id": debt_id,
        "court_reference": "CASE-1",
        "filed_at": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
