"""Per-entity JSON serialization."""
from __future__ import annotations

from typing import Any, Dict

from .util import format_iso8601
from .store import store


def _fmt(dt):
    if dt is None:
        return None
    return format_iso8601(dt)


# ----- Election -----
def serialize_election(e: Dict[str, Any]) -> Dict[str, Any]:
    total_active = _compute_total_registered_active(e["id"])
    return {
        "id": e["id"],
        "name": e["name"],
        "election_date": _fmt(e["election_date"]),
        "registration_deadline": _fmt(e["registration_deadline"]),
        "absentee_request_deadline": _fmt(e["absentee_request_deadline"]),
        "early_voting_starts_at": _fmt(e["early_voting_starts_at"]),
        "early_voting_ends_at": _fmt(e["early_voting_ends_at"]),
        "ballot_return_deadline": _fmt(e["ballot_return_deadline"]),
        "cure_deadline": _fmt(e["cure_deadline"]),
        "certification_deadline": _fmt(e["certification_deadline"]),
        "recount_threshold_pct": e["recount_threshold_pct"],
        "state": e["state"],
        "total_registered_active": total_active,
        "certified_winner_voter_choice": e.get("certified_winner_voter_choice"),
        "created_at": _fmt(e["created_at"]),
        "updated_at": _fmt(e["updated_at"]),
        "version": e["version"],
    }


def _compute_total_registered_active(election_id: str) -> int:
    s = store()
    return sum(
        1
        for v in s.voters.values()
        if v.get("election_id") == election_id
        and v.get("status") == "ACTIVE"
        and v.get("precinct_id") is not None
    )


# ----- Precinct -----
def serialize_precinct(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "election_id": p["election_id"],
        "code": p["code"],
        "street_pattern": p["street_pattern"],
        "capacity_machines": p["capacity_machines"],
        "provisional_ballot_count": _compute_provisional_ballot_count(p["id"]),
        "machine_failure_active": _compute_machine_failure_active(p["id"]),
        "created_at": _fmt(p["created_at"]),
        "updated_at": _fmt(p["updated_at"]),
        "version": p["version"],
    }


def _compute_provisional_ballot_count(precinct_id: str) -> int:
    s = store()
    return sum(
        1
        for b in s.ballot_casts.values()
        if b.get("precinct_id") == precinct_id
        and b.get("method") == "ELECTION_DAY_PROVISIONAL"
        and b.get("status") in ("CAST", "TALLIED", "CHALLENGED")
    )


def _compute_machine_failure_active(precinct_id: str) -> bool:
    s = store()
    return any(
        m.get("precinct_id") == precinct_id and m.get("status") == "DOWN"
        for m in s.voting_machines.values()
    )


# ----- Voter -----
def serialize_voter(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": v["id"],
        "full_name": v["full_name"],
        "date_of_birth": _fmt(v["date_of_birth"]),
        "residency_address": v["residency_address"],
        "residency_since": _fmt(v["residency_since"]),
        "is_citizen": v["is_citizen"],
        "election_id": v["election_id"],
        "precinct_id": v.get("precinct_id"),
        "status": v["status"],
        "party_affiliation": v.get("party_affiliation", "UNAFFILIATED"),
        "party_locked_at": _fmt(v.get("party_locked_at")),
        "registered_by_user_id": v.get("registered_by_user_id"),
        "created_at": _fmt(v["created_at"]),
        "updated_at": _fmt(v["updated_at"]),
        "version": v["version"],
    }


# ----- PartyRegistration -----
def serialize_party_registration(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "voter_id": p["voter_id"],
        "previous_party": p["previous_party"],
        "new_party": p["new_party"],
        "actor_role": p["actor_role"],
        "created_at": _fmt(p["created_at"]),
    }


# ----- AbsenteeBallot -----
def serialize_absentee(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": b["id"],
        "voter_id": b["voter_id"],
        "election_id": b["election_id"],
        "requested_at": _fmt(b.get("requested_at")),
        "issued_at": _fmt(b.get("issued_at")),
        "returned_at": _fmt(b.get("returned_at")),
        "decided_at": _fmt(b.get("decided_at")),
        "reason_code": b.get("reason_code", "NO_REASON"),
        "signature_match": b.get("signature_match"),
        "status": b["status"],
        "linked_curing_case_id": b.get("linked_curing_case_id"),
        "voter_choice": b.get("voter_choice"),
        "created_at": _fmt(b["created_at"]),
        "updated_at": _fmt(b["updated_at"]),
        "version": b["version"],
    }


# ----- CuringCase -----
def serialize_curing_case(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": c["id"],
        "absentee_ballot_id": c["absentee_ballot_id"],
        "voter_id": c["voter_id"],
        "election_id": c["election_id"],
        "defect_code": c["defect_code"],
        "round_count": c.get("round_count", 0),
        "max_rounds": c.get("max_rounds", 3),
        "voter_submission_text": c.get("voter_submission_text"),
        "voter_choice": c.get("voter_choice"),
        "status": c["status"],
        "created_at": _fmt(c["created_at"]),
        "updated_at": _fmt(c["updated_at"]),
        "version": c["version"],
    }


# ----- BallotCast -----
def serialize_ballot_cast(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": b["id"],
        "precinct_id": b["precinct_id"],
        "voter_id": b["voter_id"],
        "election_id": b["election_id"],
        "method": b["method"],
        "machine_id": b.get("machine_id"),
        "absentee_ballot_id": b.get("absentee_ballot_id"),
        "voter_choice": b["voter_choice"],
        "cast_at": _fmt(b["cast_at"]),
        "status": b["status"],
        "challenge_reason": b.get("challenge_reason"),
        "created_at": _fmt(b["created_at"]),
        "updated_at": _fmt(b["updated_at"]),
        "version": b["version"],
    }


# ----- VotingMachine -----
def serialize_voting_machine(m: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": m["id"],
        "precinct_id": m["precinct_id"],
        "serial_no": m["serial_no"],
        "status": m["status"],
        "failure_reason": m.get("failure_reason"),
        "down_since": _fmt(m.get("down_since")),
        "backup_emergency_ballots_issued": _compute_backup_count(m),
        "created_at": _fmt(m["created_at"]),
        "updated_at": _fmt(m["updated_at"]),
        "version": m["version"],
    }


def _compute_backup_count(m: Dict[str, Any]) -> int:
    if m.get("down_since") is None:
        return 0
    s = store()
    return sum(
        1
        for b in s.ballot_casts.values()
        if b.get("precinct_id") == m["precinct_id"]
        and b.get("method") == "ELECTION_DAY_PROVISIONAL"
        and b.get("cast_at") is not None
        and b["cast_at"] >= m["down_since"]
    )


# ----- RecountRequest -----
def serialize_recount(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "election_id": r["election_id"],
        "requested_by_role": r["requested_by_role"],
        "petition_count": r.get("petition_count", 0),
        "trigger_margin_pct": r.get("trigger_margin_pct"),
        "status": r["status"],
        "reconciled_totals_json": r.get("reconciled_totals_json"),
        "created_at": _fmt(r["created_at"]),
        "updated_at": _fmt(r["updated_at"]),
        "version": r["version"],
    }
