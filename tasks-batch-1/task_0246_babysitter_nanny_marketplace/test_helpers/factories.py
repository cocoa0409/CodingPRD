"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the source:input fields the corresponding POST
endpoint accepts, with sensible defaults overridable via **overrides.
"""


def create_family_payload(**overrides) -> dict:
    """Required: display_name, email, num_children. Optional: required_tier,
    wallet_balance_cents."""
    defaults = {
        "display_name": "Test Family",
        "email": "family@example.com",
        "num_children": 1,
    }
    defaults.update(overrides)
    return defaults


def create_caregiver_payload(**overrides) -> dict:
    """Required: full_name, email, hourly_rate_floor_cents."""
    defaults = {
        "full_name": "Test Caregiver",
        "email": "caregiver@example.com",
        "hourly_rate_floor_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_background_check_payload(caregiver_id, requested_tier="BASIC", **overrides) -> dict:
    """Required: caregiver_id, requested_tier."""
    defaults = {
        "caregiver_id": caregiver_id,
        "requested_tier": requested_tier,
    }
    defaults.update(overrides)
    return defaults


def create_job_posting_payload(family_id, **overrides) -> dict:
    """Required: family_id, title, care_type, family_pay_rate_cents.
    Optional: required_tier."""
    defaults = {
        "family_id": family_id,
        "title": "Test Posting",
        "care_type": "ONE_TIME",
        "family_pay_rate_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(job_posting_id, family_id, caregiver_id, **overrides) -> dict:
    """Required: job_posting_id, family_id, caregiver_id, scheduled_start,
    scheduled_end, kind."""
    defaults = {
        "job_posting_id": job_posting_id,
        "family_id": family_id,
        "caregiver_id": caregiver_id,
        "scheduled_start": "2026-03-10T15:00:00Z",
        "scheduled_end": "2026-03-10T16:00:00Z",
        "kind": "VIDEO",
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(family_id, caregiver_id, job_posting_id, **overrides) -> dict:
    """Required: family_id, caregiver_id, job_posting_id, agreed_rate_cents,
    scheduled_start, scheduled_end. Optional: recurrence_count, is_holiday."""
    defaults = {
        "family_id": family_id,
        "caregiver_id": caregiver_id,
        "job_posting_id": job_posting_id,
        "agreed_rate_cents": 2000,
        "scheduled_start": "2026-03-20T08:00:00Z",
        "scheduled_end": "2026-03-20T12:00:00Z",
        "recurrence_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_backup_request_payload(family_id, **overrides) -> dict:
    """Required: family_id, needed_start, needed_end, required_tier, max_rate_cents."""
    defaults = {
        "family_id": family_id,
        "needed_start": "2026-03-05T08:00:00Z",
        "needed_end": "2026-03-05T12:00:00Z",
        "required_tier": "BASIC",
        "max_rate_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(caregiver_id, family_id, session_ids, **overrides) -> dict:
    """Required: caregiver_id, family_id, session_ids."""
    defaults = {
        "caregiver_id": caregiver_id,
        "family_id": family_id,
        "session_ids": session_ids,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(booking_id, family_id, caregiver_id, rating_value=5, **overrides) -> dict:
    """Required: booking_id, family_id, caregiver_id, rating_value. Optional: comment."""
    defaults = {
        "booking_id": booking_id,
        "family_id": family_id,
        "caregiver_id": caregiver_id,
        "rating_value": rating_value,
    }
    defaults.update(overrides)
    return defaults


def create_tax_statement_payload(family_id, caregiver_id, tax_year=2026, **overrides) -> dict:
    """Required: family_id, caregiver_id, tax_year."""
    defaults = {
        "family_id": family_id,
        "caregiver_id": caregiver_id,
        "tax_year": tax_year,
    }
    defaults.update(overrides)
    return defaults
