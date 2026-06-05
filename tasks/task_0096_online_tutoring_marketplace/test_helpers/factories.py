"""Payload factories — one per create endpoint, input fields only.

Each factory returns a dict suitable for the matching ApiClient create method.
Tests override any field via keyword arguments. Defaults are chosen to satisfy
the PRD's input ranges so a factory call with no overrides always validates.
"""
import itertools

from .constants import (
    POLICY_REFUND_WINDOW_HOURS,
    POLICY_TIER_BREAKPOINTS_CENTS,
    POLICY_TIER_RATES_BPS,
    POLICY_TRIAL_COMMISSION_BPS,
    POLICY_TRIAL_MAX_BILLED_MINUTES,
)

# Monotonic counters so repeated factory calls within one test produce unique
# values for fields the PRD requires to be unique (subject code, emails).
_subject_seq = itertools.count(1)
_tutor_seq = itertools.count(1)
_parent_seq = itertools.count(1)


def create_subject_payload(**overrides) -> dict:
    n = next(_subject_seq)
    payload = {
        "code": f"SUBJ_{n}",
        "display_name": f"Subject {n}",
        "category": "STEM",
    }
    payload.update(overrides)
    return payload


def create_commission_policy_payload(**overrides) -> dict:
    payload = {
        "name": "Standard Policy",
        "tier_breakpoints_cents": list(POLICY_TIER_BREAKPOINTS_CENTS),
        "tier_rates_bps": list(POLICY_TIER_RATES_BPS),
        "trial_commission_bps": POLICY_TRIAL_COMMISSION_BPS,
        "trial_max_billed_minutes": POLICY_TRIAL_MAX_BILLED_MINUTES,
        "refund_window_hours": POLICY_REFUND_WINDOW_HOURS,
    }
    payload.update(overrides)
    return payload


def create_tutor_payload(**overrides) -> dict:
    n = next(_tutor_seq)
    payload = {
        "email": f"tutor{n}@example.com",
        "full_name": f"Tutor {n}",
        "base_hourly_rate_cents": 6000,
    }
    payload.update(overrides)
    return payload


def create_credential_payload(tutor_id, subject_id, **overrides) -> dict:
    payload = {
        "tutor_id": tutor_id,
        "subject_id": subject_id,
        "kind": "DEGREE",
        "document_ref": "doc-ref-1",
    }
    payload.update(overrides)
    return payload


def create_subject_tag_payload(tutor_id, subject_id, **overrides) -> dict:
    payload = {
        "tutor_id": tutor_id,
        "subject_id": subject_id,
    }
    payload.update(overrides)
    return payload


def create_parent_account_payload(**overrides) -> dict:
    n = next(_parent_seq)
    payload = {
        "email": f"parent{n}@example.com",
        "full_name": f"Parent {n}",
    }
    payload.update(overrides)
    return payload


def create_student_payload(**overrides) -> dict:
    payload = {
        "display_name": "Student One",
        "grade_level": 9,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(
    parent_account_id, student_id, tutor_id, subject_id, scheduled_start, **overrides
) -> dict:
    payload = {
        "parent_account_id": parent_account_id,
        "student_id": student_id,
        "tutor_id": tutor_id,
        "subject_id": subject_id,
        "scheduled_start": scheduled_start,
        "planned_minutes": 60,
    }
    payload.update(overrides)
    return payload


def create_refund_case_payload(session_id, claimed_amount_cents, **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload
