"""Vote outcome determination: the ORDINARY present-and-voting variant vs the
SPECIAL full-board-majority variant over identical ballots."""
from test_helpers import (
    cast_ballot,
    close_vote_as_chair,
    create_meeting_resolution,
    get_success_data,
    open_vote_as_chair,
    setup_corporation_with_directors,
    setup_in_session_meeting,
    table_resolution,
    SECRETARY,
)
from test_helpers import api_client


def _setup_two_open_votes(api):
    """5 directors all present, meeting IN_SESSION; one ORDINARY and one
    SPECIAL resolution each VOTE_OPEN; each has identical ballots:
    D1 FOR, D2 FOR, D3 AGAINST, D4 ABSTAIN, D5 RECUSED.
    """
    corp, _bylaws, directors = setup_corporation_with_directors(5, name="Corp V")
    d1, d2, d3, d4, d5 = directors
    m = setup_in_session_meeting(
        corp["id"], d1["id"], [d["id"] for d in directors]
    )
    r_ord = create_meeting_resolution(
        corp["id"], m["id"], resolution_type="ORDINARY", title="Ordinary item", text="Ordinary text"
    )
    r_spec = create_meeting_resolution(
        corp["id"], m["id"], resolution_type="SPECIAL", title="Special item", text="Special text"
    )
    for r in (r_ord, r_spec):
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        cast_ballot(r["id"], d1["id"], "FOR")
        cast_ballot(r["id"], d2["id"], "FOR")
        cast_ballot(r["id"], d3["id"], "AGAINST")
        cast_ballot(r["id"], d4["id"], "ABSTAIN")
        cast_ballot(r["id"], d5["id"], "RECUSED")
    return corp, d1, m, r_ord, r_spec


class TestDualVariantVoteOutcome:
    """Difficulty instance: vote_outcome_present_and_voting_vs_full_board_majority."""

    def test_ordinary_present_and_voting_adopted(self, api):
        """PRD §3.6: "An `ORDINARY` resolution follows the present-and-voting
        variant and is adopted if and only if twice its `for_count` strictly
        exceeds the sum of `for_count` and `against_count` — abstentions,
        recusals, and absent directors enter no denominator."

        With for=2, against=1: 2*2=4 > 2+1=3, so ADOPTED.

        Design: Difficulty/dual_variant_calc/vote_outcome_present_and_voting_vs_full_board_majority
        """
        _corp, d1, _m, r_ord, _r_spec = _setup_two_open_votes(api)
        data = close_vote_as_chair(r_ord["id"], d1["id"])
        assert data["status"] == "ADOPTED", (
            f"expected ADOPTED under present-and-voting, got {data['status']}"
        )
        assert data["for_count"] == 2
        assert data["against_count"] == 1

    def test_special_full_board_majority_rejected(self, api):
        """PRD §3.6: "A `SPECIAL` resolution follows the full-board-majority
        variant and is adopted if and only if its `for_count` reaches at least
        the integer floor of half the eligible pool plus one — here abstentions
        and absentees weigh against adoption."

        Eligible pool = 5 (no recusal disclosures), floor(5/2)+1 = 3 FOR needed;
        only 2 FOR, so REJECTED.

        Design: Difficulty/dual_variant_calc/vote_outcome_present_and_voting_vs_full_board_majority
        """
        _corp, d1, _m, _r_ord, r_spec = _setup_two_open_votes(api)
        data = close_vote_as_chair(r_spec["id"], d1["id"])
        assert data["status"] == "REJECTED", (
            f"expected REJECTED under full-board-majority (need 3 FOR), got {data['status']}"
        )
        assert data["for_count"] == 2
