"""Motions, floor voting, recusal, tabling cycles, and vote integrity."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


class TestVoteIntegrity:
    def test_vote_records_immutable_and_duplicate_rejected(self, api):
        """PRD §3.5: "Each member votes at most once per motion
        (`ERR_DUPLICATE_VOTE`), and votes are immutable once recorded."
        PRD §2.5: "The one exception is the `Vote` record, which is append-only and
        immutable once recorded: it carries only `id` and `created_at`, and both
        `updated_at` and `version` are absent."

        Design: Corner/entities/vote_records_immutable_and_duplicate_rejected
        """
        sc = fx.setup_voting_scenario(num_members=2, category="GOVERNANCE",
                                      ein="EIN-VT-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        d1 = sc["members"][1]
        motion = sc["motion"]
        vote = fx.cast_vote(np_id, motion["id"], d1, "AYE")
        th.assert_vote(vote)

        th.validate_error(api.cast_vote(
            th.create_vote_payload(np_id, motion["id"], d1["id"], "NAY"),
            th.headers_for_member(d1)), th.ApiErrorId.ERR_DUPLICATE_VOTE)

        fetched = th.validate_success(api.get_vote(vote["id"], ADMIN))
        assert fetched["choice"] == "AYE", "the original vote record is unchanged"
        motion_after = th.validate_success(api.get_motion(motion["id"], ADMIN))
        assert motion_after["votes_for"] == 1
        assert motion_after["votes_against"] == 0


class TestVotingGates:
    def test_vote_on_introduced_motion_rejected(self, api):
        """PRD §3.5: "The motion must be `VOTING_OPEN` (`ERR_MOTION_NOT_OPEN`) and
        its meeting `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`)."

        Design: Corner/state_machines/vote_on_introduced_motion_rejected
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-VI-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        meeting = fx.setup_meeting_in_session(np_id, chair,
                                              [chair["id"], d1["id"]])
        motion = fx.introduce_motion(np_id, meeting["id"], chair, title="X",
                                     category="GOVERNANCE")  # never opened

        resp = api.cast_vote(
            th.create_vote_payload(np_id, motion["id"], d1["id"], "AYE"),
            th.headers_for_member(d1))
        th.validate_error(resp, th.ApiErrorId.ERR_MOTION_NOT_OPEN)

    def test_voter_outside_attendance_rejected(self, api):
        """PRD §3.5: "The voter must be eligible: an `ACTIVE` member, present on the
        meeting's persisted `attendance` roster, and — for a committee meeting —
        holding an `ACTIVE` appointment on that committee, else
        `ERR_VOTER_NOT_ELIGIBLE`."

        Design: Corner/state_machines/voter_outside_attendance_rejected
        """
        sc = fx.setup_org_with_board(num_directors=2, officers=("CHAIR",),
                                     ein="EIN-VE-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, d1, d2 = sc["chair"], sc["members"][1], sc["members"][2]
        meeting = fx.setup_meeting_in_session(np_id, chair,
                                              [chair["id"], d1["id"]])
        motion = fx.setup_open_motion(np_id, meeting["id"], chair,
                                      category="GOVERNANCE")

        resp = api.cast_vote(
            th.create_vote_payload(np_id, motion["id"], d2["id"], "AYE"),
            th.headers_for_member(d2))
        th.validate_error(resp, th.ApiErrorId.ERR_VOTER_NOT_ELIGIBLE)

    def test_motion_withdrawn_is_terminal(self, api):
        """PRD §3.5: "Withdrawal is available from `INTRODUCED` or `TABLED` and
        moves the motion to `WITHDRAWN`; withdrawing a bylaws motion also frees the
        amendment's motion link. `PASSED`, `FAILED`, and `WITHDRAWN` are terminal."
        PRD §2.7: "7. **State-machine from-state.** The target resource must be in a
        state from which the requested transition is allowed, else
        `ERR_INVALID_STATE` (409); this also covers transitions attempted on
        terminal resources and non-idempotent re-fires."

        Design: Corner/state_machines/motion_withdrawn_is_terminal
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-MW-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        meeting = fx.create_meeting(np_id, start="2026-08-02T10:00:00Z")
        motion = fx.introduce_motion(np_id, meeting["id"], chair, title="X",
                                     category="OTHER")
        withdrawn = th.validate_success(api.withdraw_motion(motion["id"], chair_headers))
        assert withdrawn["status"] == "WITHDRAWN"

        th.validate_error(api.open_voting(motion["id"], chair_headers),
                          th.ApiErrorId.ERR_INVALID_STATE)
        th.validate_error(api.table_motion(motion["id"], chair_headers),
                          th.ApiErrorId.ERR_INVALID_STATE)


class TestRecusal:
    def test_recused_member_must_vote_recused(self, api):
        """PRD §3.5: "Recusal is enforced, not advisory: a voter whose
        current-fiscal-year disclosure is `RESTRICTIONS_IMPOSED` with
        `restriction_categories` containing the motion's `category` must cast
        `RECUSED`, and any other choice is rejected with `ERR_MEMBER_RECUSED`."
        PRD §3.5: "After each cast the motion's tallies — `votes_for`,
        `votes_against`, `votes_abstain`, `votes_recused` — are recomputed from the
        vote rows, which, the record being append-only, makes every recount
        deterministic."

        Design: Corner/errors/recused_member_must_vote_recused
        """
        sc = fx.setup_org_with_board(num_directors=2, officers=("CHAIR",),
                                     ein="EIN-RMV-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, d1, reviewer = sc["chair"], sc["members"][1], sc["members"][2]
        # D1 files a conflicting FY2026 disclosure; reviewer files their own,
        # reviews D1's, and imposes FINANCE restrictions.
        d1_coi = fx.file_coi(np_id, d1, fiscal_year=2026,
                             answers=[{"question_key": "q_fin", "answer": True}])
        fx.file_coi(np_id, reviewer, fiscal_year=2026)
        th.validate_success(api.start_review(d1_coi["id"],
                                             th.headers_for_member(reviewer)))
        th.validate_success(api.impose_restrictions(
            d1_coi["id"], {"restriction_categories": ["FINANCE"]},
            th.headers_for_member(reviewer)))

        member_ids = [m["id"] for m in sc["members"]]
        meeting = fx.setup_meeting_in_session(np_id, chair, member_ids)
        motion = fx.setup_open_motion(np_id, meeting["id"], chair,
                                      title="Invest", category="FINANCE")

        resp = api.cast_vote(
            th.create_vote_payload(np_id, motion["id"], d1["id"], "AYE"),
            th.headers_for_member(d1))
        th.validate_error(resp, th.ApiErrorId.ERR_MEMBER_RECUSED)

        vote = fx.cast_vote(np_id, motion["id"], d1, "RECUSED")
        th.assert_vote(vote)
        motion_after = th.validate_success(api.get_motion(motion["id"], ADMIN))
        assert motion_after["votes_recused"] == 1
        assert motion_after["votes_for"] == 0


class TestMotionOutcomes:
    def test_motion_unanimous_abstain_kills(self, api):
        """PRD §3.5: "The required votes follow the `threshold`: a simple majority
        needs the basis halved and rounded down, plus one; a two-thirds threshold
        needs the ceiling of two-thirds of the basis — so a basis of five requires
        four; unanimity needs the full basis and additionally that no `NAY` and no
        `ABSTAIN` votes exist."
        PRD §3.5: "under `FULL_BOARD` it is the count of the nonprofit's `ACTIVE`
        members at close time minus the recusal count."
        PRD §3.5: "The motion passes when the `AYE` count is at least the
        requirement — equality passes — with the additional unanimous-condition
        applied for `UNANIMOUS`, and fails otherwise; the computed requirement is
        persisted as the motion's `required_votes`, which is null until close."

        Design: Corner/calculations/motion_unanimous_abstain_kills
        """
        sc = fx.setup_org_with_board(num_directors=3, officers=("CHAIR",),
                                     receipts=1_000_000, ein="EIN-UN-1")
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        members = sc["members"]
        member_ids = [m["id"] for m in members]
        meeting = fx.setup_meeting_in_session(np_id, chair, member_ids,
                                              duration=120)

        mo1 = fx.setup_open_motion(np_id, meeting["id"], chair, title="U1",
                                   category="GOVERNANCE", threshold="UNANIMOUS",
                                   threshold_basis="FULL_BOARD")
        mo2 = fx.introduce_motion(np_id, meeting["id"], chair, title="U2",
                                  category="GOVERNANCE", threshold="UNANIMOUS",
                                  threshold_basis="FULL_BOARD")
        for m, choice in zip(members, ("AYE", "AYE", "AYE", "ABSTAIN")):
            fx.cast_vote(np_id, mo1["id"], m, choice)
        closed1 = th.validate_success(api.close_voting(mo1["id"], chair_headers))
        assert closed1["required_votes"] == 4, (
            f"FULL_BOARD basis: 4 ACTIVE - 0 recused, got {closed1['required_votes']}")
        assert closed1["status"] == "FAILED", (
            "3 AYE + 1 ABSTAIN breaks unanimity even though 3 >= ... abstain kills")

        mo2 = th.validate_success(api.open_voting(mo2["id"], chair_headers))
        for m in members:
            fx.cast_vote(np_id, mo2["id"], m, "AYE")
        closed2 = th.validate_success(api.close_voting(mo2["id"], chair_headers))
        assert closed2["required_votes"] == 4
        assert closed2["status"] == "PASSED", (
            "4 AYE with zero NAY and zero ABSTAIN passes unanimously")

    def test_motion_two_thirds_ceil_boundary(self, api):
        """PRD §3.5: "The required votes follow the `threshold`: a simple majority
        needs the basis halved and rounded down, plus one; a two-thirds threshold
        needs the ceiling of two-thirds of the basis — so a basis of five requires
        four; unanimity needs the full basis and additionally that no `NAY` and no
        `ABSTAIN` votes exist."
        PRD §3.5: "under `PRESENT_AND_VOTING` the basis is the sum of `AYE` and
        `NAY` votes, with abstentions and recusals excluded"
        PRD §3.5: "The motion passes when the `AYE` count is at least the
        requirement — equality passes — with the additional unanimous-condition
        applied for `UNANIMOUS`, and fails otherwise; the computed requirement is
        persisted as the motion's `required_votes`, which is null until close."

        Design: Corner/calculations/motion_two_thirds_ceil_boundary
        """
        sc = fx.setup_org_with_board(num_directors=4, officers=("CHAIR",),
                                     bylaws={"board_size": 5}, receipts=1_000_000,
                                     ein="EIN-TT-1")
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        members = sc["members"]
        member_ids = [m["id"] for m in members]
        meeting = fx.setup_meeting_in_session(np_id, chair, member_ids,
                                              duration=120)

        mo1 = fx.setup_open_motion(np_id, meeting["id"], chair, title="T1",
                                   category="PERSONNEL", threshold="TWO_THIRDS")
        mo2 = fx.introduce_motion(np_id, meeting["id"], chair, title="T2",
                                  category="PERSONNEL", threshold="TWO_THIRDS")
        for m, choice in zip(members, ("AYE", "AYE", "AYE", "NAY", "NAY")):
            fx.cast_vote(np_id, mo1["id"], m, choice)
        closed1 = th.validate_success(api.close_voting(mo1["id"], chair_headers))
        assert closed1["required_votes"] == 4, (
            f"ceil(2/3 * 5) == 4 on PRESENT_AND_VOTING basis F+N=5, got {closed1['required_votes']}")
        assert closed1["status"] == "FAILED", "3 AYE < 4"

        mo2 = th.validate_success(api.open_voting(mo2["id"], chair_headers))
        for m, choice in zip(members, ("AYE", "AYE", "AYE", "AYE", "NAY")):
            fx.cast_vote(np_id, mo2["id"], m, choice)
        closed2 = th.validate_success(api.close_voting(mo2["id"], chair_headers))
        assert closed2["required_votes"] == 4
        assert closed2["status"] == "PASSED", "4 AYE == required 4 passes on equality"


class TestTableResumeCycle:
    """Difficulty: non_linear_state_machine / motion_table_resume_cycle_preserves_votes."""

    def test_table_then_resume_preserves_pre_table_vote(self, api):
        """PRD §3.5: "Tabling is available from `INTRODUCED` or `VOTING_OPEN`;
        resuming returns a `TABLED` motion to `VOTING_OPEN` and likewise requires
        the meeting to be in session — the `VOTING_OPEN`-to-`TABLED`-to-`VOTING_OPEN`
        cycle is the normal way business survives an adjournment,
        since adjournment tables everything left open."
        PRD §3.5: "After each cast the motion's tallies — `votes_for`,
        `votes_against`, `votes_abstain`, `votes_recused` — are recomputed from the
        vote rows, which, the record being append-only, makes every recount
        deterministic."

        Design: Difficulty/non_linear_state_machine/motion_table_resume_cycle_preserves_votes
        """
        sc = fx.setup_voting_scenario(num_members=3, category="GOVERNANCE",
                                      ein="EIN-CYC-1")
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        chair_headers = th.make_board_chair_headers(chair["id"])
        motion = sc["motion"]
        fx.cast_vote(np_id, motion["id"], d1, "AYE")

        tabled = th.validate_success(api.table_motion(motion["id"], chair_headers))
        assert tabled["status"] == "TABLED"
        assert tabled["votes_for"] == 1, "the pre-table AYE survives the table loop"

        resumed = th.validate_success(api.resume_motion(motion["id"], chair_headers))
        assert resumed["status"] == "VOTING_OPEN", (
            "the cyclic edge TABLED -> VOTING_OPEN returns the motion to the floor")

    def test_resume_then_close_counts_pre_table_vote(self, api):
        """PRD §3.5: "under `PRESENT_AND_VOTING` the basis is the sum of `AYE` and
        `NAY` votes, with abstentions and recusals excluded"
        PRD §3.5: "a simple majority needs the basis halved and rounded down, plus
        one"
        PRD §3.5: "The motion passes when the `AYE` count is at least the
        requirement — equality passes — with the additional unanimous-condition
        applied for `UNANIMOUS`, and fails otherwise; the computed requirement is
        persisted as the motion's `required_votes`, which is null until close."

        Design: Difficulty/non_linear_state_machine/motion_table_resume_cycle_preserves_votes
        """
        sc = fx.setup_voting_scenario(num_members=3, category="GOVERNANCE",
                                      ein="EIN-CYC-2")
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        chair_headers = th.make_board_chair_headers(chair["id"])
        motion = sc["motion"]
        fx.cast_vote(np_id, motion["id"], d1, "AYE")
        th.validate_success(api.table_motion(motion["id"], chair_headers))
        th.validate_success(api.resume_motion(motion["id"], chair_headers))

        fx.cast_vote(np_id, motion["id"], chair, "AYE")
        closed = th.validate_success(api.close_voting(motion["id"], chair_headers))
        # basis = 2 AYE + 0 NAY -> floor(2/2)+1 == 2; 2 >= 2 passes
        assert closed["required_votes"] == 2
        assert closed["votes_for"] == 2
        assert closed["status"] == "PASSED"


class TestMeetingSessionGate:
    """Difficulty: cross_entity_state_dependency / motion_voting_gated_by_meeting_session."""

    def test_open_voting_blocked_until_meeting_in_session(self, api):
        """PRD §3.5: "Opening voting requires an `INTRODUCED` motion whose meeting
        is `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`) and moves the motion to
        `VOTING_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/motion_voting_gated_by_meeting_session
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-GATE-1")
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        chair_headers = th.make_board_chair_headers(chair["id"])
        meeting = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z")
        motion = fx.introduce_motion(np_id, meeting["id"], chair, title="Retreat",
                                     category="GOVERNANCE")

        resp = api.open_voting(motion["id"], chair_headers)
        th.validate_error(resp, th.ApiErrorId.ERR_MEETING_NOT_IN_SESSION)

    def test_open_voting_succeeds_after_call_to_order(self, api):
        """PRD §3.5: "Opening voting requires an `INTRODUCED` motion whose meeting
        is `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`) and moves the motion to
        `VOTING_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/motion_voting_gated_by_meeting_session
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-GATE-1B")
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        chair_headers = th.make_board_chair_headers(chair["id"])
        meeting = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z")
        motion = fx.introduce_motion(np_id, meeting["id"], chair, title="Retreat",
                                     category="GOVERNANCE")
        fx.call_to_order(meeting["id"], chair, [chair["id"], d1["id"]])

        opened = th.validate_success(api.open_voting(motion["id"], chair_headers))
        assert opened["status"] == "VOTING_OPEN"


class TestClosedMotionPriorityPair:
    """Difficulty: priority_pair_validation_conflict / closed_motion_referential_beats_recusal_safety."""

    def _setup_closed_finance_motion_with_recused_member(self, api):
        sc = fx.setup_org_with_board(num_directors=2, officers=("CHAIR",),
                                     ein="EIN-PRIO-1")
        np_id = sc["nonprofit"]["id"]
        chair, d1, reviewer = sc["chair"], sc["members"][1], sc["members"][2]
        chair_headers = th.make_board_chair_headers(chair["id"])
        d1_coi = fx.file_coi(np_id, d1, fiscal_year=2026,
                             answers=[{"question_key": "q_fin", "answer": True}])
        fx.file_coi(np_id, reviewer, fiscal_year=2026)
        th.validate_success(api.start_review(d1_coi["id"],
                                             th.headers_for_member(reviewer)))
        th.validate_success(api.impose_restrictions(
            d1_coi["id"], {"restriction_categories": ["FINANCE"]},
            th.headers_for_member(reviewer)))
        member_ids = [m["id"] for m in sc["members"]]
        meeting = fx.setup_meeting_in_session(np_id, chair, member_ids)
        motion = fx.setup_open_motion(np_id, meeting["id"], chair,
                                      title="Investment policy", category="FINANCE")
        return sc, chair_headers, meeting, motion

    def test_zero_aye_close_fails_on_empty_present_and_voting_basis(self, api):
        """PRD §3.5: "under `PRESENT_AND_VOTING` the basis is the sum of `AYE` and
        `NAY` votes, with abstentions and recusals excluded"
        PRD §3.5: "a simple majority needs the basis halved and rounded down, plus
        one"
        PRD §3.5: "The motion passes when the `AYE` count is at least the
        requirement — equality passes — with the additional unanimous-condition
        applied for `UNANIMOUS`, and fails otherwise; the computed requirement is
        persisted as the motion's `required_votes`, which is null until close."

        Design: Difficulty/priority_pair_validation_conflict/closed_motion_referential_beats_recusal_safety
        """
        sc, chair_headers, _meeting, motion = (
            self._setup_closed_finance_motion_with_recused_member(api))
        closed = th.validate_success(api.close_voting(motion["id"], chair_headers))
        # empty basis F+N == 0 -> floor(0/2)+1 == 1; 0 AYE < 1 -> FAILED
        assert closed["required_votes"] == 1
        assert closed["status"] == "FAILED"
        assert closed["votes_for"] == 0

    def test_closed_motion_referential_error_beats_recusal(self, api):
        """PRD §2.7: "When a request fails several rules at once, the error the
        caller receives is determined by a fixed order of precedence, evaluated from
        first to last:"
        PRD §2.7: "9. **Cross-entity state gates.** Business referential gates such
        as an adopted-bylaws requirement, an in-session meeting requirement, or
        amendment linkage rules — `ERR_BYLAWS_NOT_ADOPTED`,
        `ERR_MEETING_NOT_IN_SESSION`, `ERR_MOTION_NOT_OPEN`,
        `ERR_COMMITTEE_NOT_ACTIVE`, `ERR_AMENDMENT_NOT_PROPOSED`,
        `ERR_AMENDMENT_HAS_OPEN_MOTION`, `ERR_VOTER_NOT_ELIGIBLE` — each a 409
        detailed in §3."
        PRD §2.7: "11. **Recusal.** A recused member attempting a non-recused vote
        is rejected with `ERR_MEMBER_RECUSED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/closed_motion_referential_beats_recusal_safety
        """
        sc, chair_headers, _meeting, motion = (
            self._setup_closed_finance_motion_with_recused_member(api))
        np_id = sc["nonprofit"]["id"]
        d1 = sc["members"][1]
        th.validate_success(api.close_voting(motion["id"], chair_headers))

        # D1 is recused on FINANCE AND the motion is closed; rule 9 precedes rule 11
        resp = api.cast_vote(
            th.create_vote_payload(np_id, motion["id"], d1["id"], "AYE"),
            th.headers_for_member(d1))
        th.validate_error(resp, th.ApiErrorId.ERR_MOTION_NOT_OPEN)

        motion_after = th.validate_success(api.get_motion(motion["id"], ADMIN))
        assert motion_after["votes_for"] == 0, "no vote row was recorded"


class TestVoteSelfService:
    def test_vote_as_another_member_forbidden(self, api):
        """PRD §2.1: "Two operations are strictly self-service: casting a vote and
        filing a conflict-of-interest disclosure both require the payload's
        `board_member_id` to equal the caller's `X-User-ID` — a director votes and
        discloses only as themself, and a mismatch is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/vote_as_another_member_forbidden
        """
        sc = fx.setup_voting_scenario(num_members=3, category="GOVERNANCE",
                                      ein="EIN-RB2-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        d1, d2 = sc["members"][1], sc["members"][2]
        motion = sc["motion"]

        resp = api.cast_vote(
            th.create_vote_payload(np_id, motion["id"], d2["id"], "AYE"),
            th.headers_for_member(d1))
        th.validate_error(resp, th.ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
