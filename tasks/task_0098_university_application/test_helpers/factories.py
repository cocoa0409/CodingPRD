"""Payload factories — one per endpoint accepting input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body. Tests pass overrides for the values they want to control.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.9: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_offset(*, days: int = 0, hours: int = 0,
               minutes: int = 0, seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


def iso_date_offset(*, days: int = 0,
                    base: Optional[date] = None) -> str:
    base = base or date.today()
    return (base + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Random suffix for uniqueness.
# ---------------------------------------------------------------------------
_ALPHANUM = string.ascii_lowercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


# ===========================================================================
# Applicant (PRD §3.1)
# ===========================================================================
def create_applicant_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /applicants payload.

    PRD §3.1 required fields: full_name (1-200 chars), email (RFC5322,
    unique), date_of_birth (YYYY-MM-DD, at least 14y before now),
    high_school_gpa (0.00-4.00), household_income_cents (>= 0).
    Optional: fafsa_efc_cents, css_profile_efc_cents.
    """
    suffix = random_suffix(8)
    # Use a DOB that is 18 years before today — well past the 14-year
    # minimum, but flexible to clock-advance scenarios.
    dob = (date.today() - timedelta(days=18 * 365)).isoformat()
    payload: Dict[str, Any] = {
        "full_name": f"Applicant {suffix}",
        "email": f"applicant.{suffix}@example.com",
        "date_of_birth": dob,
        "high_school_gpa": 3.80,
        "household_income_cents": 7_500_000,
    }
    payload.update(overrides)
    return payload


def patch_applicant_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /applicants/{id} payload — gpa, income, EFCs, optional version."""
    return dict(overrides)


# ===========================================================================
# University (PRD §3.2)
# ===========================================================================
def create_university_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /universities payload.

    PRD §3.2 required: name (unique), yield_target_count (>= 1),
    regular_decision_deadline (ISO datetime), early_decision_deadline.
    Optional: rolling_admission_enabled (defaults false).
    """
    suffix = random_suffix(8)
    # Deadlines well in the future so submissions don't trip them.
    payload: Dict[str, Any] = {
        "name": f"Northstar University {suffix}",
        "yield_target_count": 100,
        "regular_decision_deadline": iso_offset(days=180),
        "early_decision_deadline": iso_offset(days=90),
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Program (PRD §3.2)
# ===========================================================================
def create_program_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /universities/{id}/programs payload.

    PRD §3.2 required: name (unique within university), capacity (>= 1).
    """
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "name": f"Computer Science {suffix}",
        "capacity": 10,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Application (PRD §3.3)
# ===========================================================================
def create_application_payload(applicant_id: str,
                               program_id: str,
                               **overrides: Any) -> Dict[str, Any]:
    """POST /applications payload.

    PRD §3.3 required: applicant_id, program_id, round (one of
    EARLY_DECISION, REGULAR_DECISION, ROLLING). Optional:
    required_recommendation_count (defaults to 2; must be 2 or 3).
    """
    payload: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "program_id": program_id,
        "round": "REGULAR_DECISION",
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Essay (PRD §3.4)
# ===========================================================================
def attach_essay_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /applications/{id}/essays payload.

    PRD §3.4 required: prompt_code, body (length 250..6500 chars).
    """
    payload: Dict[str, Any] = {
        "prompt_code": "ESSAY-DEFAULT",
        "body": "x" * 500,
    }
    payload.update(overrides)
    return payload


def patch_essay_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /essays/{id} payload — body, prompt_code, optional version."""
    return dict(overrides)


# ===========================================================================
# Recommendation (PRD §3.5)
# ===========================================================================
def create_recommendation_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /applications/{id}/recommendations payload.

    PRD §3.5 required: recommender_email (the email-string that the
    Recommender will later authenticate as via X-User-ID).
    """
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "recommender_email": f"recommender.{suffix}@example.com",
    }
    payload.update(overrides)
    return payload


def reassign_recommendation_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /recommendations/{id}/reassign payload — recommender_email."""
    suffix = random_suffix(6)
    payload: Dict[str, Any] = {
        "recommender_email": f"new-recommender.{suffix}@example.com",
    }
    payload.update(overrides)
    return payload


def submit_letter_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /recommendations/{id}/submit-letter payload.

    PRD §3.5 required: letter_body. PRD §3.5: weak letter is one
    with letter_word_count < 200; the strong default here is 220 words.
    """
    payload: Dict[str, Any] = {
        "letter_body": "word " * 220,  # 220 whitespace-tokens
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Financial aid (PRD §3.8)
# ===========================================================================
def create_financial_aid_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /applications/{id}/financial-aid payload.

    PRD §3.8 required: aid_method (FEDERAL_METHODOLOGY or
    INSTITUTIONAL_METHODOLOGY), cost_of_attendance_cents (>= 0).
    """
    payload: Dict[str, Any] = {
        "aid_method": "FEDERAL_METHODOLOGY",
        "cost_of_attendance_cents": 8_000_000,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Decision (PRD §3.7)
# ===========================================================================
def decide_application_payload(decision: str = "ADMIT") -> Dict[str, Any]:
    """POST /applications/{id}/decide payload — decision in {ADMIT, REJECT, WAITLIST}."""
    return {"decision": decision}


# ===========================================================================
# Clock (PRD §3.11)
# ===========================================================================
def advance_clock_payload(seconds: int = 1) -> Dict[str, Any]:
    return {"seconds": seconds}


# ===========================================================================
# Body crafting helpers for essay scoring (PRD §3.4)
# ===========================================================================
def craft_essay_body(*,
                     university_name: str = "Northstar",
                     program_name: str = "Computer Science",
                     uni_mentions: int = 2,
                     prog_mentions: int = 2,
                     token_count: int = 500,
                     padding_word: str = "writing") -> str:
    """Produce a body with exactly `token_count` whitespace-tokens, of
    which `uni_mentions` are the university name and `prog_mentions`
    are the program name. Used to drive the customization-score formula
    in PRD §3.4 to a known value.
    """
    if token_count < uni_mentions + prog_mentions:
        raise ValueError("token_count too small for requested mentions")
    tokens = []
    for _ in range(uni_mentions):
        tokens.append(university_name)
    for _ in range(prog_mentions):
        # If program name has spaces, split into tokens too — the PRD's
        # whitespace tokenizer counts each whitespace-separated token,
        # but the case-insensitive whole-word match is on the multi-word
        # name. We append it as a contiguous run so the substring matches.
        tokens.extend(program_name.split())
    padding_needed = token_count - len(tokens)
    if padding_needed < 0:
        raise ValueError("token_count too small")
    tokens.extend([padding_word] * padding_needed)
    return " ".join(tokens)


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "iso_date_offset",
    "random_suffix",
    "create_applicant_payload",
    "patch_applicant_payload",
    "create_university_payload",
    "create_program_payload",
    "create_application_payload",
    "attach_essay_payload",
    "patch_essay_payload",
    "create_recommendation_payload",
    "reassign_recommendation_payload",
    "submit_letter_payload",
    "create_financial_aid_payload",
    "decide_application_payload",
    "advance_clock_payload",
    "craft_essay_body",
]
