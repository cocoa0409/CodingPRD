"""Lazy time-driven sweeps invoked by /hoa/_clock/advance and by reads/mutations.

The PRD describes lazy evaluation of:
  * AssessmentCharge OPEN -> OVERDUE (and late-fee recompute) when clock crosses due_date.
  * Violation OPEN -> FINED when clock_now > cure_deadline.
  * ACCRequest UNDER_REVIEW -> AUTO_APPROVED / AUTO_DENIED at deemed_decision_deadline.
  * ElectionCycle NOMINATION -> VOTING / VOIDED at voting_open_at;
    VOTING -> TALLIED / FAILED_QUORUM at voting_close_at.
  * BoardResolution PROPOSED -> FAILED at created_at + 14 days.
  * Member.total_overdue_amount_cents recompute.

All of these are idempotent: running the sweep again with the same clock value
makes no further changes.
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Optional

from ..calculations import late_fee_for_charge, violation_fine_for_occurrence
from ..store import store
from .common import bump_member_overdue, bump_version


def run_sweep(target_member_ids: Optional[set] = None) -> None:
    """Re-evaluate all time-gated transitions against the current clock."""
    s = store()
    now = s.now()

    affected_members: set = set(target_member_ids or [])

    # 1. AssessmentCharges — apply OVERDUE transitions & recompute late fees.
    for ch in list(s.assessment_charges.values()):
        cycle = s.assessment_cycles.get(ch["cycle_id"])
        if cycle is None:
            continue
        outstanding = ch["principal_cents"] + ch["late_fee_cents"] - ch["paid_cents"]
        if ch["status"] in {"PAID", "WRITTEN_OFF"}:
            continue
        if now > cycle["due_date"] and outstanding > 0:
            new_fee = late_fee_for_charge(
                cycle_type=cycle["cycle_type"],
                due_date=cycle["due_date"],
                clock_now=now,
                principal_cents=ch["principal_cents"],
            )
            changed = False
            if ch["status"] != "OVERDUE":
                ch["status"] = "OVERDUE"
                changed = True
            if ch["late_fee_cents"] != new_fee:
                ch["late_fee_cents"] = new_fee
                changed = True
            if changed:
                bump_version(ch, now)
                unit = s.units.get(ch["unit_id"])
                if unit is not None:
                    affected_members.add(unit["owner_member_id"])

    # 2. Violations — auto-FINE expired OPEN ones.
    for v in list(s.violations.values()):
        if v["status"] != "OPEN":
            continue
        if now > v["cure_deadline"]:
            v["status"] = "FINED"
            v["fine_cents"] = violation_fine_for_occurrence(v["occurrence_index"])
            bump_version(v, now)
            unit = s.units.get(v["unit_id"])
            if unit is not None:
                affected_members.add(unit["owner_member_id"])

    # 3. ACCRequests — silent decisions.
    for r in list(s.acc_requests.values()):
        if r["status"] != "UNDER_REVIEW":
            continue
        if now >= r["deemed_decision_deadline"]:
            if r["category"] == "LANDSCAPING":
                r["status"] = "AUTO_APPROVED"
            else:
                r["status"] = "AUTO_DENIED"
            bump_version(r, now)

    # 4. Elections — NOMINATION -> VOTING or VOIDED; VOTING -> TALLIED or FAILED_QUORUM.
    for e in list(s.elections.values()):
        if e["status"] == "NOMINATION" and now >= e["voting_open_at"]:
            candidates = [c for c in s.candidates.values() if c["election_id"] == e["id"]]
            if not candidates:
                e["status"] = "VOIDED"
                bump_version(e, now)
            else:
                eligible_ids = [
                    m["id"]
                    for m in s.members.values()
                    if _is_eligible_to_vote(m)
                ]
                e["eligible_voter_count_at_open"] = len(eligible_ids)
                e["eligible_voter_ids_at_open"] = set(eligible_ids)
                e["status"] = "VOTING"
                bump_version(e, now)
        if e["status"] == "VOTING" and now >= e["voting_close_at"]:
            _tally_election(e)

    # 5. BoardResolutions — auto-FAIL at created_at + 14 days.
    for r in list(s.board_resolutions.values()):
        if r["status"] == "PROPOSED" and now > r["created_at"] + timedelta(days=14):
            r["status"] = "FAILED"
            bump_version(r, now)

    # 6. Recompute member overdue aggregates.
    for mid in affected_members:
        member = s.members.get(mid)
        if member is not None:
            bump_member_overdue(member)


def _tally_election(election: dict) -> None:
    s = store()
    now = s.now()
    ballots = [b for b in s.ballots.values() if b["election_id"] == election["id"]]
    total_ballots = len(ballots)
    eligible = election.get("eligible_voter_count_at_open") or 0
    required = math.ceil(eligible * float(election["quorum_pct"]))
    if total_ballots < required:
        election["status"] = "FAILED_QUORUM"
        election["winner_candidate_id"] = None
    else:
        candidates = [c for c in s.candidates.values() if c["election_id"] == election["id"]]
        # vote counts already maintained on candidate rows
        ranked = sorted(
            candidates, key=lambda c: (-c["vote_count"], c["nominated_at"])
        )
        if ranked:
            election["winner_candidate_id"] = ranked[0]["id"]
            election["status"] = "TALLIED"
        else:
            election["status"] = "FAILED_QUORUM"
            election["winner_candidate_id"] = None
    bump_version(election, now)


def _is_eligible_to_vote(member: dict) -> bool:
    from .common import compute_eligible_to_vote

    return compute_eligible_to_vote(member)
