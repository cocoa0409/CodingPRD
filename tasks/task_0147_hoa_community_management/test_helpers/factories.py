"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for
the request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared
input fields are produced; computed/system fields are intentionally
omitted so the implementation cannot accidentally accept them.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_QUORUM_PCT,
    MIN_LEVY_CENTS,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 ISO 8601 UTC with three fractional digits
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


def iso_instant_utc(
    year: int, month: int, day: int,
    hour: int = 12, minute: int = 0, second: int = 0,
    millis: int = 0,
) -> str:
    micros = millis * 1000
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            micros, tzinfo=timezone.utc))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_seconds(dt: datetime, seconds: int) -> datetime:
    return dt + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_email() -> str:
    return f"member_{random_suffix(6).lower()}@example.com"


def random_address(n: int = 0) -> str:
    return f"{random.randint(100, 9999)} {random_suffix(6)} Way #{n}"


# ---------------------------------------------------------------------------
# Member — PRD §3.1
# ---------------------------------------------------------------------------
def create_member_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: 'submitting their full_name and email — the email must
    be unique within the HOA.'"""
    defaults: Dict[str, Any] = {
        "full_name": f"{TEST_DEFAULTS['member_full_name']} {random_suffix(4)}",
        "email": random_email(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Unit — PRD §3.1
# ---------------------------------------------------------------------------
def create_unit_payload(
    owner_member_id: str,
    share_factor: float,
    address: Optional[str] = None,
    mortgage_holder: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: address, owner_member_id, share_factor; optional
    mortgage_holder (null when unencumbered)."""
    payload: Dict[str, Any] = {
        "address": address or random_address(),
        "owner_member_id": owner_member_id,
        "share_factor": share_factor,
    }
    if mortgage_holder is not None:
        payload["mortgage_holder"] = mortgage_holder
    payload.update(overrides)
    return payload


def patch_unit_payload(
    version: int,
    share_factor: Optional[float] = None,
    mortgage_holder: Optional[Any] = "__UNSET__",
    **overrides,
) -> Dict[str, Any]:
    """PRD §4: 'PATCH /hoa/units/{id}' accepts share_factor?,
    mortgage_holder?, version. PRD §2.6: 'optional version field'."""
    payload: Dict[str, Any] = {"version": version}
    if share_factor is not None:
        payload["share_factor"] = share_factor
    if mortgage_holder != "__UNSET__":
        payload["mortgage_holder"] = mortgage_holder
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Assessment cycle — PRD §3.2
# ---------------------------------------------------------------------------
def create_assessment_cycle_payload(
    cycle_type: str = "REGULAR",
    period_start: Optional[str] = None,
    due_date: Optional[str] = None,
    total_levy_cents: int = TEST_DEFAULTS["regular_levy_cents"],
    approval_resolution_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.2: cycle_type (REGULAR|SPECIAL), period_start, due_date,
    total_levy_cents, optional approval_resolution_id."""
    payload: Dict[str, Any] = {
        "cycle_type": cycle_type,
        "period_start": period_start or iso_now(),
        "due_date": due_date or iso_utc(utcnow() + timedelta(days=30)),
        "total_levy_cents": total_levy_cents,
    }
    if approval_resolution_id is not None:
        payload["approval_resolution_id"] = approval_resolution_id
    payload.update(overrides)
    return payload


def version_payload(version: int, **overrides) -> Dict[str, Any]:
    """For mutation endpoints that accept only {version} — issue,
    close, void, begin-review, cure, certify, write-off."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payment — PRD §3.3
# ---------------------------------------------------------------------------
def create_payment_payload(
    member_id: str,
    amount_cents: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3: 'A Member posts a Payment carrying their member_id
    (which MUST equal X-User-ID) and an amount_cents strictly greater
    than zero.'"""
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ACC request — PRD §3.4
# ---------------------------------------------------------------------------
def create_acc_request_payload(
    unit_id: str,
    category: str = "LANDSCAPING",
    description: str = TEST_DEFAULTS["acc_description"],
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.4: 'A Member initiates the request by submitting unit_id,
    category, and description.'"""
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "category": category,
        "description": description,
    }
    payload.update(overrides)
    return payload


def vote_payload(vote: str, **overrides) -> Dict[str, Any]:
    """PRD §3.4 / §3.8: ACCVote and BoardResolution vote both take
    {vote: YES|NO}."""
    payload: Dict[str, Any] = {"vote": vote}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Violation — PRD §3.5
# ---------------------------------------------------------------------------
def create_violation_payload(
    unit_id: str,
    description: str = TEST_DEFAULTS["violation_description"],
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: 'opened by a SecretaryRole or PresidentRole against a
    particular unit_id, with a description of the infraction.'"""
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "description": description,
    }
    payload.update(overrides)
    return payload


def waive_violation_payload(
    resolution_id: str,
    version: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5 / §4: waive accepts {resolution_id, version}."""
    payload: Dict[str, Any] = {
        "resolution_id": resolution_id,
        "version": version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Board resolutions — PRD §3.8
# ---------------------------------------------------------------------------
def create_board_resolution_payload(
    subject: str,
    target_id: str,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.8: 'submitting a subject and a target_id.'"""
    payload: Dict[str, Any] = {
        "subject": subject,
        "target_id": target_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Elections — PRD §3.7
# ---------------------------------------------------------------------------
def create_election_payload(
    seat: str,
    nomination_open_at: str,
    voting_open_at: str,
    voting_close_at: str,
    quorum_pct: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.7: 'specifying which seat is up ... together with three
    timestamps and an optional quorum_pct.'"""
    payload: Dict[str, Any] = {
        "seat": seat,
        "nomination_open_at": nomination_open_at,
        "voting_open_at": voting_open_at,
        "voting_close_at": voting_close_at,
    }
    if quorum_pct is not None:
        payload["quorum_pct"] = quorum_pct
    payload.update(overrides)
    return payload


def create_candidate_payload(member_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.7: 'submitting their own member_id (which MUST equal
    X-User-ID).'"""
    payload: Dict[str, Any] = {"member_id": member_id}
    payload.update(overrides)
    return payload


def create_ballot_payload(
    voter_member_id: str,
    candidate_id: str,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.7: 'carrying the election's election_id, the caller's
    voter_member_id (which MUST equal X-User-ID), and the candidate_id
    of their choice.' election_id is in the URL path."""
    payload: Dict[str, Any] = {
        "voter_member_id": voter_member_id,
        "candidate_id": candidate_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Liens — PRD §3.6
# ---------------------------------------------------------------------------
def create_lien_payload(unit_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.6: 'creates a lien notice by submitting the unit_id of
    the unit to be encumbered.'"""
    payload: Dict[str, Any] = {"unit_id": unit_id}
    payload.update(overrides)
    return payload


def lien_action_payload(
    resolution_id: str,
    version: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §4: record and release both accept {resolution_id, version}."""
    payload: Dict[str, Any] = {
        "resolution_id": resolution_id,
        "version": version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reserve studies — PRD §3.9
# ---------------------------------------------------------------------------
def reserve_component(
    component_name: str,
    replacement_cost_cents: int,
    useful_life_years: int,
    remaining_life_years: int,
) -> Dict[str, Any]:
    return {
        "component_name": component_name,
        "replacement_cost_cents": replacement_cost_cents,
        "useful_life_years": useful_life_years,
        "remaining_life_years": remaining_life_years,
    }


def create_reserve_study_payload(
    study_year: int = TEST_DEFAULTS["study_year"],
    components: Optional[List[Dict[str, Any]]] = None,
    current_reserve_balance_cents: int = 0,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.9: 'a study_year calendar-year integer, a non-empty
    components array ..., and the HOA's current_reserve_balance_cents.'"""
    payload: Dict[str, Any] = {
        "study_year": study_year,
        "components": components if components is not None else [
            reserve_component("Roof", 100_000, 20, 10),
        ],
        "current_reserve_balance_cents": current_reserve_balance_cents,
    }
    payload.update(overrides)
    return payload


def adopt_reserve_study_payload(
    resolution_id: str,
    version: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §4: adopt accepts {resolution_id, version}."""
    payload: Dict[str, Any] = {
        "resolution_id": resolution_id,
        "version": version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock — PRD §3.10
# ---------------------------------------------------------------------------
def clock_advance_payload(target_timestamp: str, **overrides) -> Dict[str, Any]:
    """PRD §3.10: 'carries a target_timestamp ISO 8601 instant'."""
    payload: Dict[str, Any] = {"target_timestamp": target_timestamp}
    payload.update(overrides)
    return payload


__all__ = [
    # time helpers
    "iso_utc", "utcnow", "iso_now", "iso_instant_utc",
    "parse_iso", "add_days", "add_seconds",
    # random
    "random_suffix", "random_email", "random_address",
    # payloads
    "create_member_payload",
    "create_unit_payload", "patch_unit_payload",
    "create_assessment_cycle_payload",
    "version_payload",
    "create_payment_payload",
    "create_acc_request_payload", "vote_payload",
    "create_violation_payload", "waive_violation_payload",
    "create_board_resolution_payload",
    "create_election_payload", "create_candidate_payload",
    "create_ballot_payload",
    "create_lien_payload", "lien_action_payload",
    "reserve_component", "create_reserve_study_payload",
    "adopt_reserve_study_payload",
    "clock_advance_payload",
]
