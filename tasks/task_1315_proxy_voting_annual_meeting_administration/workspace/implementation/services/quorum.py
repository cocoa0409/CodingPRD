"""Quorum calculation (scaffold §1.3 quorum_calculation, PRD §3.7).

Variants:
- PROVISIONAL: sums shares_voted across VALIDATED instructions of the meeting
  (challenged-but-still-valid votes included); walk_in_shares never counted.
- FINAL: excludes VALIDATED instructions carrying an OPEN VoteChallenge and
  adds the meeting's walk_in_shares.

Both figures are converted to integer basis points (x10000, round-half-up)
before comparison. CONTESTED meetings enforce a 0.50 effective-threshold floor.
"""

from __future__ import annotations

from decimal import Decimal

import db
from util import round_half_up_int

BP_SCALE = 10000
CONTESTED_MIN_QUORUM_PCT = Decimal("0.50")


def compute_quorum(meeting: dict, variant: str, walk_in_shares: int | None = None) -> dict:
    validated = [
        v
        for v in db.votes.values()
        if v["meeting_id"] == meeting["id"] and v["status"] == "VALIDATED"
    ]

    if variant == "FINAL":
        challenged_ids = {
            c["vote_instruction_id"]
            for c in db.challenges.values()
            if c["meeting_id"] == meeting["id"] and c["status"] == "OPEN"
        }
        shares_present = sum(
            v["shares_voted"] for v in validated if v["id"] not in challenged_ids
        )
        walk_ins = meeting["walk_in_shares"] if walk_in_shares is None else walk_in_shares
        shares_present += walk_ins
    else:  # PROVISIONAL
        shares_present = sum(v["shares_voted"] for v in validated)

    effective_threshold = Decimal(str(meeting["quorum_threshold_pct"]))
    if meeting["meeting_type"] == "CONTESTED":
        effective_threshold = max(effective_threshold, CONTESTED_MIN_QUORUM_PCT)

    threshold_bp = round_half_up_int(Decimal(BP_SCALE) * effective_threshold)
    quorum_pct_bp = round_half_up_int(
        Decimal(BP_SCALE) * Decimal(shares_present) / Decimal(meeting["outstanding_shares"])
    )

    return {
        "meeting_id": meeting["id"],
        "variant": variant,
        "shares_present": shares_present,
        "outstanding_shares": meeting["outstanding_shares"],
        "quorum_pct_bp": quorum_pct_bp,
        "threshold_bp": threshold_bp,
        "quorum_met": quorum_pct_bp >= threshold_bp,
    }
