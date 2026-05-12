"""Second-coverage tests for every difficulty-design instance.

Each test in this file covers a distinct instance from
SCAFFOLD_DIFFICULTY_DESIGN.yaml's `scaffold_difficulty_design` list to
ensure every instance carries at least TWO `# difficulty:` tags
(per the test generator's coverage rule).

Each test still cites a verbatim PRD sentence — the difficulty index
is an extraction guide, never a substitute citation.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    advance_clock,
    advance_to_running,
    api_client,
    apply_to_activity,
    apply_to_activity_payload,
    approve_application,
    approve_hour_adjustment,
    archive_point_mall_item,
    check_in_payload,
    check_in_via_site_code,
    check_out,
    create_certificate_template,
    create_draft_activity,
    create_point_mall_item,
    create_redemption_order,
    create_skill,
    create_verified_volunteer,
    declare_and_approve_skill,
    file_hour_adjustment,
    get_activity,
    get_application,
    get_volunteer,
    issue_certificate_payload,
    make_organizer_headers,
    make_skilladmin_headers,
    make_volunteer_headers,
    publish_activity,
    reject_activity,
    resubmit_volunteer_skill_payload,
    setup_completed_application,
    setup_organizer,
    setup_recruiting_activity,
    setup_running_activity_with_approved_volunteer,
    submit_activity,
    validate_error,
    validate_success,
    withdraw_application,
)


# =========================================================================
# Rule 1 instance 2 — dual_variant_calc / point_earn_calc balance update
# =========================================================================
class TestPointEarnCompletionVariantOnVolunteerBalance:
    """difficulty: dual_variant_calc/point_earn_calc_completion_vs_adjustment_on_volunteer_balance"""

    def test_first_completion_credits_full_amount_to_volunteer_balance(self, api):
        """PRD §3.7: 'On a first-time completion (whether
        volunteer-initiated check-out or automatic completion at
        activity end), the freshly-computed value is written into
        Application.points_awarded and the volunteer's points_balance
        is increased by the full amount.'

        # difficulty: dual_variant_calc/point_earn_calc_completion_vs_adjustment_on_volunteer_balance
        """
        scenario = setup_completed_application(
            difficulty="MEDIUM", role_label="LEAD", duration_hours=2,
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        # 2.00 hours, MEDIUM (1.50), LEAD (1.20) -> floor(20*1.50*1.20)=36.
        # First-completion variant adds the FULL 36 to balance.
        assert int(application["points_awarded"]) == 36
        assert int(volunteer["points_balance"]) == 36


# =========================================================================
# Rule 2 instance 1 — combinatorial_formula / pinned rounding order
# =========================================================================
class TestRoundingOrderHardEasyCases:
    """difficulty: combinatorial_formula/point_earn_calc_three_factor_with_pinned_rounding_order"""

    def test_floor_rule_with_hard_difficulty_does_not_round_half_up(self, api):
        """PRD §3.7: 'the integer Application.points_awarded is the
        floor of that raw value — always rounded down to an integer,
        never half up.'

        Setup: ACTUAL_DURATION 1.07 hours (64.2 min approx), HARD
        (2.00), no role (1.00). base = round(1.07*10, 2) = 10.70.
        raw = 10.70 * 2.00 * 1.00 = 21.40 -> floor 21 (not 21).
        We use 1.07 hours by checking out 64.2 minutes after start.

        Actually pinpointing 64.2 minutes via clock advancement is
        tricky. Use a more controllable scenario: start_at offsets in
        whole minutes that produce a fractional hour with a known
        non-half-up floor effect.

        Use 1.50 hours (90 min) with HARD/None: base=15.00,
        raw=15.00*2.00*1.00=30.00 -> floor 30. Trivially exact.

        Use 0.50 hours with HARD/REGULAR: base=5.00,
        raw=5.00*2.00*0.90=9.00 -> 9. Trivially exact.

        Use 1.00 hours with MEDIUM/None: base=10.00,
        raw=10.00*1.50*1.00=15.00 -> floor 15. Trivially exact too.

        For a meaningful floor-vs-half-up test we need adjusted_hours
        producing a non-integer raw. Use early-departure: 1.50h * 0.75
        = 1.125 -> round to 1.13 (covered already in rounding_order
        test). Different cell: pick MEDIUM/SUPPORT with 1.13 hours
        (already covered) — instead pick MEDIUM/REGULAR. We need a
        different invocation cell to constitute a SECOND test for the
        instance.

        Fresh scenario: HARD/None with early-departure on 90 min:
        adjusted = 1.13. base = round(1.13*10, 2) = 11.30. raw =
        11.30 * 2.00 * 1.00 = 22.60 -> floor 22, not 23.

        # difficulty: combinatorial_formula/point_earn_calc_three_factor_with_pinned_rounding_order
        """
        scenario = setup_running_activity_with_approved_volunteer(
            difficulty="HARD", hour_rule_type="ACTUAL_DURATION",
        )
        application = scenario["application"]
        volunteer = scenario["volunteer"]
        activity = scenario["activity"]
        application = check_in_via_site_code(
            application=application, volunteer=volunteer, activity=activity
        )
        # Activity is 2h. start + 90 min = 30 min before end -> early-departure.
        advance_clock(add_minutes(activity["start_at"], 90))
        application = api.check_out(
            application["id"], make_volunteer_headers(volunteer["id"])
        ).json()["data"]
        assert application["early_departure_marker"] is True
        # adjusted_hours = round(1.50 * 0.75, 2) = round(1.125, 2) = 1.13.
        assert application["adjusted_hours"] == pytest.approx(1.13, abs=0.005)
        # base = round(1.13*10, 2) = 11.30. raw = 11.30 * 2.00 * 1.00 = 22.60.
        # floor(22.60) = 22 (NOT 23 — this is the load-bearing claim).
        assert int(application["points_awarded"]) == 22


# =========================================================================
# Rule 2 instance 2 — combinatorial_formula / time_conflict three-input
# =========================================================================
class TestTimeConflictThreeInputCombination:
    """difficulty: combinatorial_formula/time_conflict_three_input_overlap_check"""

    def test_unfilled_quota_with_overlapping_window_returns_time_conflict(self, api):
        """PRD §3.4: 'the same time-conflict check that applied at
        apply time is re-evaluated at approve time against the
        volunteer's other non-terminal applications, with the same
        ERR_TIME_CONFLICT outcome.'

        PRD §2.7 priority: time-conflict (priority 12) fires BEFORE
        position quota (priority 17). So with quota unfilled and an
        overlapping APPROVED Application in flight, the approve fails
        with ERR_TIME_CONFLICT, not ERR_QUOTA_EXCEEDED.

        Setup: Volunteer V has APPROVED Application on Activity A1
        [12:00-14:00] which is in CHECKED_IN. V applies to A2
        [13:00-15:00] — overlapping interior. Quota on A2 is 5 with
        filled_positions=0 (not full).

        # difficulty: combinatorial_formula/time_conflict_three_input_overlap_check
        """
        organizer = setup_organizer()

        a1_times = {
            "recruit_open_at": "2031-04-01T08:00:00.000Z",
            "recruit_close_at": "2031-04-01T11:00:00.000Z",
            "start_at": "2031-04-01T12:00:00.000Z",
            "end_at": "2031-04-01T14:00:00.000Z",
        }
        a2_times = {
            "recruit_open_at": "2031-04-01T08:00:00.000Z",
            "recruit_close_at": "2031-04-01T11:00:00.000Z",
            "start_at": "2031-04-01T13:00:00.000Z",
            "end_at": "2031-04-01T15:00:00.000Z",
        }
        # Publish both before any clock advance, then bring to RECRUITING.
        organizer, activity_1, _ = setup_recruiting_activity(
            organizer=organizer, position_quota=5, times=a1_times,
        )
        from test_helpers import advance_to_recruiting
        activity_2_pub, _ = publish_activity(
            organizer=organizer, position_quota=5, times=a2_times,
        )
        activity_2 = advance_to_recruiting(activity_2_pub)

        v = create_verified_volunteer()
        # Apply + approve on A1.
        app_1 = apply_to_activity(volunteer=v, activity=activity_1)
        approve_application(application=app_1, organizer=organizer)
        # Apply on A2; if apply itself rejects with ERR_TIME_CONFLICT,
        # that already proves the rule at apply time. If apply succeeds,
        # the approve must reject with ERR_TIME_CONFLICT.
        app_2_res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity_2["id"]),
            make_volunteer_headers(v["id"]),
        )
        if app_2_res.status_code == 201:
            app_2 = app_2_res.json()["data"]
            # filled_positions on A2 still 0; quota=5 (unfilled).
            res = api.approve_application(
                app_2["id"], make_organizer_headers(organizer["id"])
            )
            validate_error(res, "ERR_TIME_CONFLICT")
        else:
            validate_error(app_2_res, "ERR_TIME_CONFLICT")


# =========================================================================
# Rule 3 instance 1 — Activity REJECTED -> DRAFT cycle (second test)
# =========================================================================
class TestActivityRevisionCycleVersionMonotonic:
    """difficulty: non_linear_state_machine/activity_rejected_to_draft_revision_cycle"""

    def test_each_cycle_iteration_bumps_version_monotonically(self, api):
        """PRD §2.4: 'an integer version field that starts at 1 on
        creation and increments by exactly 1 on every successful
        mutation.'

        Two iterations of the rejection-revision loop must produce
        version >= 5 (creation=1, submit=2, reject=3, revise=4,
        submit=5).

        # difficulty: non_linear_state_machine/activity_rejected_to_draft_revision_cycle
        """
        organizer = setup_organizer()
        activity = create_draft_activity(organizer=organizer)
        assert activity["version"] == 1

        a2 = submit_activity(activity, organizer)
        assert a2["version"] == 2
        a3 = reject_activity(activity["id"])
        assert a3["version"] == 3
        a4 = api.revise_activity(
            activity["id"], make_organizer_headers(organizer["id"])
        ).json()["data"]
        assert a4["version"] == 4
        a5 = submit_activity(activity, organizer)
        assert a5["version"] == 5
        # id unchanged.
        assert a5["id"] == activity["id"]


# =========================================================================
# Rule 3 instance 2 — VolunteerSkill APPROVED -> UNDER_REVIEW (second test)
# =========================================================================
class TestVolunteerSkillResubmitUpdatesCertOnly:
    """difficulty: non_linear_state_machine/volunteerskill_approved_to_under_review_revision_loop"""

    def test_resubmit_does_not_change_volunteer_or_skill_id(self, api):
        """PRD §3.2: 'the volunteer may resubmit the row with a
        refreshed certificate_url in the request body; the row reverts
        from APPROVED to UNDER_REVIEW for re-review, with the new
        certificate_url overwriting the old.'

        Volunteer_id and skill_id remain unchanged across the loop —
        only review_status and certificate_url move.

        # difficulty: non_linear_state_machine/volunteerskill_approved_to_under_review_revision_loop
        """
        v = create_verified_volunteer()
        skill = create_skill(requires_certificate=True)
        approved = declare_and_approve_skill(
            volunteer=v, skill=skill, certificate_url="https://example.test/v1.pdf"
        )
        original_v_id = approved["volunteer_id"]
        original_s_id = approved["skill_id"]

        res = api.resubmit_volunteer_skill(
            approved["id"],
            resubmit_volunteer_skill_payload(certificate_url="https://example.test/v2.pdf"),
            make_volunteer_headers(v["id"]),
        )
        reopened = validate_success(res, expected_status=200)
        assert reopened["volunteer_id"] == original_v_id
        assert reopened["skill_id"] == original_s_id
        assert reopened["review_status"] == "UNDER_REVIEW"
        assert reopened.get("certificate_url") == "https://example.test/v2.pdf"


# =========================================================================
# Rule 4 instance 1 — checkout cascade (second test)
# =========================================================================
class TestCheckoutCascadeIncrementsCompletedActivities:
    """difficulty: transitive_cascade/checkout_to_hour_calc_to_points_to_volunteer_balance"""

    def test_two_separate_checkouts_increment_completed_activities_to_two(self, api):
        """PRD §3.5: 'Volunteer.total_completed_activities is
        incremented by 1' on each check-out.

        Run a single Volunteer through TWO completed Applications in
        non-overlapping windows; total_completed_activities must end at 2.

        # difficulty: transitive_cascade/checkout_to_hour_calc_to_points_to_volunteer_balance
        """
        s1 = setup_completed_application(
            difficulty="EASY", role_label=None, duration_hours=1,
        )
        v = s1["volunteer"]
        # 1.00h * EASY (1.00) * default (1.00) = floor(10.00) = 10 points.
        assert int(s1["application"]["points_awarded"]) == 10
        assert int(v["total_completed_activities"]) == 1
        assert float(v["total_service_hours"]) == pytest.approx(1.00, abs=0.005)
        assert int(v["points_balance"]) == 10

        # Second application — but this time we cannot reuse the same
        # volunteer through the helper (which always creates a fresh
        # one). To exercise "second checkout for same volunteer", run
        # a manual scenario. Build a fresh recruiting Activity in a
        # later time window, V (already verified) applies, organizer
        # approves, advance to RUNNING+CHECKED_IN+CHECKED_OUT.
        from test_helpers import (
            CLOCK_BASELINE_ISO, advance_to_running, add_hours, get_volunteer,
            make_activity_times, publish_activity, advance_to_recruiting,
        )

        # Schedule the second activity in a window that is strictly future
        # relative to the SERVER'S CURRENT logical clock. The first
        # setup_completed_application above already advanced the clock past
        # its own end_at; anchoring on a static far_base would silently
        # leave the second activity marooned in PUBLISHED, since the server
        # clock could already be past the would-be recruit_open_at.
        # Passing base_iso=None (the default) makes make_activity_times
        # query the server clock and anchor times safely in the future.
        times = make_activity_times()
        # Use a fresh organizer so the activity is owned by them.
        organizer2 = s1["organizer"]
        activity2, _ = publish_activity(organizer=organizer2, times=times)
        activity2 = advance_to_recruiting(activity2)
        app2 = apply_to_activity(volunteer=v, activity=activity2)
        approve_application(application=app2, organizer=organizer2)
        advance_to_running(activity2)
        app2 = check_in_via_site_code(
            application=app2, volunteer=v, activity=activity2
        )
        # Check out at one second short of end_at; advancing to exactly
        # end_at would let the impl's clock-sweep auto-cascade
        # RUNNING -> COMPLETED before the manual /check-out call could fire.
        from test_helpers import add_seconds
        advance_clock(add_seconds(activity2["end_at"], -1))
        app2 = api.check_out(app2["id"], make_volunteer_headers(v["id"])).json()["data"]
        v_after = get_volunteer(v["id"])
        assert int(v_after["total_completed_activities"]) == 2


# =========================================================================
# Rule 4 instance 2 — hour_adjust cascade (second test)
# =========================================================================
class TestHourAdjustmentCascadeNegativeDelta:
    """difficulty: transitive_cascade/hour_adjust_approve_to_application_to_volunteer_to_certificate_eligibility"""

    def test_negative_delta_propagates_through_cascade(self, api):
        """PRD §3.7: 'increases Volunteer.total_service_hours by the
        hours delta, and increases Volunteer.points_balance by the
        points delta.' (Negative deltas decrease.)

        Setup: Application with adjusted_hours=2.00, points_awarded=36.
        Approve HourAdjustment with delta=-0.25:
          new adjusted_hours = 1.75
          new base = round(1.75*10, 2) = 17.50
          new raw = 17.50 * 1.50 * 1.20 = 31.50 -> floor 31
          delta points = 31 - 36 = -5
          balance: 36 - 5 = 31

        # difficulty: transitive_cascade/hour_adjust_approve_to_application_to_volunteer_to_certificate_eligibility
        """
        scenario = setup_completed_application(
            difficulty="MEDIUM", role_label="LEAD", duration_hours=2,
        )
        application = scenario["application"]
        organizer = scenario["organizer"]
        volunteer = scenario["volunteer"]
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=-0.25
        )
        approve_hour_adjustment(adj["id"])
        new_app = get_application(application["id"])
        new_v = get_volunteer(volunteer["id"])
        assert new_app["adjusted_hours"] == pytest.approx(1.75, abs=0.005)
        assert int(new_app["points_awarded"]) == 31
        assert float(new_v["total_service_hours"]) == pytest.approx(1.75, abs=0.005)
        assert int(new_v["points_balance"]) == 31


# =========================================================================
# Rule 5 instance 1 — state vs business_safety (second test)
# =========================================================================
class TestStateBeforeCheckInProofIsolated:
    """difficulty: priority_pair_validation_conflict/state_vs_business_safety_check_in_proof_vs_activity_state"""

    def test_state_check_supersedes_check_in_proof_with_partial_proof(self, api):
        """PRD §2.7: state-machine permissibility precedes field-level
        proof checks. Repeat with PARTIAL proof (lat without lng) to
        verify the state check still fires when proof is incomplete
        rather than fully missing.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_check_in_proof_vs_activity_state
        """
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=application, organizer=organizer)
        # Activity STILL RECRUITING; submit only lat (incomplete proof).
        res = api.check_in(
            application["id"],
            check_in_payload(check_in_lat=activity["location_lat"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# =========================================================================
# Rule 5 instance 2 — business_safety vs business_temporal (second test)
# =========================================================================
class TestIdentityBeforeRecruitmentClosedSecondVariant:
    """difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_identity_vs_recruitment_window"""

    def test_rejected_identity_volunteer_in_closed_recruitment_returns_identity_error(
        self, api
    ):
        """PRD §2.7 illustrates: 'a caller whose identity is unverified
        and who would also fail a skill-match check always receives
        ERR_IDENTITY_NOT_VERIFIED first'.

        Variant: identity is REJECTED (terminal failure), recruitment
        window has not opened yet (so PUBLISHED, not RECRUITING). The
        identity error must still come first.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_identity_vs_recruitment_window
        """
        from test_helpers import create_volunteer, reject_identity, publish_activity
        organizer = setup_organizer()
        activity, _ = publish_activity(organizer=organizer)  # PUBLISHED
        # Volunteer with REJECTED identity.
        v = create_volunteer()
        reject_identity(v["id"])
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_IDENTITY_NOT_VERIFIED")


# =========================================================================
# Rule 7 instance 1 — Application check-in requires Activity RUNNING (second test)
# =========================================================================
class TestApplicationCheckInRequiresActivityRunningAfterEnd:
    """difficulty: cross_entity_state_dependency/application_check_in_requires_activity_running"""

    def test_check_in_after_activity_completed_rejected(self, api):
        """PRD §3.5: 'Once the parent activity reaches RUNNING, the
        volunteer who holds an APPROVED application checks in.'

        With Activity in COMPLETED (past RUNNING), the check-in
        precondition fails. PRD §2.7 places state-machine
        permissibility above field-level proof checks.

        # difficulty: cross_entity_state_dependency/application_check_in_requires_activity_running
        """
        organizer, activity, _ = setup_recruiting_activity(position_quota=2)
        v = create_verified_volunteer()
        application = apply_to_activity(volunteer=v, activity=activity)
        approve_application(application=application, organizer=organizer)
        # Drive Activity past RUNNING straight to COMPLETED (no check-in).
        advance_to_running(activity)
        from test_helpers import advance_to_completed
        advance_to_completed(activity)
        # Application is now NO_SHOW (PRD §3.3 cascade). Check-in must reject.
        res = api.check_in(
            application["id"], check_in_payload(site_code="000000"),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# =========================================================================
# Rule 7 instance 2 — RedemptionOrder fulfillment (second test)
# =========================================================================
class TestRedemptionFulfillRequiresPointsRecheckedAtFulfill:
    """difficulty: cross_entity_state_dependency/redemption_fulfill_requires_pointmallitem_active_and_balance_check"""

    def test_fulfill_with_points_drained_between_creation_and_fulfill(self, api):
        """PRD §3.7: 'Volunteer.points_balance to be at least
        total_points (re-checked at fulfillment time, since either
        side may have shifted).'

        Setup: Volunteer with 36 points. Order A for total_points=30 —
        balance 36 >= 30 at creation. Order B for total_points=30 —
        balance 36 >= 30 at creation. Fulfill A first -> balance now 6.
        Fulfill B -> balance check 6 < 30 fails -> ERR_INSUFFICIENT_POINTS.

        # difficulty: cross_entity_state_dependency/redemption_fulfill_requires_pointmallitem_active_and_balance_check
        """
        scenario = setup_completed_application(role_label="LEAD")  # 36 points
        volunteer = scenario["volunteer"]
        item_a = create_point_mall_item(point_cost=30, stock=5)
        item_b = create_point_mall_item(point_cost=30, stock=5)
        order_a = create_redemption_order(
            volunteer=volunteer, item_id=item_a["id"], quantity=1
        )
        order_b = create_redemption_order(
            volunteer=volunteer, item_id=item_b["id"], quantity=1
        )
        # Fulfill A first.
        first = api.fulfill_redemption_order(order_a["id"], make_skilladmin_headers())
        validate_success(first, expected_status=200)
        # Fulfill B — balance is now 6 < 30.
        res = api.fulfill_redemption_order(order_b["id"], make_skilladmin_headers())
        validate_error(res, "ERR_INSUFFICIENT_POINTS")


# =========================================================================
# Rule 8 instance 1 — closed-closed time conflict (second test)
# =========================================================================
class TestVolunteerTimeWindowClosedClosedAtApplyTime:
    """difficulty: resource_temporal_overlap/application_volunteer_time_window_closed_closed_overlap"""

    def test_touching_endpoint_at_apply_time_returns_time_conflict(self, api):
        """PRD §3.4: 'overlap is evaluated as closed-closed intervals,
        so an activity that starts at exactly the moment another ends
        still counts as a conflict and is rejected with
        ERR_TIME_CONFLICT.'

        Setup: Volunteer APPROVED on Activity A [10:00-12:00] (in
        RECRUITING). Volunteer applies to Activity B [12:00-14:00] (in
        RECRUITING) — touching endpoint A.end == B.start. The apply
        itself rejects with ERR_TIME_CONFLICT.

        # difficulty: resource_temporal_overlap/application_volunteer_time_window_closed_closed_overlap
        """
        organizer = setup_organizer()
        # Anchor on the SERVER's current logical clock so the recruitment
        # window is always strictly future relative to whatever state prior
        # tests left the clock in. Hardcoding a fixed wall-clock date
        # silently leaves activities marooned in PUBLISHED whenever the
        # global logical clock has been advanced past the chosen instant.
        from test_helpers import (
            add_hours, get_clock as _get_clock, publish_activity, advance_to_recruiting,
        )
        clock_now = _get_clock().get("now")
        a_times = {
            "recruit_open_at": add_hours(clock_now, 1),
            "recruit_close_at": add_hours(clock_now, 2),
            "start_at": add_hours(clock_now, 3),
            "end_at": add_hours(clock_now, 5),
        }
        b_times = {
            "recruit_open_at": add_hours(clock_now, 1),
            "recruit_close_at": add_hours(clock_now, 2),
            "start_at": add_hours(clock_now, 5),  # touches A.end_at
            "end_at": add_hours(clock_now, 7),
        }
        organizer, activity_a, _ = setup_recruiting_activity(
            organizer=organizer, position_quota=5, times=a_times,
        )
        from test_helpers import publish_activity, advance_to_recruiting
        activity_b_pub, _ = publish_activity(
            organizer=organizer, position_quota=5, times=b_times,
        )
        activity_b = advance_to_recruiting(activity_b_pub)

        v = create_verified_volunteer()
        app_a = apply_to_activity(volunteer=v, activity=activity_a)
        approve_application(application=app_a, organizer=organizer)
        # Apply to B; PRD §3.4 lists the overlap rejection in the apply
        # endpoint's reasons.
        res = api.apply_to_activity(
            apply_to_activity_payload(activity_id=activity_b["id"]),
            make_volunteer_headers(v["id"]),
        )
        validate_error(res, "ERR_TIME_CONFLICT")


# =========================================================================
# Rule 9 instance 1 — filled_positions compensating invariant (second test)
# =========================================================================
class TestFilledPositionsInvariantWithMultipleApplicants:
    """difficulty: compensating_invariant/application_withdraw_restores_filled_positions"""

    def test_two_approves_one_withdraw_yields_filled_positions_one(self, api):
        """PRD §3.4: 'an APPROVED application may be withdrawn by the
        volunteer only while the parent activity is still RECRUITING,
        and the withdrawal additionally decrements
        Activity.filled_positions by exactly 1 to free the slot.'

        After +1 +1 -1, filled_positions == 1.

        # difficulty: compensating_invariant/application_withdraw_restores_filled_positions
        """
        organizer, activity, _ = setup_recruiting_activity(position_quota=5)
        v1 = create_verified_volunteer()
        v2 = create_verified_volunteer()
        a1 = apply_to_activity(volunteer=v1, activity=activity)
        approve_application(application=a1, organizer=organizer)
        a2 = apply_to_activity(volunteer=v2, activity=activity)
        approve_application(application=a2, organizer=organizer)
        # filled_positions == 2.
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 2
        # Withdraw only V1's application.
        withdraw_application(application=a1, volunteer=v1)
        fresh = get_activity(activity["id"])
        assert fresh["filled_positions"] == 1


# =========================================================================
# Rule 9 instance 2 — hour_adjust compensating invariant (second test)
# =========================================================================
class TestHourAdjustCompensatingMultipleStepsRestore:
    """difficulty: compensating_invariant/hour_adjust_approve_then_compensating_adjust_restores_balances"""

    def test_three_step_compensating_sequence_restores_baseline(self, api):
        """PRD §3.7: each approved HourAdjustment increments Volunteer
        totals by the deltas. A sequence delta=+1.00, delta=-0.50,
        delta=-0.50 yields net zero hours — Volunteer
        total_service_hours and points_balance equal the pre-sequence
        baseline.

        Baseline: 2.00 hours, 36 points (MEDIUM/LEAD).
        After +1.00: hours=3.00, points=floor(30*1.50*1.20)=54 (delta +18).
        After -0.50: hours=2.50, points=floor(25*1.50*1.20)=45 (delta -9).
        After -0.50: hours=2.00, points=floor(20*1.50*1.20)=36 (delta -9).
        Net: hours back to 2.00, points back to 36.

        # difficulty: compensating_invariant/hour_adjust_approve_then_compensating_adjust_restores_balances
        """
        scenario = setup_completed_application(
            difficulty="MEDIUM", role_label="LEAD", duration_hours=2,
        )
        application = scenario["application"]
        organizer = scenario["organizer"]
        volunteer = scenario["volunteer"]

        # +1.00
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=1.00
        )
        approve_hour_adjustment(adj["id"])
        # -0.50
        application = get_application(application["id"])
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=-0.50
        )
        approve_hour_adjustment(adj["id"])
        # -0.50
        application = get_application(application["id"])
        adj = file_hour_adjustment(
            application=application, organizer=organizer, delta_hours=-0.50
        )
        approve_hour_adjustment(adj["id"])

        new_app = get_application(application["id"])
        new_v = get_volunteer(volunteer["id"])
        assert new_app["adjusted_hours"] == pytest.approx(2.00, abs=0.005)
        assert int(new_app["points_awarded"]) == 36
        assert float(new_v["total_service_hours"]) == pytest.approx(2.00, abs=0.005)
        assert int(new_v["points_balance"]) == 36
