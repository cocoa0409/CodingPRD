"""Tier movement proposals: evidence rules, supersede-on-propose, and the
ratifiable-set invariant (PRD §3.4, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_second_window_screening,
    assert_tier_movement,
    convene_meeting,
    create_team_meeting,
    get_student,
    list_movements,
    propose_movement,
    propose_tier_movement_payload,
    ratify_movement,
    record_weekly_probes,
    setup_active_plan,
    setup_student_with_ratified_tier,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["team_lead_headers"]


class TestMovementEligibility:
    def test_tier2_to_tier3_via_progress_monitoring_path(self, api):
        """PRD §3.4: "Intensifying to `TIER_3` requires either a latest screening
        band of `TIER_3`, or a run in which the four most recent probes are all
        `NON_RESPONSIVE` while an `ACTIVE` plan is in place."

        The student's latest screening band is TIER_2 (raw 95 against cuts
        120/90), so the screening path cannot authorize the move; the
        progress-monitoring path does, because the four most recent probes on
        the ACTIVE plan are all NON_RESPONSIVE (flat scores under a rising
        aimline). Five probes are recorded so the four most recent all carry
        multi-probe trailing windows.

        Design: Difficulty/combinatorial_formula/tier_movement_eligibility_multi_input
        """
        ctx = setup_active_plan(api, tier="TIER_2", raw_score=95,
                                tier2_max_score=120, tier3_max_score=90,
                                probe_frequency="WEEKLY")
        record_weekly_probes(api, ctx, [95, 95, 96, 96, 96],
                             first_date="2026-08-12")

        resp = api.propose_tier_movement(
            ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
            propose_tier_movement_payload(
                "TIER_3", "four consecutive non-responsive probes at TIER_2",
                get_student(api, ctx["district"]["id"], ctx["school"]["id"],
                            ctx["student"]["id"])["version"]),
            LEAD)
        movement = validate_success(resp, 201)
        assert_tier_movement(movement)
        assert movement["status"] == "PROPOSED"
        assert movement["from_tier"] == "TIER_2"
        assert movement["to_tier"] == "TIER_3"

    def test_proposal_to_current_tier_rejected(self, api):
        """PRD §3.4: "Regardless of the student's current tier, proposing a move
        to the tier the student already occupies is incoherent and is rejected
        with `ERR_INVALID_TIER_MOVE`."

        Design: Difficulty/combinatorial_formula/tier_movement_eligibility_multi_input
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2")
        student = get_student(api, ctx["district"]["id"], ctx["school"]["id"],
                              ctx["student"]["id"])
        assert student["current_tier"] == "TIER_2"
        resp = api.propose_tier_movement(
            ctx["district"]["id"], ctx["school"]["id"], student["id"],
            propose_tier_movement_payload("TIER_2", "no-op move",
                                          student["version"]),
            LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIER_MOVE, 422)


class TestSupersedeOnPropose:
    def _setup_with_tier3_evidence(self, api):
        """Student ratified at TIER_2, then a WINTER window bands them TIER_3 so
        TIER_3 proposals are admissible."""
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2",
                                               raw_score=80)
        add_second_window_screening(api, ctx, raw_score=60)
        return ctx

    def test_new_proposal_supersedes_existing(self, api):
        """PRD §3.4: "The proposal captures `from_tier` from the student's
        `current_tier` at proposal time, starts life in `PROPOSED` status with
        `decided_at_meeting_id` still null, and supersedes any earlier proposals:
        every existing `PROPOSED` movement for the same student transitions to
        `SUPERSEDED` when the new one is created."

        Design: Difficulty/non_linear_state_machine/tier_movement_proposed_superseded_proposed_loop
        """
        ctx = self._setup_with_tier3_evidence(api)
        d_id, s_id, st_id = (ctx["district"]["id"], ctx["school"]["id"],
                             ctx["student"]["id"])
        mv1 = propose_movement(api, d_id, s_id, st_id, "TIER_3",
                               rationale="first proposal")
        assert mv1["status"] == "PROPOSED"
        assert mv1["decided_at_meeting_id"] is None
        assert mv1["from_tier"] == "TIER_2"

        mv2 = propose_movement(api, d_id, s_id, st_id, "TIER_3",
                               rationale="second proposal — supersedes first")
        assert mv2["status"] == "PROPOSED"

        mv1_after = validate_success(api.get_tier_movement(
            d_id, s_id, st_id, mv1["id"], LEAD))
        assert mv1_after["status"] == "SUPERSEDED", (
            "the second write forces the first proposal into SUPERSEDED")

    def test_superseded_movement_is_not_ratifiable(self, api):
        """PRD §3.7: "Three preconditions guard the act, and their failure is
        rejected as `ERR_INVALID_STATE` (HTTP 409): the meeting must be
        `CONVENED`, the movement must still be `PROPOSED`, and no other
        `PROPOSED` movement for the same student may have been created later than
        this one — a later proposal supersedes earlier ones, so only the freshest
        proposal for a student is ever ratifiable."

        Design: Difficulty/non_linear_state_machine/tier_movement_proposed_superseded_proposed_loop
        """
        ctx = self._setup_with_tier3_evidence(api)
        d_id, s_id, st_id = (ctx["district"]["id"], ctx["school"]["id"],
                             ctx["student"]["id"])
        mv1 = propose_movement(api, d_id, s_id, st_id, "TIER_3",
                               rationale="first proposal")
        mv2 = propose_movement(api, d_id, s_id, st_id, "TIER_3",
                               rationale="second proposal")
        meeting = create_team_meeting(api, d_id, s_id, scheduled_on="2026-12-20")
        convene_meeting(api, d_id, s_id, meeting["id"])

        student = get_student(api, d_id, s_id, st_id)
        resp = api.ratify_movement(
            d_id, s_id, meeting["id"],
            {"movement_id": mv1["id"],
             "expected_student_version": student["version"]},
            LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        ratified = ratify_movement(api, d_id, s_id, meeting["id"], mv2["id"],
                                   st_id)
        assert ratified["status"] == "RATIFIED"
        assert get_student(api, d_id, s_id, st_id)["current_tier"] == "TIER_3"


class TestProposedCountConservation:
    def test_proposed_count_conserved_across_supersede(self, api):
        """PRD §3.4: "The proposal captures `from_tier` from the student's
        `current_tier` at proposal time, starts life in `PROPOSED` status with
        `decided_at_meeting_id` still null, and supersedes any earlier proposals:
        every existing `PROPOSED` movement for the same student transitions to
        `SUPERSEDED` when the new one is created."

        The conserved quantity is the count of PROPOSED movements per student:
        propose (+1) paired with propose (old -> SUPERSEDED, new +1) leaves the
        total at exactly 1.

        Design: Difficulty/compensating_invariant/student_tier_conservation_via_supersede
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2",
                                               raw_score=80)
        add_second_window_screening(api, ctx, raw_score=60)
        d_id, s_id, st_id = (ctx["district"]["id"], ctx["school"]["id"],
                             ctx["student"]["id"])

        mv1 = propose_movement(api, d_id, s_id, st_id, "TIER_3", "1st")
        proposed = list_movements(api, d_id, s_id, st_id, status="PROPOSED")
        assert [m["id"] for m in proposed] == [mv1["id"]]

        mv2 = propose_movement(api, d_id, s_id, st_id, "TIER_3", "2nd")
        proposed = list_movements(api, d_id, s_id, st_id, status="PROPOSED")
        assert [m["id"] for m in proposed] == [mv2["id"]], (
            "PROPOSED count is conserved at 1 across the propose+supersede pair")
        assert validate_success(api.get_tier_movement(
            d_id, s_id, st_id, mv1["id"], LEAD))["status"] == "SUPERSEDED"

    def test_supersede_chain_keeps_single_proposed(self, api):
        """PRD §3.4: "The proposal captures `from_tier` from the student's
        `current_tier` at proposal time, starts life in `PROPOSED` status with
        `decided_at_meeting_id` still null, and supersedes any earlier proposals:
        every existing `PROPOSED` movement for the same student transitions to
        `SUPERSEDED` when the new one is created."

        A chain of three proposals leaves the first two SUPERSEDED and exactly
        one PROPOSED.

        Design: Difficulty/compensating_invariant/student_tier_conservation_via_supersede
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2",
                                               raw_score=80)
        add_second_window_screening(api, ctx, raw_score=60)
        d_id, s_id, st_id = (ctx["district"]["id"], ctx["school"]["id"],
                             ctx["student"]["id"])

        mv1 = propose_movement(api, d_id, s_id, st_id, "TIER_3", "1st")
        mv2 = propose_movement(api, d_id, s_id, st_id, "TIER_3", "2nd")
        mv3 = propose_movement(api, d_id, s_id, st_id, "TIER_3", "3rd")

        statuses = {m["id"]: m["status"]
                    for m in list_movements(api, d_id, s_id, st_id)}
        assert statuses[mv1["id"]] == "SUPERSEDED"
        assert statuses[mv2["id"]] == "SUPERSEDED"
        assert statuses[mv3["id"]] == "PROPOSED"
        proposed = list_movements(api, d_id, s_id, st_id, status="PROPOSED")
        assert len(proposed) == 1 and proposed[0]["id"] == mv3["id"]
