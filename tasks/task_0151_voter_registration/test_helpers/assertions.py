"""Entity assertions and domain invariant checkers.

These check response shape and domain invariants required by the PRD
contract.

PRD §2.4 — entities split into two shapes:

    common-fields (Election, Precinct, Voter, AbsenteeBallot,
    CuringCase, BallotCast, VotingMachine, RecountRequest):
        id, created_at, updated_at, version

    lean (PartyRegistration, ClockState):
        id, created_at only — no updated_at, no version
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: version is "a counter initialised to 1 on creation and
    incremented by 1 on every server-side mutation of the row".
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 common-fields entities (Election, Precinct, Voter,
    AbsenteeBallot, CuringCase, BallotCast, VotingMachine,
    RecountRequest)."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)


def assert_lean_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 lean entities (PartyRegistration, ClockState) — id +
    created_at only; no updated_at, no version."""
    _assert_id_and_created_at(data)
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "lean entities must not expose updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "lean entities must not expose version per PRD §2.4"
    )


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.4: every mutation increments version by exactly 1."""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']}+{delta} = "
        f"{before['version'] + delta}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_election(data: Dict[str, Any]) -> None:
    """PRD §2.4, §3.1 Election fields."""
    assert_common_fields(data)
    assert isinstance(data.get("name"), str)
    for ts in ("election_date", "registration_deadline",
               "absentee_request_deadline", "early_voting_starts_at",
               "early_voting_ends_at", "ballot_return_deadline",
               "cure_deadline", "certification_deadline"):
        assert ts in data, f"missing {ts}"
    assert data["state"] in (
        "DRAFT", "OPEN_REGISTRATION", "EARLY_VOTING",
        "ELECTION_DAY", "TALLY", "RECOUNT", "CERTIFIED",
    ), f"unexpected election state: {data['state']!r}"
    # PRD §2.10: ratios rounded to six decimal places (the field itself
    # is supplied as input so we only require the right type).
    assert isinstance(
        data.get("recount_threshold_pct"), (int, float),
    ), "recount_threshold_pct must be numeric"
    assert isinstance(
        data.get("total_registered_active"), int,
    ), "total_registered_active must be integer"


def assert_precinct(data: Dict[str, Any]) -> None:
    """PRD §3.1 Precinct fields."""
    assert_common_fields(data)
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("street_pattern"), str)
    assert isinstance(data.get("capacity_machines"), int)
    # PRD §3.1: "the computed provisional_ballot_count" and
    # "the computed machine_failure_active boolean".
    assert isinstance(data.get("provisional_ballot_count"), int)
    assert isinstance(data.get("machine_failure_active"), bool)


def assert_voter(data: Dict[str, Any]) -> None:
    """PRD §3.3 Voter fields."""
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("residency_address"), str)
    assert isinstance(data.get("is_citizen"), bool)
    assert data["status"] in (
        "PENDING", "ACTIVE", "SUSPENDED", "PURGED",
    ), f"unexpected voter status: {data['status']!r}"
    assert data["party_affiliation"] in (
        "DEMOCRATIC", "REPUBLICAN", "INDEPENDENT", "UNAFFILIATED",
    ), f"unexpected party_affiliation: {data['party_affiliation']!r}"


def assert_absentee_ballot(data: Dict[str, Any]) -> None:
    """PRD §3.5 AbsenteeBallot fields."""
    assert_common_fields(data)
    assert isinstance(data.get("voter_id"), str) and data["voter_id"]
    assert isinstance(data.get("election_id"), str) and data["election_id"]
    assert data["status"] in (
        "REQUESTED", "ISSUED", "RETURNED", "ACCEPTED",
        "REJECTED", "CURED",
    ), f"unexpected absentee status: {data['status']!r}"
    assert data["reason_code"] in (
        "MILITARY", "OVERSEAS", "DISABILITY", "ABSENT", "NO_REASON",
    ), f"unexpected reason_code: {data['reason_code']!r}"


def assert_curing_case(data: Dict[str, Any]) -> None:
    """PRD §3.5 CuringCase fields."""
    assert_common_fields(data)
    assert isinstance(data.get("absentee_ballot_id"), str)
    assert isinstance(data.get("voter_id"), str)
    assert data["defect_code"] in (
        "SIGNATURE_MISMATCH", "SIGNATURE_MISSING",
    ), f"unexpected defect_code: {data['defect_code']!r}"
    assert isinstance(data.get("round_count"), int)
    assert isinstance(data.get("max_rounds"), int)
    assert data["status"] in (
        "OPEN_PENDING_VOTER", "UNDER_REVIEW",
        "RESOLVED_ACCEPT", "RESOLVED_REJECT", "EXPIRED",
    ), f"unexpected curing status: {data['status']!r}"


def assert_ballot_cast(data: Dict[str, Any]) -> None:
    """PRD §3.8 BallotCast fields."""
    assert_common_fields(data)
    assert isinstance(data.get("voter_id"), str)
    assert isinstance(data.get("precinct_id"), str)
    assert isinstance(data.get("election_id"), str)
    assert data["method"] in (
        "EARLY_IN_PERSON", "ELECTION_DAY_MACHINE",
        "ELECTION_DAY_PROVISIONAL", "ABSENTEE",
    ), f"unexpected ballot method: {data['method']!r}"
    assert data["status"] in (
        "CAST", "TALLIED", "CHALLENGED", "INVALIDATED",
    ), f"unexpected ballot status: {data['status']!r}"
    assert isinstance(data.get("voter_choice"), str)


def assert_voting_machine(data: Dict[str, Any]) -> None:
    """PRD §3.7 VotingMachine fields."""
    assert_common_fields(data)
    assert isinstance(data.get("serial_no"), str)
    assert data["status"] in (
        "READY", "IN_USE", "DOWN", "DECOMMISSIONED",
    ), f"unexpected machine status: {data['status']!r}"
    assert isinstance(data.get("backup_emergency_ballots_issued"), int)


def assert_recount_request(data: Dict[str, Any]) -> None:
    """PRD §3.9 RecountRequest fields."""
    assert_common_fields(data)
    assert isinstance(data.get("election_id"), str)
    assert data["requested_by_role"] in (
        "ElectionBoard", "system",
    ), f"unexpected requested_by_role: {data['requested_by_role']!r}"
    assert data["status"] in (
        "REQUESTED", "APPROVED", "IN_PROGRESS",
        "RESOLVED_NO_CHANGE", "RESOLVED_OVERTURN", "DENIED",
    ), f"unexpected recount status: {data['status']!r}"


def assert_party_registration(data: Dict[str, Any]) -> None:
    """PRD §3.4 PartyRegistration is append-only — lean shape."""
    assert_lean_fields(data)
    assert isinstance(data.get("voter_id"), str)
    assert data["previous_party"] in (
        "DEMOCRATIC", "REPUBLICAN", "INDEPENDENT", "UNAFFILIATED",
    )
    assert data["new_party"] in (
        "DEMOCRATIC", "REPUBLICAN", "INDEPENDENT", "UNAFFILIATED",
    )
    assert data["actor_role"] in (
        "VoterSelf", "RegistrarClerk",
    ), f"unexpected actor_role: {data['actor_role']!r}"


# ---------------------------------------------------------------------------
# Margin / precision helpers — PRD §2.10
# ---------------------------------------------------------------------------
def assert_margin_precision(value: float) -> None:
    """PRD §2.10: "Percentages and ratios produced by the tally pipeline
    ... are rounded to six decimal places using round-half-up."

    We accept floats whose ulp matches a six-decimal-place rounded
    value (tolerance 1e-9 to absorb float printing noise).
    """
    rounded = round(value + 1e-12, 6)
    assert abs(value - rounded) <= 1e-9, (
        f"margin {value!r} is not 6-decimal precision"
    )


__all__ = [
    "assert_common_fields",
    "assert_lean_fields",
    "assert_version_incremented_by",
    "assert_election",
    "assert_precinct",
    "assert_voter",
    "assert_absentee_ballot",
    "assert_curing_case",
    "assert_ballot_cast",
    "assert_voting_machine",
    "assert_recount_request",
    "assert_party_registration",
    "assert_margin_precision",
]
