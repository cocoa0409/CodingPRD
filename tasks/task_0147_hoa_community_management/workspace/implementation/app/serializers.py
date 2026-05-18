"""Per-entity JSON serialization.

The internal representation stores datetimes as Python ``datetime`` objects so
that comparisons stay precise. Serializers project them to the ISO 8601 UTC
string format mandated by PRD §2.4.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .util import format_iso8601


def _fmt(dt):
    if dt is None:
        return None
    return format_iso8601(dt)


def serialize_unit(u: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": u["id"],
        "address": u["address"],
        "owner_member_id": u["owner_member_id"],
        "share_factor": u["share_factor"],
        "mortgage_holder": u.get("mortgage_holder"),
        "lien_status": u.get("lien_status", "NONE"),
        "created_at": _fmt(u["created_at"]),
        "updated_at": _fmt(u["updated_at"]),
        "version": u["version"],
    }


def serialize_member(m: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "eligible_to_vote": m.get("eligible_to_vote", False),
        "board_role": m.get("board_role", "NONE"),
        "total_overdue_amount_cents": m.get("total_overdue_amount_cents", 0),
        "created_at": _fmt(m["created_at"]),
        "updated_at": _fmt(m["updated_at"]),
        "version": m["version"],
    }


def serialize_assessment_cycle(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": c["id"],
        "cycle_type": c["cycle_type"],
        "period_start": _fmt(c["period_start"]),
        "due_date": _fmt(c["due_date"]),
        "total_levy_cents": c["total_levy_cents"],
        "approval_resolution_id": c.get("approval_resolution_id"),
        "status": c.get("status", "DRAFT"),
        "created_at": _fmt(c["created_at"]),
    }


def serialize_assessment_charge(ch: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": ch["id"],
        "cycle_id": ch["cycle_id"],
        "unit_id": ch["unit_id"],
        "principal_cents": ch.get("principal_cents", 0),
        "late_fee_cents": ch.get("late_fee_cents", 0),
        "paid_cents": ch.get("paid_cents", 0),
        "status": ch.get("status", "OPEN"),
        "created_at": _fmt(ch["created_at"]),
        "updated_at": _fmt(ch["updated_at"]),
        "version": ch["version"],
    }


def serialize_payment(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "member_id": p["member_id"],
        "amount_cents": p["amount_cents"],
        "allocations": list(p.get("allocations", [])),
        "created_at": _fmt(p["created_at"]),
    }


def serialize_acc_request(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "unit_id": r["unit_id"],
        "submitted_by_member_id": r["submitted_by_member_id"],
        "category": r["category"],
        "description": r["description"],
        "submitted_at": _fmt(r["submitted_at"]),
        "deemed_decision_deadline": _fmt(r["deemed_decision_deadline"]),
        "status": r.get("status", "SUBMITTED"),
        "yes_votes": r.get("yes_votes", 0),
        "no_votes": r.get("no_votes", 0),
        "created_at": _fmt(r["created_at"]),
        "updated_at": _fmt(r["updated_at"]),
        "version": r["version"],
    }


def serialize_acc_vote(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": v["id"],
        "request_id": v["request_id"],
        "voter_member_id": v["voter_member_id"],
        "vote": v["vote"],
        "cast_at": _fmt(v["cast_at"]),
        "created_at": _fmt(v["created_at"]),
    }


def serialize_violation(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": v["id"],
        "unit_id": v["unit_id"],
        "opened_by_member_id": v["opened_by_member_id"],
        "description": v.get("description"),
        "opened_at": _fmt(v["opened_at"]),
        "cure_deadline": _fmt(v["cure_deadline"]),
        "occurrence_index": v.get("occurrence_index", 1),
        "fine_cents": v.get("fine_cents", 0),
        "status": v.get("status", "OPEN"),
        "created_at": _fmt(v["created_at"]),
        "updated_at": _fmt(v["updated_at"]),
        "version": v["version"],
    }


def serialize_board_resolution(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "subject": r["subject"],
        "target_id": r["target_id"],
        "yes_votes": r.get("yes_votes", 0),
        "no_votes": r.get("no_votes", 0),
        "status": r.get("status", "PROPOSED"),
        "created_at": _fmt(r["created_at"]),
        "updated_at": _fmt(r["updated_at"]),
        "version": r["version"],
    }


def serialize_election(e: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": e["id"],
        "seat": e["seat"],
        "nomination_open_at": _fmt(e["nomination_open_at"]),
        "voting_open_at": _fmt(e["voting_open_at"]),
        "voting_close_at": _fmt(e["voting_close_at"]),
        "quorum_pct": e["quorum_pct"],
        "eligible_voter_count_at_open": e.get("eligible_voter_count_at_open"),
        "status": e.get("status", "NOMINATION"),
        "winner_candidate_id": e.get("winner_candidate_id"),
        "created_at": _fmt(e["created_at"]),
        "updated_at": _fmt(e["updated_at"]),
        "version": e["version"],
    }


def serialize_candidate(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": c["id"],
        "election_id": c["election_id"],
        "member_id": c["member_id"],
        "nominated_at": _fmt(c["nominated_at"]),
        "vote_count": c.get("vote_count", 0),
        "created_at": _fmt(c["created_at"]),
    }


def serialize_ballot(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": b["id"],
        "election_id": b["election_id"],
        "voter_member_id": b["voter_member_id"],
        "candidate_id": b["candidate_id"],
        "created_at": _fmt(b["created_at"]),
    }


def serialize_lien(l: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": l["id"],
        "unit_id": l["unit_id"],
        "principal_cents_at_record": l.get("principal_cents_at_record"),
        "mortgage_holder_at_record": l.get("mortgage_holder_at_record"),
        "recorded_at": _fmt(l.get("recorded_at")),
        "released_at": _fmt(l.get("released_at")),
        "status": l.get("status", "NOTICE_SENT"),
        "created_at": _fmt(l["created_at"]),
        "updated_at": _fmt(l["updated_at"]),
        "version": l["version"],
    }


def serialize_reserve_study(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "study_year": r["study_year"],
        "components": list(r["components"]),
        "current_reserve_balance_cents": r["current_reserve_balance_cents"],
        "full_funding_target_cents": r.get("full_funding_target_cents", 0),
        "funded_ratio": r.get("funded_ratio"),
        "posture": r.get("posture", "OK"),
        "adopted_resolution_id": r.get("adopted_resolution_id"),
        "status": r.get("status", "DRAFT"),
        "created_at": _fmt(r["created_at"]),
        "updated_at": _fmt(r["updated_at"]),
        "version": r["version"],
    }
