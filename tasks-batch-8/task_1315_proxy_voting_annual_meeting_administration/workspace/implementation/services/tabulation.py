"""Weighted tabulation (scaffold §1.3 weighted_tabulation, PRD §3.4).

Each VALIDATED instruction is converted to a whole number of weighted votes
(shares_voted x class weight 1.0/0.5) rounded half-up PER INSTRUCTION BEFORE
summation — the per-instruction-then-sum order is pinned and must not be
replaced by sum-then-round.

Variants:
- UNOFFICIAL (default): includes VALIDATED votes with an OPEN challenge.
- CERTIFIED: excludes VALIDATED votes with an OPEN challenge on the meeting.
"""

from __future__ import annotations

from decimal import Decimal

import db
from util import round_half_up_int

CLASS_WEIGHT = {
    "COMMON": Decimal("1.0"),
    "PREFERRED": Decimal("0.5"),
}


def compute_tabulation(proposal: dict, variant: str) -> dict:
    meeting = db.meetings.get(proposal["meeting_id"])

    included = [
        v
        for v in db.votes.values()
        if v["proposal_id"] == proposal["id"] and v["status"] == "VALIDATED"
    ]
    if variant == "CERTIFIED":
        challenged_ids = {
            c["vote_instruction_id"]
            for c in db.challenges.values()
            if c["meeting_id"] == proposal["meeting_id"] and c["status"] == "OPEN"
        }
        included = [v for v in included if v["id"] not in challenged_ids]

    totals = {"FOR": 0, "AGAINST": 0, "ABSTAIN": 0, "WITHHOLD": 0}
    for vi in included:
        account = db.accounts.get(vi["account_id"])
        weight = CLASS_WEIGHT[account["share_class"]] if account else Decimal("1.0")
        # Pinned order: round EACH instruction first, then sum.
        weighted = round_half_up_int(Decimal(vi["shares_voted"]) * weight)
        totals[vi["choice"]] += weighted

    for_votes = totals["FOR"]
    against_votes = totals["AGAINST"]
    abstain_votes = totals["ABSTAIN"]
    withhold_votes = totals["WITHHOLD"]
    # Abstentions and withholds are NOT votes cast.
    votes_cast = for_votes + against_votes

    standard = proposal["vote_standard"]
    if standard == "MAJORITY_OF_VOTES_CAST":
        outcome = "PASS" if (votes_cast > 0 and for_votes * 2 > votes_cast) else "FAIL"
    elif standard == "MAJORITY_OF_OUTSTANDING":
        outcome = (
            "PASS" if (for_votes * 2 > meeting["outstanding_shares"]) else "FAIL"
        )
    else:  # PLURALITY
        outcome = "PASS" if (for_votes > withhold_votes) else "FAIL"

    return {
        "proposal_id": proposal["id"],
        "variant": variant,
        "for_votes": for_votes,
        "against_votes": against_votes,
        "abstain_votes": abstain_votes,
        "withhold_votes": withhold_votes,
        "votes_cast": votes_cast,
        "projected_outcome": outcome,
    }
