"""Cascade side-effects (PRD §2.6).

- Voter ACTIVE -> SUSPENDED triggers AbsenteeBallot {REQUESTED, ISSUED,
  RETURNED} -> REJECTED, which in turn (for ballots that have a
  linked_curing_case_id in OPEN_PENDING_VOTER or UNDER_REVIEW) drives
  the CuringCase to RESOLVED_REJECT.
- CuringCase -> RESOLVED_ACCEPT cascades the linked AbsenteeBallot to
  CURED and creates a BallotCast(method=ABSENTEE).
- CuringCase -> EXPIRED cascades the linked AbsenteeBallot to REJECTED.
"""
from __future__ import annotations

from typing import List

from ..store import store
from ..util import new_uuid
from .common import bump_version


def cascade_voter_suspend(voter: dict) -> None:
    """Link-2 + Link-3 cascade for voter SUSPENDED."""
    s = store()
    now = s.now()
    for b in list(s.absentee_ballots.values()):
        if b.get("voter_id") != voter["id"]:
            continue
        if b.get("status") not in ("REQUESTED", "ISSUED", "RETURNED"):
            continue
        from_state = b["status"]
        b["status"] = "REJECTED"
        b["decided_at"] = now
        bump_version(b, now)
        # Link 3 — transitive on RETURNED -> REJECTED with linked curing case
        if from_state == "RETURNED" and b.get("linked_curing_case_id"):
            cc = s.curing_cases.get(b["linked_curing_case_id"])
            if cc and cc.get("status") in ("OPEN_PENDING_VOTER", "UNDER_REVIEW"):
                cc["status"] = "RESOLVED_REJECT"
                bump_version(cc, now)


def cascade_curing_resolved_accept(case: dict) -> None:
    """Cascade-up CuringCase RESOLVED_ACCEPT to AbsenteeBallot CURED + create BallotCast."""
    s = store()
    now = s.now()
    ballot = s.absentee_ballots.get(case["absentee_ballot_id"])
    if not ballot:
        return
    ballot["status"] = "CURED"
    ballot["decided_at"] = now
    bump_version(ballot, now)
    # Create BallotCast with method=ABSENTEE using the voter_choice captured at cure
    voter = s.voters.get(case["voter_id"])
    precinct_id = voter.get("precinct_id") if voter else None
    bc = _create_ballot_cast(
        precinct_id=precinct_id,
        voter_id=case["voter_id"],
        election_id=case["election_id"],
        method="ABSENTEE",
        machine_id=None,
        absentee_ballot_id=ballot["id"],
        voter_choice=case.get("voter_choice"),
        now=now,
    )
    if bc is not None:
        ballot["voter_choice"] = case.get("voter_choice")


def cascade_absentee_accept_on_return(ballot: dict, voter_choice: str) -> None:
    """ISSUED -> RETURNED with signature_match=MATCH cascades to ACCEPTED + BallotCast."""
    s = store()
    now = s.now()
    ballot["status"] = "ACCEPTED"
    ballot["decided_at"] = now
    bump_version(ballot, now)
    voter = s.voters.get(ballot["voter_id"])
    precinct_id = voter.get("precinct_id") if voter else None
    _create_ballot_cast(
        precinct_id=precinct_id,
        voter_id=ballot["voter_id"],
        election_id=ballot["election_id"],
        method="ABSENTEE",
        machine_id=None,
        absentee_ballot_id=ballot["id"],
        voter_choice=voter_choice,
        now=now,
    )


def cascade_curing_expired(case: dict) -> None:
    """CuringCase -> EXPIRED cascades AbsenteeBallot RETURNED -> REJECTED."""
    s = store()
    now = s.now()
    ballot = s.absentee_ballots.get(case.get("absentee_ballot_id"))
    if ballot and ballot.get("status") == "RETURNED":
        ballot["status"] = "REJECTED"
        ballot["decided_at"] = now
        bump_version(ballot, now)


def _create_ballot_cast(
    *,
    precinct_id,
    voter_id,
    election_id,
    method,
    machine_id,
    absentee_ballot_id,
    voter_choice,
    now,
):
    """Internal helper used by cascade flows. Enforces double-vote
    by invalidating any later cast (handles data-import edge case)."""
    from ..store import store
    s = store()
    # If a non-INVALIDATED cast already exists for (voter, election), the
    # new one is INVALIDATED per the data-import semantics described in
    # SCAFFOLD calculations.precinct_margin / state_machines.BallotCast.
    existing = [
        c for c in s.ballot_casts.values()
        if c.get("voter_id") == voter_id
        and c.get("election_id") == election_id
        and c.get("status") != "INVALIDATED"
    ]
    initial_status = "CAST"
    challenge_reason = None
    if existing:
        # mark this newly-created (later) one as INVALIDATED to preserve the first
        initial_status = "INVALIDATED"
        challenge_reason = "DOUBLE_VOTE"

    bc = {
        "id": new_uuid(),
        "precinct_id": precinct_id,
        "voter_id": voter_id,
        "election_id": election_id,
        "method": method,
        "machine_id": machine_id,
        "absentee_ballot_id": absentee_ballot_id,
        "voter_choice": voter_choice,
        "cast_at": now,
        "status": initial_status,
        "challenge_reason": challenge_reason,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("ballot_casts", bc)
    return bc
