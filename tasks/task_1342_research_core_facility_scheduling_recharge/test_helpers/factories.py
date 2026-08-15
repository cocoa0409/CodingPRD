"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    CANONICAL_INSTRUMENT, CANONICAL_RATE_LINE,
    CANONICAL_BOOKING_START, CANONICAL_BOOKING_END, CANONICAL_GRANT,
)

_user_seq = {"n": 0}
_grant_seq = {"n": 0}


def create_user_payload(**overrides) -> dict:
    _user_seq["n"] += 1
    defaults = {
        "full_name": "Rita Rao",
        "email": f"r{_user_seq['n']}@uni.edu",
        "affiliation": "INTERNAL",
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(**overrides) -> dict:
    defaults = dict(CANONICAL_INSTRUMENT)
    defaults.update(overrides)
    return defaults


def create_training_record_payload(user_id, instrument_id, **overrides) -> dict:
    defaults = {"user_id": user_id, "instrument_id": instrument_id}
    defaults.update(overrides)
    return defaults


def create_grant_payload(pi_user_id, **overrides) -> dict:
    _grant_seq["n"] += 1
    defaults = {
        "grant_code": f"NIH-{_grant_seq['n']}",
        "pi_user_id": pi_user_id,
        "title": CANONICAL_GRANT["title"],
        "budget_total_cents": CANONICAL_GRANT["budget_total_cents"],
        "start_date": CANONICAL_GRANT["start_date"],
        "end_date": CANONICAL_GRANT["end_date"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_line_payload(instrument_id, **overrides) -> dict:
    defaults = dict(CANONICAL_RATE_LINE)
    defaults["instrument_id"] = instrument_id
    defaults.update(overrides)
    return defaults


def create_rate_set_payload(instrument_id, **overrides) -> dict:
    defaults = {
        "fiscal_year": 2026,
        "effective_from": "2026-08-01T00:00:00Z",
        "lines": [create_rate_line_payload(instrument_id)],
    }
    if "lines" in overrides:
        defaults["lines"] = overrides.pop("lines")
    defaults.update(overrides)
    return defaults


def create_booking_payload(user_id, instrument_id, **overrides) -> dict:
    defaults = {
        "user_id": user_id,
        "instrument_id": instrument_id,
        "start_at": CANONICAL_BOOKING_START,
        "end_at": CANONICAL_BOOKING_END,
        "priority": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_usage_log_payload(booking_id, actual_start_at, actual_end_at, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "actual_start_at": actual_start_at,
        "actual_end_at": actual_end_at,
    }
    defaults.update(overrides)
    return defaults


def create_recharge_batch_payload(**overrides) -> dict:
    defaults = {"period_year": 2026, "period_month": 9}
    defaults.update(overrides)
    return defaults


def create_subsidy_application_payload(user_id, **overrides) -> dict:
    defaults = {
        "user_id": user_id,
        "kind": "SUBSIDY",
        "requested_amount_cents": 5000,
        "justification": "pilot",
    }
    defaults.update(overrides)
    return defaults


def create_award_approval_payload(**overrides) -> dict:
    defaults = {
        "awarded_amount_cents": 5000,
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_until": "2026-12-01T00:00:00Z",
        "conveys_priority": False,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_contract_payload(instrument_id, **overrides) -> dict:
    defaults = {
        "instrument_id": instrument_id,
        "vendor": "Bruker Service",
        "sla_response_hours": 24,
        "coverage_start": "2026-01-01",
        "coverage_end": "2026-12-31",
        "annual_cost_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_downtime_event_payload(instrument_id, **overrides) -> dict:
    defaults = {
        "instrument_id": instrument_id,
        "kind": "UNSCHEDULED_FAILURE",
        "start_at": "2026-09-01T08:00:00Z",
        "end_at": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_publication_payload(user_id, instrument_ids, **overrides) -> dict:
    defaults = {
        "user_id": user_id,
        "title": "Paper",
        "journal": "Nature",
        "published_at": "2026-07-15",
        "acknowledges_core": True,
        "instrument_ids": list(instrument_ids),
    }
    defaults.update(overrides)
    return defaults


def create_fiscal_year_payload(**overrides) -> dict:
    defaults = {"fiscal_year": 2026}
    defaults.update(overrides)
    return defaults
