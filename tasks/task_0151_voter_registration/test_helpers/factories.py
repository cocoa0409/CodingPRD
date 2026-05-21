"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


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


def iso_instant(year: int, month: int, day: int,
                hour: int = 0, minute: int = 0, second: int = 0,
                millis: int = 0) -> str:
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


def add_millis(dt: datetime, millis: int) -> datetime:
    return dt + timedelta(milliseconds=millis)


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_street_address(pattern_token: str = "Main") -> str:
    return f"{random.randint(100, 9999)} {pattern_token} Street"


def random_serial_no(prefix: str = "SN") -> str:
    return f"{prefix}-{random_suffix(8)}"


# ---------------------------------------------------------------------------
# Clock — PRD §2.5
# ---------------------------------------------------------------------------
def clock_advance_payload(to_instant: str, **overrides) -> Dict[str, Any]:
    """PRD §2.5: 'The clock-advance request supplies a single to_instant
    field carrying the target ISO 8601 instant the clock should jump
    to.'"""
    payload: Dict[str, Any] = {"to_instant": to_instant}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Election — PRD §3.1
# ---------------------------------------------------------------------------
def create_election_payload(
    name: str = "Test General Election",
    election_date: str = "2026-11-03T00:00:00.000Z",
    registration_deadline: str = "2026-10-04T00:00:00.000Z",
    absentee_request_deadline: str = "2026-10-27T00:00:00.000Z",
    early_voting_starts_at: str = "2026-10-20T00:00:00.000Z",
    early_voting_ends_at: str = "2026-11-02T00:00:00.000Z",
    ballot_return_deadline: str = "2026-11-03T20:00:00.000Z",
    cure_deadline: str = "2026-11-10T00:00:00.000Z",
    certification_deadline: str = "2026-11-20T00:00:00.000Z",
    recount_threshold_pct: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1 election creation payload."""
    payload: Dict[str, Any] = {
        "name": name,
        "election_date": election_date,
        "registration_deadline": registration_deadline,
        "absentee_request_deadline": absentee_request_deadline,
        "early_voting_starts_at": early_voting_starts_at,
        "early_voting_ends_at": early_voting_ends_at,
        "ballot_return_deadline": ballot_return_deadline,
        "cure_deadline": cure_deadline,
        "certification_deadline": certification_deadline,
    }
    if recount_threshold_pct is not None:
        payload["recount_threshold_pct"] = recount_threshold_pct
    payload.update(overrides)
    return payload


def state_transition_payload(to_state: str,
                             version: Optional[int] = None,
                             **overrides) -> Dict[str, Any]:
    """PRD §2.8: 'Any mutating endpoint that targets a specific row by
    its id accepts an optional version field in the request body.'"""
    payload: Dict[str, Any] = {"to_state": to_state}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Precinct — PRD §3.1
# ---------------------------------------------------------------------------
def create_precinct_payload(
    code: str = "P1",
    street_pattern: str = ".*Main.*",
    capacity_machines: int = 2,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'Each precinct carries a code that must be unique within
    the parent election_id, a street_pattern (a regex or CIDR-style
    pattern that drives residency-based voter assignment), and a
    capacity_machines integer.'"""
    payload: Dict[str, Any] = {
        "code": code,
        "street_pattern": street_pattern,
        "capacity_machines": capacity_machines,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Voter — PRD §3.3
# ---------------------------------------------------------------------------
def create_voter_payload(
    election_id: str,
    full_name: Optional[str] = None,
    date_of_birth: str = "1990-01-01T00:00:00.000Z",
    residency_address: Optional[str] = None,
    residency_since: str = "2020-01-01T00:00:00.000Z",
    is_citizen: bool = True,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3: 'the creation payload supplies full_name, date_of_birth,
    residency_address, residency_since, is_citizen, and the election_id
    the voter is registering for.'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Voter {random_suffix(6)}",
        "date_of_birth": date_of_birth,
        "residency_address": residency_address or random_street_address(),
        "residency_since": residency_since,
        "is_citizen": is_citizen,
        "election_id": election_id,
    }
    payload.update(overrides)
    return payload


def patch_voter_payload(version: int,
                        full_name: Optional[str] = None,
                        residency_address: Optional[str] = None,
                        residency_since: Optional[str] = None,
                        **overrides) -> Dict[str, Any]:
    """PRD §3.3: 'A Voter or RegistrarClerk may patch the voter's
    mutable fields — full_name, residency_address, residency_since —
    under OCC.'"""
    payload: Dict[str, Any] = {"version": version}
    if full_name is not None:
        payload["full_name"] = full_name
    if residency_address is not None:
        payload["residency_address"] = residency_address
    if residency_since is not None:
        payload["residency_since"] = residency_since
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Party registration — PRD §3.4
# ---------------------------------------------------------------------------
def change_party_payload(new_party: str,
                         version: Optional[int] = None,
                         **overrides) -> Dict[str, Any]:
    """PRD §3.4: 'The mutation requires a new_party value and accepts
    the optional OCC version.'"""
    payload: Dict[str, Any] = {"new_party": new_party}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Absentee ballot — PRD §3.5
# ---------------------------------------------------------------------------
def request_absentee_payload(election_id: str,
                             reason_code: Optional[str] = None,
                             **overrides) -> Dict[str, Any]:
    """PRD §3.5: 'requests an absentee ballot by supplying the
    election_id and optionally a reason_code.'"""
    payload: Dict[str, Any] = {"election_id": election_id}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    payload.update(overrides)
    return payload


def return_absentee_payload(signature_match: str,
                            voter_choice: str,
                            version: Optional[int] = None,
                            **overrides) -> Dict[str, Any]:
    """PRD §3.5: 'supplying signature_match (MATCH, MISMATCH, or
    MISSING) and the voter_choice the ballot bears.'"""
    payload: Dict[str, Any] = {
        "signature_match": signature_match,
        "voter_choice": voter_choice,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Curing case — PRD §3.5
# ---------------------------------------------------------------------------
def submit_curing_payload(voter_submission_text: str,
                          voter_choice: str,
                          version: Optional[int] = None,
                          **overrides) -> Dict[str, Any]:
    """PRD §3.5: 'submit a cure, supplying voter_submission_text and the
    intended voter_choice.'"""
    payload: Dict[str, Any] = {
        "voter_submission_text": voter_submission_text,
        "voter_choice": voter_choice,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def version_payload(version: Optional[int] = None,
                    **overrides) -> Dict[str, Any]:
    """For endpoints (e.g., POST /curing-cases/{caseId}/request-revision)
    whose only input is an optional OCC version."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# In-person ballot — PRD §3.8
# ---------------------------------------------------------------------------
def create_ballot_payload(voter_id: str,
                          precinct_id: str,
                          method: str,
                          voter_choice: str,
                          machine_id: Optional[str] = None,
                          **overrides) -> Dict[str, Any]:
    """PRD §3.8: 'a payload carrying voter_id, precinct_id, method, an
    optional machine_id (required when method=ELECTION_DAY_MACHINE,
    null otherwise), and voter_choice.'"""
    payload: Dict[str, Any] = {
        "voter_id": voter_id,
        "precinct_id": precinct_id,
        "method": method,
        "voter_choice": voter_choice,
    }
    if machine_id is not None:
        payload["machine_id"] = machine_id
    payload.update(overrides)
    return payload


def invalidate_ballot_payload(challenge_reason: Optional[str] = None,
                              version: Optional[int] = None,
                              **overrides) -> Dict[str, Any]:
    """PRD §3.9: 'The endpoint accepts to_state and an optional
    challenge_reason.'"""
    payload: Dict[str, Any] = {"to_state": "INVALIDATED"}
    if challenge_reason is not None:
        payload["challenge_reason"] = challenge_reason
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Voting machine — PRD §3.1, §3.7
# ---------------------------------------------------------------------------
def create_voting_machine_payload(serial_no: Optional[str] = None,
                                  **overrides) -> Dict[str, Any]:
    """PRD §3.1: 'Each machine carries a serial_no that must be globally
    unique across the entire system.'"""
    payload: Dict[str, Any] = {
        "serial_no": serial_no or random_serial_no(),
    }
    payload.update(overrides)
    return payload


def machine_transition_payload(to_state: str,
                               failure_reason: Optional[str] = None,
                               version: Optional[int] = None,
                               **overrides) -> Dict[str, Any]:
    """PRD §3.7: 'reporting a failure_reason (POWER, JAM, TAMPER, or
    OTHER).'"""
    payload: Dict[str, Any] = {"to_state": to_state}
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recount request — PRD §3.9
# ---------------------------------------------------------------------------
def create_recount_payload(petition_count: int = 100,
                           **overrides) -> Dict[str, Any]:
    """PRD §3.9: 'A manual recount is filed by an ElectionBoard
    operator submitting petition_count against the election.'"""
    payload: Dict[str, Any] = {"petition_count": petition_count}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc", "utcnow", "iso_now", "iso_instant", "parse_iso",
    "add_days", "add_seconds", "add_millis",
    "random_suffix", "random_street_address", "random_serial_no",
    "clock_advance_payload",
    "create_election_payload", "state_transition_payload",
    "create_precinct_payload",
    "create_voter_payload", "patch_voter_payload",
    "change_party_payload",
    "request_absentee_payload", "return_absentee_payload",
    "submit_curing_payload", "version_payload",
    "create_ballot_payload", "invalidate_ballot_payload",
    "create_voting_machine_payload", "machine_transition_payload",
    "create_recount_payload",
]
