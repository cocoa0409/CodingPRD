"""Payload factories — one per creatable resource, input fields only."""

from .constants import DEFAULT_TERM_END, DEFAULT_TERM_START


def create_artist_payload(**overrides) -> dict:
    defaults = {
        "stage_name": "Test Act",
        "legal_name": "Test Act LLC",
        "primary_genre": "pop",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(artist_id, expected_artist_version, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "term_start_date": DEFAULT_TERM_START,
        "term_end_date": DEFAULT_TERM_END,
        "expected_artist_version": expected_artist_version,
    }
    defaults.update(overrides)
    return defaults


def patch_agreement_payload(expected_agreement_version, **overrides) -> dict:
    defaults = {"expected_agreement_version": expected_agreement_version}
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(agreement_id, income_type="TOURING", **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "income_type": income_type,
        "in_term_rate_bps": 1500,
        "sunset_rate_bps": 750,
        "sunset_months": 12,
        "effective_from_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_income_event_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "income_type": "TOURING",
        "gross_amount_cents": 100000,
        "recognition_date": "2026-03-10",
        "source_name": "Test Promoter",
    }
    defaults.update(overrides)
    return defaults


def settle_payload(received_date="2026-03-12", received_amount_cents=100000) -> dict:
    return {"received_date": received_date, "received_amount_cents": received_amount_cents}


def create_advance_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "principal_cents": 50000,
        "issued_date": "2026-01-05",
    }
    defaults.update(overrides)
    return defaults


def create_expense_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "category": "OTHER",
        "amount_cents": 5000,
        "incurred_date": "2026-07-01",
        "description": "Test expense",
    }
    defaults.update(overrides)
    return defaults


def create_opportunity_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "income_type": "TOURING",
        "counterparty_name": "FestCo",
        "proposed_value_cents": 5000000,
        "offer_expiry_date": "2026-12-31",
        "proposed_window_start": "2026-10-01T00:00:00Z",
        "proposed_window_end": "2026-10-02T00:00:00Z",
        "fit_score": 60,
    }
    defaults.update(overrides)
    return defaults


def counter_offer_payload(new_value_cents, expected_opportunity_version) -> dict:
    return {
        "new_value_cents": new_value_cents,
        "expected_opportunity_version": expected_opportunity_version,
    }


def create_engagement_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "income_type": "TOURING",
        "counterparty_name": "Venue",
        "start_datetime": "2026-09-10T18:00:00Z",
        "end_datetime": "2026-09-10T23:00:00Z",
        "guarantee_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_option_payload(artist_id, agreement_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "agreement_id": agreement_id,
        "option_type": "TOUR_LEG",
        "income_type": "TOURING",
        "exercise_window_start": "2026-07-01T00:00:00Z",
        "exercise_window_end": "2026-09-01T00:00:00Z",
        "engagement_start_datetime": "2027-03-01T20:00:00Z",
        "engagement_end_datetime": "2027-03-01T23:00:00Z",
        "exercise_value_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_team_member_payload(artist_id, member_role="AGENT", **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "member_role": member_role,
        "display_name": "Team Member",
        "window_start_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def generate_statement_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "period_start_date": "2026-01-01",
        "period_end_date": "2026-03-31",
        "basis": "ACCRUAL",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(artist_id, statement_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "statement_id": statement_id,
        "reason": "OTHER",
        "claimed_amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(outcome="UPHELD", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_audit_payload(artist_id, scope_statement_id) -> dict:
    return {"artist_id": artist_id, "scope_statement_id": scope_statement_id}


def issue_findings_payload(findings_underpayment_cents=0, audit_cost_cents=0) -> dict:
    return {
        "findings_underpayment_cents": findings_underpayment_cents,
        "audit_cost_cents": audit_cost_cents,
    }
