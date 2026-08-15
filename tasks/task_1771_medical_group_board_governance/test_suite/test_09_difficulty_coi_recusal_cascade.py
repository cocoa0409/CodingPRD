"""Difficulty queue: transitive cascade — COI FLAGGED recusal + vote voiding."""
from test_helpers import (
    add_member,
    cast_vote,
    charter_amendment_payload,
    create_and_open_motion,
    create_committee,
    create_policy,
    create_shareholder,
    file_coi_disclosure,
    get_motion,
    list_motion_votes,
    review_coi_disclosure,
)


def _setup_open_charter_motion_with_flagged_coi():
    """T, U, V shareholders; FINANCE committee ACTIVE (V sole member);
    CHARTER_AMENDMENT OPEN with snapshot {T,U,V}; T voted FOR; T's related
    disclosure reviewed FLAGGED."""
    create_policy(total_shares_authorized=1000000, board_quorum_count=1)
    t = create_shareholder("Dr T", 1000, "2014-01-01T00:00:00Z")
    create_shareholder("Dr U", 1000, "2015-01-01T00:00:00Z")
    v = create_shareholder("Dr V", 1000, "2016-01-01T00:00:00Z")
    committee = create_committee(
        name="Finance Committee", committee_type="FINANCE", quorum_count=1
    )
    add_member(committee["id"], v["id"], "MEMBER")
    motion = create_and_open_motion(
        "CHARTER_AMENDMENT", t, charter_amendment_payload(new_quorum_count=1),
        committee_id=committee["id"],
    )
    vote = cast_vote(motion["id"], t, "FOR")
    disclosure = file_coi_disclosure(
        t, "Spouse employed by vendor under charter review", related_motion_id=motion["id"]
    )
    reviewed = review_coi_disclosure(disclosure["id"], "FLAGGED", review_note="Material conflict confirmed")
    return t, motion, vote, reviewed


class TestCoiFlagRecusalVoteVoidingCascade:
    def test_link1_recusal_recomputes_eligible_count_and_required_votes(self, api):
        """PRD §3.7: "A `FLAGGED` outcome fires a two-link cascade when
        `related_motion_id` is set and that motion is `OPEN` or `TABLED`: first the
        physician is added to the motion's `recused_physician_ids`, which recomputes
        `eligible_voter_count` and `required_votes`"
        PRD §2.1: "The same is true when `X-User-Role` is `ComplianceOfficer`:
        `X-User-ID` is an opaque operator identifier, recorded for example as
        `reviewed_by` on a `COIDisclosure` at review time, but never compared to any
        entity's `id`."
        Snapshot 3, one recusal -> eligible_voter_count 2; SUPERMAJORITY required =
        ceil(2/3 * 2) = 2.

        Design: Difficulty/transitive_cascade/coi_flag_recusal_vote_voiding_cascade
        """
        t, motion, _vote, reviewed = _setup_open_charter_motion_with_flagged_coi()
        assert reviewed["status"] == "FLAGGED"
        assert reviewed["reviewed_by"] == "co-1", (
            "the reviewing ComplianceOfficer's X-User-ID is recorded as reviewed_by"
        )

        motion_after = get_motion(motion["id"])
        assert t["id"] in motion_after["recused_physician_ids"]
        assert motion_after["eligible_voter_count"] == 2
        assert motion_after["required_votes"] == 2, (
            f"ceil(2/3 * 2) = 2, got {motion_after['required_votes']}"
        )

    def test_link2_cast_vote_voided_and_tallies_recomputed(self, api):
        """PRD §3.7: "second, any `CAST` vote by that physician on that motion becomes
        `VOIDED` with `void_reason` set to `COI_RECUSAL`, and the motion's tallies are
        recomputed excluding it."
        PRD §3.4: "`votes_for`, `votes_against`, and `votes_abstain` count only
        non-`VOIDED` ballots."

        Design: Difficulty/transitive_cascade/coi_flag_recusal_vote_voiding_cascade
        """
        _t, motion, vote, _reviewed = _setup_open_charter_motion_with_flagged_coi()
        votes, _meta = list_motion_votes(motion["id"])
        voided = [v for v in votes if v["id"] == vote["id"]]
        assert len(voided) == 1
        assert voided[0]["status"] == "VOIDED"
        assert voided[0]["void_reason"] == "COI_RECUSAL"

        motion_after = get_motion(motion["id"])
        assert motion_after["votes_for"] == 0, (
            "the voided ballot must be excluded from the tallies"
        )
