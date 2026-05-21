"""Server-clock sweep (PRD §2.5).

Triggered by POST /_clock/advance after the clock moves forward. It:

- Rolls Elections through OPEN_REGISTRATION -> EARLY_VOTING when
  now >= early_voting_starts_at; auto-suspends any PENDING voters that
  fail strict eligibility at the new instant.
- Rolls Elections through EARLY_VOTING -> ELECTION_DAY when
  now >= early_voting_ends_at.
- Expires any CuringCase in OPEN_PENDING_VOTER or UNDER_REVIEW when
  now > Election.cure_deadline; cascades the linked AbsenteeBallot
  RETURNED -> REJECTED.
"""
from __future__ import annotations

from ..store import store
from .cascades import cascade_curing_expired, cascade_voter_suspend
from .common import bump_version
from .eligibility import passes_strict


def run_sweep() -> None:
    s = store()
    now = s.now()

    # 1. Election day-rollovers
    # We may need multiple passes — OPEN_REGISTRATION -> EARLY_VOTING ->
    # ELECTION_DAY can fire in a single clock advance.
    changed = True
    while changed:
        changed = False
        for e in list(s.elections.values()):
            if e["state"] == "OPEN_REGISTRATION" and now >= e["early_voting_starts_at"]:
                # PRD §3.6: snapshot which voters were ACTIVE at the
                # moment of registration_deadline. The cure-grace
                # variant later keys off this snapshot.
                for v in list(s.voters.values()):
                    if v.get("election_id") != e["id"]:
                        continue
                    v["was_active_at_registration_deadline"] = (
                        v.get("status") == "ACTIVE"
                    )
                e["state"] = "EARLY_VOTING"
                bump_version(e, now)
                # Cascade: auto-suspend PENDING voters that newly fail eligibility.
                for v in list(s.voters.values()):
                    if v.get("election_id") != e["id"]:
                        continue
                    if v.get("status") != "PENDING":
                        continue
                    ok, _ = passes_strict(v, e)
                    if not ok:
                        v["status"] = "SUSPENDED"
                        bump_version(v, now)
                        cascade_voter_suspend(v)
                changed = True
            elif e["state"] == "EARLY_VOTING" and now >= e["early_voting_ends_at"]:
                e["state"] = "ELECTION_DAY"
                bump_version(e, now)
                changed = True

    # 2. CuringCase expiry
    for cc in list(s.curing_cases.values()):
        if cc.get("status") not in ("OPEN_PENDING_VOTER", "UNDER_REVIEW"):
            continue
        election = s.elections.get(cc.get("election_id"))
        if not election:
            continue
        if now > election["cure_deadline"]:
            cc["status"] = "EXPIRED"
            bump_version(cc, now)
            cascade_curing_expired(cc)
