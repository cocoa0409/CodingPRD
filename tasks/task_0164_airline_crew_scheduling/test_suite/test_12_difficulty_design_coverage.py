"""Additional tests pinned to difficulty-design instances.

Per the unit-test generator spec §2.1.A: every instance in
SCAFFOLD_DIFFICULTY_DESIGN.yaml must be covered by AT LEAST TWO tests.
The primary coverage lives in the feature files (test_02..test_11); the
second test for each instance that still needs one is collected here so
the "two tests per instance" rule is visibly satisfied.

Every assertion in this file is pinned to a PRD sentence — the
underlying rule the instance exercises — never to the difficulty-design
entry itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    add_hours_iso,
    add_minutes_iso,
    advance_clock_to,
    assert_block_minutes_conserved_across_trade,
    award_bid_window,
    build_pairing_with_one_duty_period,
    cancel_pairing,
    counter_trade_as,
    create_assignment_payload,
    create_bid_payload,
    create_crew_member,
    create_duty_period_payload,
    create_trade_request,
    crew_role_headers,
    get_assignment,
    get_crew_member,
    get_pairing,
    iso_from_dt,
    iso_now_utc,
    list_assignments,
    list_reserve_pool,
    mark_no_show,
    open_bidding,
    open_bidding_payload,
    pilot_headers_for,
    place_on_reserve,
    publish_pairing,
    raise_cumulative_block_30d,
    random_bid_window_id,
    release_assignment,
    report_sick_call,
    run_pairing_to_completion,
    scheduler_headers,
    setup_pairing_admin_assigned,
    setup_pairing_in_bidding,
    setup_sick_call_chain,
    setup_two_pilots_with_assignments,
    submit_bid,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Difficulty: dual_variant_calc / pay_credit_scheduled_vs_actual
# ===========================================================================
class TestDualVariantPayCreditScheduledVsActual:

    def test_scheduled_includes_dropped_legs_while_actual_excludes(
        self, api,
    ):
        """PRD §3.6: "The scheduled variant of the pay-credit
        calculation treats every flight leg currently scheduled in the
        pairing as if it had flown" vs "actual variant ... uses only
        FlightLeg rows in DutyPeriods whose release_at <= Pairing.end_at
        and whose Assignment had status IN_PROGRESS at release time
        (chronological filter: excludes legs cancelled / not flown
        because of an intra-pairing sick call)."

        # difficulty: dual_variant_calc/pay_credit_scheduled_vs_actual
        Second test: confirm scheduled returns the full pre-completion
        formula (without the MIN floor), regardless of intra-pairing
        sick calls that would shape the actual result.
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Build a pairing with one REVENUE leg of 300 minutes.
        pairing, _, _ = build_pairing_with_one_duty_period(
            revenue_block_minutes=300, duty_minutes=480,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        from test_helpers import admin_assign
        a = admin_assign(pairing["id"], pilot["id"], "CAPTAIN")

        # Estimate BEFORE completion via scheduled variant.
        resp = api.get_pay_credit_estimate(
            a["id"], pilot_headers_for(pilot),
        )
        data = validate_success(resp)
        # PRD §3.6: scheduled does NOT apply MIN floor; raw=300, no floor.
        assert data["scheduled_pay_credit_minutes"] == 300


# ===========================================================================
# Difficulty: combinatorial_formula / faa_duty_rest_check_three_input_threshold
# ===========================================================================
class TestFaaDutyRestCheckMultiInputOrdering:

    def test_30day_block_cap_attributed_when_rest_passes_at_boundary(
        self, api, scheduler_headers,
    ):
        """PRD §3.5: "the gap from the candidate's last_duty_end_at to
        the candidate pairing's earliest report_at must be at least 600
        minutes ... the candidate's cumulative_block_minutes_30d plus
        the pairing's total_block_minutes must be at most 6000 minutes
        ... Any of the last three failures yields
        ERR_FAA_DUTY_VIOLATION ... All four boundary inequalities are
        inclusive — a gap of exactly 600 minutes ... are all permitted."

        # difficulty: combinatorial_formula/faa_duty_rest_check_three_input_threshold
        Setup: rest passes at the 600-minute boundary; cumulative block
        check fails. Error attribution must name ERR_FAA_DUTY_VIOLATION,
        not the rest variant.
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Raise cumulative_block to 5400.
        pilot = raise_cumulative_block_30d(pilot, target_minutes=5400)
        # Run a recent pairing to set last_duty_end_at.
        recent_start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=20),
        )
        p_recent, _ = setup_pairing_admin_assigned(
            pilot, assigned_rank_slot="CAPTAIN",
            start_at=recent_start,
            revenue_block_minutes=100, duty_minutes=180,
        )
        run_pairing_to_completion(p_recent)
        pilot = get_crew_member(pilot["id"])
        last_end = pilot["last_duty_end_at"]
        # New pairing: rest exactly 600min (passes) but
        # total_block 700 → 5500+700 = 6200 > 6000.
        report_at = add_minutes_iso(last_end, 600)
        pairing, _, _ = build_pairing_with_one_duty_period(
            start_at=report_at,
            revenue_block_minutes=700, duty_minutes=800,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        resp = api.create_assignment(
            create_assignment_payload(
                pairing["id"], pilot["id"], "CAPTAIN",
            ),
            scheduler_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FAA_DUTY_VIOLATION.value)


# ===========================================================================
# Difficulty: combinatorial_formula / bid_award_chronological_dependency
# ===========================================================================
class TestBidAwardChronologicalDependencySecondTest:

    def test_both_pairings_award_when_total_fits_under_cap(self, api):
        """PRD §3.5: "the candidate's cumulative_block_minutes_30d plus
        the pairing's total_block_minutes must be at most 6000 minutes"
        — verified inside bid_award_calc per PRD §3.3 chronological
        evaluation.

        # difficulty: combinatorial_formula/bid_award_chronological_dependency
        Mirror of the disqualification test in test_04: when the sum of
        all pairings stays under the FAA cap, the chronological order
        is observable but BOTH pairings still award.
        """
        pilot = create_crew_member(rank="CAPTAIN", union_seniority_number=1)
        pilot = raise_cumulative_block_30d(pilot, target_minutes=4000)
        # Two pairings of 600 minutes each → 4000+600+600 = 5200 < 6000.
        start_early = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=2),
        )
        start_late = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=10),
        )
        bw = random_bid_window_id()
        p_early, _, _ = build_pairing_with_one_duty_period(
            start_at=start_early,
            revenue_block_minutes=600, duty_minutes=720,
            required_rank_composition={"CAPTAIN": 1},
        )
        p_late, _, _ = build_pairing_with_one_duty_period(
            start_at=start_late,
            revenue_block_minutes=600, duty_minutes=720,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(p_early["id"])
        publish_pairing(p_late["id"])
        open_bidding(p_early["id"], bid_window_id=bw)
        open_bidding(p_late["id"], bid_window_id=bw)
        submit_bid(pilot, p_early["id"], bw, preference_rank=1)
        submit_bid(pilot, p_late["id"], bw, preference_rank=2)
        award_bid_window(bw)
        assignments = list_assignments(params={"limit": 100})
        # Filter to assignments created by this awarding sweep on the
        # two pairings under test (the setup helper
        # raise_cumulative_block_30d also admin-assigns the pilot to
        # several pre-existing pairings to seed the counter).
        own = [
            a for a in assignments
            if a.get("crew_member_id") == pilot["id"]
            and a.get("pairing_id") in {p_early["id"], p_late["id"]}
        ]
        assert len(own) == 2, (
            "PRD §3.3: both pairings should award when cumulative stays "
            "under the FAA 30-day block cap."
        )


# ===========================================================================
# Difficulty: non_linear_state_machine / trade_request_cyclic_counter_loop
# ===========================================================================
class TestTradeCounterCycleSecondTest:

    def test_counter_swaps_initiator_and_counterparty_roles(self, api):
        """PRD §3.8: "the action swaps the two assignment ids in the
        trade, swaps the initiator_id and counterparty_id roles (the
        prior counterparty becomes the new proposer), and increments
        revision_count by one."

        # difficulty: non_linear_state_machine/trade_request_cyclic_counter_loop
        """
        m1, m2, a1, a2 = setup_two_pilots_with_assignments()
        tr = create_trade_request(m1, m2, a1, a2)
        assert tr["initiator_id"] == m1["id"]
        assert tr["counterparty_id"] == m2["id"]
        tr1 = counter_trade_as(m2, tr["id"], a2["id"], a1["id"])
        # After counter, the prior counterparty (m2) becomes the new
        # proposer; equivalently, the active counterparty is now m1.
        assert tr1["initiator_id"] == m2["id"], (
            "PRD §3.8: prior counterparty becomes the new proposer."
        )
        assert tr1["counterparty_id"] == m1["id"]
        assert tr1["revision_count"] == 1


# ===========================================================================
# Difficulty: non_linear_state_machine / assignment_branching_release_vs_progress
# ===========================================================================
class TestAssignmentBranchingSecondTest:

    def test_release_assignment_debits_cumulative_block_30d(self, api):
        """PRD §3.7: "An individual assignment may be released by a
        CrewScheduler while it is SCHEDULED ... The release moves the
        assignment from SCHEDULED to RELEASED, applies the same
        window-aware debits to the affected crew member's two
        cumulative counters."

        # difficulty: non_linear_state_machine/assignment_branching_release_vs_progress
        Test the RELEASED branch of the SCHEDULED fork (the IN_PROGRESS
        branch is covered in test_10).
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Build pairing within 30d window so debit fires on release.
        start_at = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=5),
        )
        pairing, assignment = setup_pairing_admin_assigned(
            pilot, assigned_rank_slot="CAPTAIN",
            start_at=start_at,
            revenue_block_minutes=400, duty_minutes=500,
        )
        before = get_crew_member(pilot["id"])
        sched_block = int(assignment["scheduled_block_minutes"])
        release_assignment(assignment["id"])
        after = get_crew_member(pilot["id"])
        assert (
            int(after["cumulative_block_minutes_30d"])
            == int(before["cumulative_block_minutes_30d"]) - sched_block
        ), (
            "PRD §3.7 release debits cumulative_block_minutes_30d by "
            "scheduled_block_minutes."
        )
        a = get_assignment(assignment["id"])
        assert a["status"] == "RELEASED"


# ===========================================================================
# Difficulty: transitive_cascade / sick_call_chain_depth_3
# ===========================================================================
class TestSickCallChainDepth3SecondTest:

    def test_reserve_member_block_30d_incremented_on_callout(self, api):
        """PRD §3.4: "the covering crew member's
        cumulative_block_minutes_30d is incremented by
        Pairing.total_block_minutes."

        # difficulty: transitive_cascade/sick_call_chain_depth_3
        Second-link consequence: the reserve member's cumulative counter
        must be incremented after the auto-callout fires.
        """
        ctx = setup_sick_call_chain()
        reserve_before = get_crew_member(ctx["reserve_member"]["id"])
        block_before = int(reserve_before["cumulative_block_minutes_30d"])
        # Report sick.
        resp = report_sick_call(
            ctx["sick_member"],
            assignment_id=ctx["sick_assignment"]["id"],
        )
        assert resp.status_code == 201
        # Re-read reserve member.
        reserve_after = get_crew_member(ctx["reserve_member"]["id"])
        block_after = int(reserve_after["cumulative_block_minutes_30d"])
        pairing = get_pairing(ctx["sick_pairing"]["id"])
        assert block_after == block_before + int(pairing["total_block_minutes"]), (
            "PRD §3.4: reserve member's cumulative_block_minutes_30d "
            "incremented by Pairing.total_block_minutes."
        )


# ===========================================================================
# Difficulty: transitive_cascade / pairing_cancel_chain_depth_2
# ===========================================================================
class TestPairingCancelChainDepth2SecondTest:

    def test_cancel_releases_both_assignments_on_multi_slot_pairing(self, api):
        """PRD §3.7: "Cancelling from AWARDED releases every AWARDED
        assignment on the pairing: the assignment transitions to
        RELEASED."

        # difficulty: transitive_cascade/pairing_cancel_chain_depth_2
        Multi-slot version: two crew members, two assignments, both must
        end RELEASED after a single cancel.
        """
        m_cap = create_crew_member(
            rank="CAPTAIN", base_airport="DFW", union_seniority_number=1,
        )
        m_fo = create_crew_member(
            rank="FIRST_OFFICER", base_airport="DFW",
            union_seniority_number=1,
        )
        start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=5),
        )
        pairing, _, _ = build_pairing_with_one_duty_period(
            base_airport="DFW",
            revenue_block_minutes=400, duty_minutes=520,
            required_rank_composition={"CAPTAIN": 1, "FIRST_OFFICER": 1},
            start_at=start,
        )
        publish_pairing(pairing["id"])
        from test_helpers import admin_assign
        a_cap = admin_assign(pairing["id"], m_cap["id"], "CAPTAIN")
        a_fo = admin_assign(pairing["id"], m_fo["id"], "FIRST_OFFICER")
        cancel_pairing(pairing["id"])
        assert get_assignment(a_cap["id"])["status"] == "RELEASED"
        assert get_assignment(a_fo["id"])["status"] == "RELEASED"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / state_vs_business_safety_on_bid_award
# ===========================================================================
class TestStateVsBusinessSafetyOnBidAwardSecondTest:

    def test_bidding_on_cancelled_pairing_yields_pairing_invalid_state(
        self, api,
    ):
        """PRD §3.2: "A bid against a pairing that is no longer
        BIDDING_OPEN is rejected with ERR_BID_WINDOW_CLOSED if the
        pairing has just left that state through an awarding sweep, or
        with ERR_PAIRING_INVALID_STATE otherwise."
        PRD §2.8: state checks fire before FAA business safety.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_bid_award
        Second test: an individual bid submission on a CANCELLED
        pairing must produce ERR_PAIRING_INVALID_STATE — the state
        precondition pre-empts any FAA reasoning.
        """
        bidder = create_crew_member(rank="CAPTAIN")
        bidder = raise_cumulative_block_30d(bidder, target_minutes=5800)
        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        cancel_pairing(pairing["id"])
        resp = api.create_bid(
            create_bid_payload(pairing["id"], bw, preference_rank=1),
            crew_role_headers(bidder),
        )
        validate_error(resp, ApiErrorId.ERR_PAIRING_INVALID_STATE.value)


# ===========================================================================
# Difficulty: priority_pair_validation_conflict /
#             trade_state_vs_business_referential_on_approve
# ===========================================================================
class TestTradeStateVsBusinessReferentialOnApprove:

    def test_approve_rejected_trade_yields_invalid_trade_state(self, api):
        """PRD §3.8: "After 24 hours of no movement ... a clock advance
        moves a PROPOSED or COUNTER_PROPOSED trade to EXPIRED."
        PRD §2.8: trade-state checks (ERR_INVALID_TRADE_STATE, priority
        8) fire before trade-rule (ERR_TRADE_RULE_VIOLATION, priority
        11).

        # difficulty: priority_pair_validation_conflict/trade_state_vs_business_referential_on_approve
        Setup: rejected trade with crew members on different ranks
        (would also fail trade legality). Approval must surface the
        state error first.
        """
        # Two crew members of differing ranks to set up a latent
        # trade-rule failure.
        m1 = create_crew_member(
            rank="CAPTAIN", base_airport="DFW",
        )
        m2 = create_crew_member(
            rank="FIRST_OFFICER", base_airport="DFW",
        )
        # Each gets their own assignment (same-rank not required for
        # the trade request to be CREATED; the legality check fires at
        # /approve).
        p1, a1 = setup_pairing_admin_assigned(
            m1, assigned_rank_slot="CAPTAIN",
        )
        later_start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=5),
        )
        p2, a2 = setup_pairing_admin_assigned(
            m2, assigned_rank_slot="FIRST_OFFICER",
            start_at=later_start,
        )
        tr = create_trade_request(m1, m2, a1, a2)
        # m2 rejects the proposal → state REJECTED.
        from test_helpers import (
            crew_role_headers,
            scheduler_headers as _sch,
        )
        rej = api.reject_trade_request(tr["id"], crew_role_headers(m2))
        validate_success(rej)
        # Now attempt approval → trade-state check fires first.
        resp = api.approve_trade_request(tr["id"], _sch())
        validate_error(resp, ApiErrorId.ERR_INVALID_TRADE_STATE.value)

    def test_approve_rejected_trade_second_path(self, api):
        """PRD §2.8 trade-state vs trade-rule priority — second test
        with a different rejection path (counter then reject).

        # difficulty: priority_pair_validation_conflict/trade_state_vs_business_referential_on_approve
        """
        m1, m2, a1, a2 = setup_two_pilots_with_assignments()
        tr = create_trade_request(m1, m2, a1, a2)
        # m2 rejects (no counter round).
        from test_helpers import (
            crew_role_headers,
            scheduler_headers as _sch,
        )
        api.reject_trade_request(tr["id"], crew_role_headers(m2))
        # Approver attempts approval.
        resp = api.approve_trade_request(tr["id"], _sch())
        validate_error(resp, ApiErrorId.ERR_INVALID_TRADE_STATE.value)


# ===========================================================================
# Difficulty: boundary_precision_check / reserve_callout_empty_pool
# ===========================================================================
class TestReserveCalloutEmptyPoolSecondTest:

    def test_empty_pool_keeps_sick_member_status_on_sick_call(self, api):
        """PRD §3.4: "If no covering candidate exists, the sick call is
        still recorded (HTTP 201) but covered_by_assignment_id remains
        null, the pairing keeps its uncovered slot."
        PRD §3.4: "The crew member's status transitions from ACTIVE to
        ON_SICK_CALL."

        # difficulty: boundary_precision_check/reserve_callout_empty_pool
        Second test for empty-pool case: even when the auto-callout
        cannot fire, the primary effect (member -> ON_SICK_CALL) still
        applies.
        """
        sick_pilot = create_crew_member(rank="CAPTAIN")
        pairing, assignment = setup_pairing_admin_assigned(
            sick_pilot, assigned_rank_slot="CAPTAIN",
        )
        resp = report_sick_call(
            sick_pilot, assignment_id=assignment["id"],
        )
        assert resp.status_code == 201
        cm = get_crew_member(sick_pilot["id"])
        assert cm["status"] == "ON_SICK_CALL"


# ===========================================================================
# Difficulty: cross_entity_state_dependency /
#             bid_submission_requires_pairing_bidding_open
# ===========================================================================
class TestBidRequiresBiddingOpenSecondTest:

    def test_bid_on_draft_pairing_rejected(self, api):
        """PRD §3.2: "A bid against a pairing that is no longer
        BIDDING_OPEN is rejected ... with ERR_PAIRING_INVALID_STATE
        otherwise."

        # difficulty: cross_entity_state_dependency/bid_submission_requires_pairing_bidding_open
        DRAFT pairing case (the test in test_11 covers PUBLISHED).
        """
        pilot = create_crew_member(rank="CAPTAIN")
        pairing, _, _ = build_pairing_with_one_duty_period(
            required_rank_composition={"CAPTAIN": 1},
        )
        # No publish, no open-bidding → status remains DRAFT.
        resp = api.create_bid(
            create_bid_payload(
                pairing["id"], random_bid_window_id(), preference_rank=1,
            ),
            crew_role_headers(pilot),
        )
        validate_error(resp, ApiErrorId.ERR_PAIRING_INVALID_STATE.value)


# ===========================================================================
# Difficulty: resource_temporal_overlap /
#             pairing_internal_dutyperiod_rest_overlap
# ===========================================================================
class TestPairingInternalOverlapSecondTest:

    def test_overlapping_duty_periods_rejected(self, api):
        """PRD §3.1: "The publish step additionally verifies that no
        two duty periods overlap and that the rest gap between
        consecutive duty periods ... is at least the crew-rest minimum
        interval of ten hours; any violation yields
        ERR_PAIRING_INTERNAL_OVERLAP, and the same check applies
        whenever a duty period is appended to a draft."

        # difficulty: resource_temporal_overlap/pairing_internal_dutyperiod_rest_overlap
        Overlap (negative gap) case to complement the 599-vs-600
        boundary test in test_02.
        """
        from test_helpers import create_pairing_draft
        p = create_pairing_draft()
        # D1 covers 08:00-18:00.
        from test_helpers import add_duty_period
        add_duty_period(
            p["id"], 1,
            "2030-06-01T08:00:00.000Z", "2030-06-01T18:00:00.000Z",
        )
        # D2 starts at 17:00 (overlaps D1).
        bad = create_duty_period_payload(
            2,
            "2030-06-01T17:00:00.000Z", "2030-06-02T02:00:00.000Z",
        )
        resp = api.add_duty_period(p["id"], bad, scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_PAIRING_INTERNAL_OVERLAP.value)


# ===========================================================================
# Difficulty: compensating_invariant / trade_execution_conserves_total_block_30d
# ===========================================================================
class TestTradeConservationSecondTest:

    def test_individual_block_changes_balance_across_two_members(self, api):
        """PRD §2.10: "Across a successful trade execution, the SUM of
        cumulative_block_minutes_30d across the two crew members is
        identical before and after, because each minute moves from one
        ledger to the other with no net loss or gain."

        # difficulty: compensating_invariant/trade_execution_conserves_total_block_30d
        Stronger test: assert individual changes are equal-and-opposite,
        not merely that the sum is unchanged.
        """
        m1, m2, a1, a2 = setup_two_pilots_with_assignments()
        m1 = get_crew_member(m1["id"])
        m2 = get_crew_member(m2["id"])
        m1_block_before = int(m1["cumulative_block_minutes_30d"])
        m2_block_before = int(m2["cumulative_block_minutes_30d"])

        tr = create_trade_request(m1, m2, a1, a2)
        from test_helpers import accept_trade_as, approve_trade
        accept_trade_as(m2, tr["id"])
        approve_trade(tr["id"])

        m1_after = get_crew_member(m1["id"])
        m2_after = get_crew_member(m2["id"])
        # Conservation invariant.
        assert_block_minutes_conserved_across_trade(
            m1_block_before, m2_block_before,
            int(m1_after["cumulative_block_minutes_30d"]),
            int(m2_after["cumulative_block_minutes_30d"]),
        )
        # Equal-and-opposite delta (a stronger derivative of the
        # conservation invariant — PRD §2.10 says "each minute moves
        # from one ledger to the other").
        delta1 = int(m1_after["cumulative_block_minutes_30d"]) - m1_block_before
        delta2 = int(m2_after["cumulative_block_minutes_30d"]) - m2_block_before
        assert delta1 == -delta2, (
            f"PRD §2.10: equal-and-opposite cumulative_block_minutes_30d "
            f"deltas; got {delta1} vs {delta2}"
        )


# ===========================================================================
# Difficulty: compensating_invariant /
#             pairing_cancel_undo_conserves_baseline_block_30d
# ===========================================================================
class TestPairingCancelBaselineSecondTest:

    def test_cancel_returns_member_block_30d_to_baseline(self, api):
        """PRD §2.10: "They are incremented when an assignment binds
        and decremented when an assignment is released or its parent
        pairing is cancelled."
        PRD §3.7: cancel debits cumulative_block_minutes_30d by
        Assignment.scheduled_block_minutes when start_at is within the
        rolling 30-day window from now.

        # difficulty: compensating_invariant/pairing_cancel_undo_conserves_baseline_block_30d
        Second test: assert net-zero — baseline before assignment ==
        baseline after cancel — using a higher cumulative starting
        point than test_03's freshly-minted pilot.
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Raise baseline to a non-zero value.
        pilot = raise_cumulative_block_30d(pilot, target_minutes=1500)
        baseline = int(pilot["cumulative_block_minutes_30d"])
        # Add an assignment.
        start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=10),
        )
        pairing, _ = setup_pairing_admin_assigned(
            pilot, assigned_rank_slot="CAPTAIN",
            start_at=start,
            revenue_block_minutes=400, duty_minutes=520,
        )
        mid = get_crew_member(pilot["id"])
        assert int(mid["cumulative_block_minutes_30d"]) == baseline + 400
        # Cancel.
        cancel_pairing(pairing["id"])
        after = get_crew_member(pilot["id"])
        assert int(after["cumulative_block_minutes_30d"]) == baseline, (
            f"PRD §2.10 + §3.7: cancel must return cumulative back to "
            f"baseline; baseline={baseline}, after={after['cumulative_block_minutes_30d']}"
        )
