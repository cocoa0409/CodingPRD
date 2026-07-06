"""Payload factories — one per creatable entity, input fields only."""


def create_committee_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Committee",
        "committee_type": "CANDIDATE",
        "election_cycle": "2026",
        "jurisdiction": "CA",
        "treasurer_name": "T",
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(**overrides) -> dict:
    defaults = {
        "contributor_ref": "r1",
        "contributor_name": "Ann",
        "contributor_type": "INDIVIDUAL",
        "amount_cents": 5000,
        "contribution_date": "2026-02-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_expenditure_payload(**overrides) -> dict:
    defaults = {
        "payee_name": "Vendor",
        "amount_cents": 10000,
        "expenditure_date": "2026-02-20T00:00:00Z",
        "purpose": "ads",
    }
    defaults.update(overrides)
    return defaults


def create_reporting_period_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction": "CA",
        "election_cycle": "2026",
        "period_label": "Q1",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-04-01T00:00:00Z",
        "filing_deadline": "2026-04-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(period_id, expected_committee_version, **overrides) -> dict:
    defaults = {
        "period_id": period_id,
        "expected_committee_version": expected_committee_version,
    }
    defaults.update(overrides)
    return defaults


def create_registrant_payload(**overrides) -> dict:
    defaults = {
        "name": "Lobby LLC",
        "registrant_contact": "c",
        "jurisdiction": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {"client_name": "ClientCo"}
    defaults.update(overrides)
    return defaults


def create_lobbying_period_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction": "CA",
        "period_label": "LP1",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-03-31T00:00:00Z",
        "filing_deadline": "2026-04-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_activity_payload(client_id, period_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "period_id": period_id,
        "lobbyist_name": "L",
        "subject": "S",
        "amount_cents": 5000,
        "activity_date": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
