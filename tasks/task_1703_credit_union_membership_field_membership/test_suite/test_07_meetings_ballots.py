"""Annual meetings: scheduling gaps, ballot windows and eligibility, quorum
tallying, and the adjourn-reconvene chain."""
from test_helpers import (
    ApiErrorId,
    assert_annual_meeting,
    assert_ballot,
    cast_ballot,
    close_and_tally,
    create_ballot_payload,
    create_meeting,
    create_meeting_payload,
    create_member,
    make_member_headers,
    reconvene,
    set_clock,
    setup_charter,
    setup_voters,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_director_headers"]
FILER = TEST_USERS["membership_officer_headers"]


def _three_voters_with_meeting(api, quorum_threshold=3):
    """Three members approved 2026-07-01 (effective <= record_date 2026-07-05)
    plus a meeting: record 2026-07-05, voting open 2026-07-10, meeting
    2026-07-20."""
    set_clock("2026-07-01")
    _charter, _seg, members = setup_voters(
        3, names=["Voter Ava", "Voter Ben", "Voter Cy"])
    meeting = create_meeting(quorum_threshold=quorum_threshold)
    return meeting, members


class TestQuorumBoundary:
    def test_quorum_exactly_at_threshold_is_met(self, api):
        """PRD §3.8: "When that count is at least the `quorum_threshold` — the
        exact boundary meets quorum — the meeting closes HELD with
        `quorum_met` recorded true; when it falls short, the meeting closes
        ADJOURNED_NO_QUORUM with `quorum_met` false, which is a recorded
        outcome rather than an error."

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_threshold_is_met
        """
        meeting, (m_a, m_b, m_c) = _three_voters_with_meeting(api, 3)
        set_clock("2026-07-15")
        cast_ballot(meeting["id"], m_a, "FOR_SLATE_A")
        cast_ballot(meeting["id"], m_b, "ABSTAIN")
        cast_ballot(meeting["id"], m_c, "FOR_SLATE_B")

        set_clock("2026-07-20")
        tallied = validate_success(api.close_and_tally(meeting["id"], BOARD))
        assert_annual_meeting(tallied)
        assert tallied["ballots_counted"] == 3, (
            "Three distinct chain voters exactly equal quorum_threshold 3")
        assert tallied["quorum_met"] is True, "The >= boundary meets quorum"
        assert tallied["status"] == "HELD"

    def test_quorum_boundary_tally_snapshot_by_choice(self, api):
        """PRD §3.8: "Either way the tally snapshot is written to the tallied
        meeting: `ballots_counted` set to the distinct-voter count,
        `votes_for_slate_a` and `votes_for_slate_b` holding the chain-wide
        counts of each slate's ballots, and `votes_abstain` holding the
        abstentions, which count toward quorum but toward neither slate."

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_threshold_is_met
        """
        meeting, (m_a, m_b, m_c) = _three_voters_with_meeting(api, 3)
        set_clock("2026-07-15")
        cast_ballot(meeting["id"], m_a, "FOR_SLATE_A")
        cast_ballot(meeting["id"], m_b, "ABSTAIN")
        cast_ballot(meeting["id"], m_c, "FOR_SLATE_B")

        set_clock("2026-07-20")
        tallied = validate_success(api.close_and_tally(meeting["id"], BOARD))
        assert tallied["votes_for_slate_a"] == 1
        assert tallied["votes_for_slate_b"] == 1
        assert tallied["votes_abstain"] == 1, (
            "ABSTAIN counts toward quorum but toward neither slate")


class TestAdjournReconveneCycle:
    def _setup_adjourned(self, api):
        """Two of three eligible voters cast on M1 (quorum 3); tally adjourns
        it. Returns (meeting, members)."""
        meeting, members = _three_voters_with_meeting(api, 3)
        set_clock("2026-07-15")
        cast_ballot(meeting["id"], members[0], "FOR_SLATE_A")
        cast_ballot(meeting["id"], members[1], "FOR_SLATE_B")
        set_clock("2026-07-20")
        return meeting, members

    def test_meeting_adjourns_then_reconvene_spawns_successor(self, api):
        """PRD §3.8: "when it falls short, the meeting closes
        ADJOURNED_NO_QUORUM with `quorum_met` false, which is a recorded
        outcome rather than an error."
        PRD §3.8: "reconvening an ADJOURNED_NO_QUORUM meeting — any other state
        fails with `ERR_MEETING_INVALID_STATE` — creates a brand-new
        AnnualMeeting in SCHEDULED whose `reconvened_from_id` points at the
        adjourned meeting and which inherits its `record_date` and
        `quorum_threshold`, while the caller supplies a fresh `meeting_date`
        and `voting_open_date` and the thirty-day spacing rule is waived inside
        the chain."

        Design: Difficulty/non_linear_state_machine/meeting_adjourn_reconvene_chain_cycle
        """
        meeting, members = self._setup_adjourned(api)
        tallied = close_and_tally(meeting["id"])
        assert tallied["status"] == "ADJOURNED_NO_QUORUM"
        assert tallied["quorum_met"] is False
        assert tallied["ballots_counted"] == 2, "2 distinct voters < quorum 3"

        successor = validate_success(api.reconvene_meeting(
            meeting["id"],
            {"meeting_date": "2026-07-25", "voting_open_date": "2026-07-16"},
            BOARD), 201)
        assert_annual_meeting(successor)
        assert successor["id"] != meeting["id"]
        assert successor["reconvened_from_id"] == meeting["id"]
        assert successor["status"] == "SCHEDULED", "The chain cycle re-enters"
        assert successor["record_date"] == "2026-07-05", "Inherited"
        assert successor["quorum_threshold"] == 3, "Inherited"
        # 2026-07-25 is only five days after the adjourned meeting's 2026-07-20
        # date: inside the chain the thirty-day spacing rule is waived.

    def test_reconvened_meeting_tallies_chain_to_held(self, api):
        """PRD §3.8: "Ballots cast anywhere in the chain count toward the
        successor's quorum and tallies, so the chain loops — adjourn,
        reconvene, tally again — until quorum is finally met."
        PRD §3.8: "Closing the vote is a `BoardDirector` act that tallies the
        whole chain — the meeting itself plus every meeting reachable by
        following `reconvened_from_id` links backwards."

        Design: Difficulty/non_linear_state_machine/meeting_adjourn_reconvene_chain_cycle
        """
        meeting, members = self._setup_adjourned(api)
        close_and_tally(meeting["id"])
        successor = reconvene(meeting["id"])

        # The third member casts on the successor on 2026-07-20, inside the
        # successor's window [2026-07-16, 2026-07-25].
        accepted = validate_success(api.cast_ballot(
            create_ballot_payload(successor["id"], choice="FOR_SLATE_A"),
            make_member_headers(members[2])), 201)
        assert_ballot(accepted)
        assert accepted["cast_date"] == "2026-07-20"

        set_clock("2026-07-25")
        tallied = validate_success(api.close_and_tally(successor["id"], BOARD))
        assert tallied["status"] == "HELD"
        assert tallied["quorum_met"] is True
        assert tallied["ballots_counted"] == 3, (
            "The two ballots cast on the adjourned meeting remain live in the "
            "chain")
        assert tallied["votes_for_slate_a"] == 2
        assert tallied["votes_for_slate_b"] == 1


class TestChainVoterConservation:
    def _setup_adjourned(self, api):
        """Ava (FOR_SLATE_A) and Ben (ABSTAIN) cast on M1 (quorum 3); the tally
        adjourns it."""
        meeting, members = _three_voters_with_meeting(api, 3)
        set_clock("2026-07-15")
        cast_ballot(meeting["id"], members[0], "FOR_SLATE_A")
        cast_ballot(meeting["id"], members[1], "ABSTAIN")
        set_clock("2026-07-20")
        tallied = close_and_tally(meeting["id"])
        assert tallied["status"] == "ADJOURNED_NO_QUORUM"
        return meeting, members

    def test_chain_duplicate_rejected_and_adjourned_snapshot_immutable(self, api):
        """PRD §3.8: "One member, one ballot, per reconvene chain: a member who
        has already cast on any meeting of the chain is rejected with
        `ERR_BALLOT_ALREADY_CAST_IN_CHAIN`."
        PRD §3.8: "The snapshot is immutable — later reconvenes never rewrite
        it"

        Design: Difficulty/compensating_invariant/adjourn_reconvene_conserves_distinct_voter_count
        """
        meeting, members = self._setup_adjourned(api)
        successor = reconvene(meeting["id"])

        dup = api.cast_ballot(
            create_ballot_payload(successor["id"], choice="FOR_SLATE_B"),
            make_member_headers(members[0]))
        validate_error(dup, ApiErrorId.ERR_BALLOT_ALREADY_CAST_IN_CHAIN)

        original = validate_success(api.get_annual_meeting(meeting["id"],
                                                           BOARD))
        assert original["status"] == "ADJOURNED_NO_QUORUM"
        assert original["ballots_counted"] == 2, (
            "The adjourned meeting's snapshot is not rewritten by the "
            "reconvene or the rejected ballot")

    def test_chain_tally_counts_each_member_exactly_once(self, api):
        """PRD §3.8: "The distinct-voter count is the number of distinct
        `member_id` values across all ballots cast on any meeting in the chain;
        because ballots are immutable, no status filtering applies."

        Design: Difficulty/compensating_invariant/adjourn_reconvene_conserves_distinct_voter_count
        """
        meeting, members = self._setup_adjourned(api)
        successor = reconvene(meeting["id"])

        dup = api.cast_ballot(
            create_ballot_payload(successor["id"], choice="FOR_SLATE_B"),
            make_member_headers(members[0]))
        validate_error(dup, ApiErrorId.ERR_BALLOT_ALREADY_CAST_IN_CHAIN)

        cast_ballot(successor["id"], members[2], "FOR_SLATE_A")

        set_clock("2026-07-25")
        tallied = validate_success(api.close_and_tally(successor["id"], BOARD))
        assert tallied["status"] == "HELD"
        assert tallied["ballots_counted"] == 3, (
            "2 carried + 1 new, zero duplicates: the distinct-voter count is "
            "conserved")
        assert tallied["votes_for_slate_a"] == 2
        assert tallied["votes_abstain"] == 1


class TestMeetingSpacing:
    def test_meeting_29_days_apart_rejected(self, api):
        """PRD §3.8: "Scheduling also observes a thirty-day spacing rule: a new
        meeting fewer than thirty days from another SCHEDULED or HELD meeting
        outside its reconvene chain is rejected with `ERR_MEETING_TOO_CLOSE`,
        while a gap of exactly thirty days is permitted and meetings within the
        same chain are exempt entirely."

        Design: Difficulty/resource_temporal_overlap/meeting_minimum_gap_strict_vs_exact_30_days
        """
        set_clock("2026-08-01")
        create_meeting(meeting_date="2026-09-15", record_date="2026-08-20",
                       voting_open_date="2026-08-25")

        resp = api.create_annual_meeting(
            create_meeting_payload(meeting_date="2026-10-14",
                                   record_date="2026-09-20",
                                   voting_open_date="2026-09-25"),
            BOARD)
        validate_error(resp, ApiErrorId.ERR_MEETING_TOO_CLOSE)

    def test_meeting_exactly_30_days_apart_accepted(self, api):
        """PRD §3.8: "a new meeting fewer than thirty days from another
        SCHEDULED or HELD meeting outside its reconvene chain is rejected with
        `ERR_MEETING_TOO_CLOSE`, while a gap of exactly thirty days is
        permitted and meetings within the same chain are exempt entirely."

        Design: Difficulty/resource_temporal_overlap/meeting_minimum_gap_strict_vs_exact_30_days
        """
        set_clock("2026-08-01")
        create_meeting(meeting_date="2026-09-15", record_date="2026-08-20",
                       voting_open_date="2026-08-25")

        third = validate_success(api.create_annual_meeting(
            create_meeting_payload(meeting_date="2026-10-15",
                                   record_date="2026-09-20",
                                   voting_open_date="2026-09-25"),
            BOARD), 201)
        assert third["status"] == "SCHEDULED", (
            "2026-10-15 is exactly thirty days after 2026-09-15; the boundary "
            "is permitted")


class TestMeetingAndBallotStateRules:
    def test_meeting_double_tally_rejected(self, api):
        """PRD §3.8: "The snapshot is immutable — later reconvenes never
        rewrite it — and tallying a meeting that is not SCHEDULED fails with
        `ERR_MEETING_INVALID_STATE`."

        Design: Corner/state_machines/meeting_double_tally_rejected
        """
        meeting, members = _three_voters_with_meeting(api, 1)
        set_clock("2026-07-15")
        cast_ballot(meeting["id"], members[0], "FOR_SLATE_A")
        set_clock("2026-07-20")
        tallied = close_and_tally(meeting["id"])
        assert tallied["status"] == "HELD"
        assert tallied["ballots_counted"] == 1

        resp = api.close_and_tally(meeting["id"], BOARD)
        validate_error(resp, ApiErrorId.ERR_MEETING_INVALID_STATE)

    def test_ballot_on_adjourned_meeting_rejected(self, api):
        """PRD §3.8: "Checks run meeting-first: casting against a meeting that
        is not SCHEDULED fails with `ERR_MEETING_INVALID_STATE`"
        PRD §3.8: "An adjourned meeting is terminal for voting but fertile"

        Design: Corner/state_machines/ballot_on_adjourned_meeting_rejected
        """
        set_clock("2026-07-01")
        _charter, seg, members = setup_voters(1, names=["Late Voter"])
        meeting = create_meeting(quorum_threshold=1)

        set_clock("2026-07-20")
        tallied = close_and_tally(meeting["id"])
        assert tallied["status"] == "ADJOURNED_NO_QUORUM", "0 < quorum 1"

        resp = api.cast_ballot(
            create_ballot_payload(meeting["id"], choice="FOR_SLATE_A"),
            make_member_headers(members[0]))
        validate_error(resp, ApiErrorId.ERR_MEETING_INVALID_STATE)

    def test_meeting_date_ordering_rule(self, api):
        """PRD §3.8: "The dates must order correctly: the `record_date`
        strictly before the `voting_open_date`, and the `voting_open_date` on
        or before the `meeting_date`; any violation fails with
        `ERR_DATE_ORDER_INVALID`."

        Design: Corner/validations/meeting_date_ordering_rule
        """
        resp = api.create_annual_meeting(
            create_meeting_payload(meeting_date="2026-09-15",
                                   record_date="2026-08-20",
                                   voting_open_date="2026-08-10"),
            BOARD)
        validate_error(resp, ApiErrorId.ERR_DATE_ORDER_INVALID)


class TestBallotEligibilityAndWindow:
    def test_voting_window_bounds(self, api):
        """PRD §3.8: "Ballots are accepted only within the voting window from
        `voting_open_date` through `meeting_date`, both days inclusive; a cast
        outside it fails with `ERR_VOTING_WINDOW_CLOSED`."

        Design: Corner/validations/voting_window_bounds
        """
        set_clock("2026-07-01")
        _charter, _seg, (m1, m2) = setup_voters(
            2, names=["Window Wendy", "Window Wade"])
        meeting = create_meeting(quorum_threshold=1)

        set_clock("2026-07-09")
        early = api.cast_ballot(
            create_ballot_payload(meeting["id"], choice="FOR_SLATE_A"),
            make_member_headers(m1))
        validate_error(early, ApiErrorId.ERR_VOTING_WINDOW_CLOSED)

        set_clock("2026-07-20")
        ballot = validate_success(api.cast_ballot(
            create_ballot_payload(meeting["id"], choice="FOR_SLATE_A"),
            make_member_headers(m1)), 201)
        assert_ballot(ballot)
        assert ballot["member_id"] == m1, (
            "The ballot is attributed to the caller")
        assert ballot["cast_date"] == "2026-07-20", (
            "Casting on the meeting day itself is inside the window")

        set_clock("2026-07-21")
        late = api.cast_ballot(
            create_ballot_payload(meeting["id"], choice="FOR_SLATE_B"),
            make_member_headers(m2))
        validate_error(late, ApiErrorId.ERR_VOTING_WINDOW_CLOSED)

    def test_voter_record_date_cutoff(self, api):
        """PRD §3.8: "the member must be ACTIVE and their
        `membership_effective_date` must be on or before the meeting's
        `record_date`, and failing either condition yields
        `ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE`."

        Design: Corner/validations/voter_record_date_cutoff
        """
        set_clock("2026-07-01")
        _charter, seg_ids = setup_charter()
        meeting = create_meeting(quorum_threshold=1)

        set_clock("2026-07-10")
        member_id = create_member(segment_id=seg_ids[0], name="Newbie Ned")

        set_clock("2026-07-15")
        resp = api.cast_ballot(
            create_ballot_payload(meeting["id"], choice="FOR_SLATE_A"),
            make_member_headers(member_id))
        # Effective 2026-07-10 is after record_date 2026-07-05: ACTIVE but not
        # in the frozen electorate.
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE)

    def test_duplicate_ballot_same_meeting_rejected(self, api):
        """PRD §3.8: "One member, one ballot, per reconvene chain: a member who
        has already cast on any meeting of the chain is rejected with
        `ERR_BALLOT_ALREADY_CAST_IN_CHAIN`."

        Design: Corner/validations/duplicate_ballot_same_meeting_rejected
        """
        set_clock("2026-07-01")
        _charter, _seg, (m1,) = setup_voters(1, names=["Dup Dora"])
        meeting = create_meeting(quorum_threshold=1)

        set_clock("2026-07-15")
        cast_ballot(meeting["id"], m1, "FOR_SLATE_A")

        dup = api.cast_ballot(
            create_ballot_payload(meeting["id"], choice="FOR_SLATE_B"),
            make_member_headers(m1))
        validate_error(dup, ApiErrorId.ERR_BALLOT_ALREADY_CAST_IN_CHAIN)
