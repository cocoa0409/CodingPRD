"""Branch designation cascades, their compensating rescissions, and the closure blackout."""
from test_helpers import ApiErrorId, api_client, make_filer_headers
from test_helpers.assertions import assert_branch, assert_same_instant
from test_helpers.fixtures import (
    application_decided,
    attach_condition,
    designate_for_closure,
    designate_for_divestiture,
    fernwood_closure_world,
    kestrel_market_world,
    read_analysis,
    read_application,
    read_branch,
    read_condition,
    read_conversion_plan,
    read_institution,
    read_market,
    rescind_designation,
    run_competitive_analysis,
)
from prd_bench_local_runner.testing import validate_error


def _kestrel_case_with_open_divestiture_condition() -> dict:
    """A decided Kestrel case whose order carries an OPEN pre-consummation divestiture condition."""
    world = application_decided(with_market=True)
    world["condition"] = attach_condition(
        world["decision"]["id"], condition_type="DIVESTITURE", timing="PRE_CONSUMMATION",
        threshold_usd=39_000_000,
    )
    return world


class TestDivestitureDesignationCascade:
    """Designating a branch walks four records deep."""

    def test_designation_recomputes_the_mitigation_figures_on_the_analysis(self):
        """PRD §3.6: "The competitive analysis for that application and the branch's market
        recomputes `designated_divestiture_deposits_usd`, `hhi_post_mitigated` and
        `mitigation_satisfied`."
        PRD §3.5: "`designated_divestiture_deposits_usd` is the sum of `deposits_usd` over the
        branches in this market whose `status` is `DESIGNATED_FOR_DIVESTITURE` and whose
        `designation_application_id` equals this application."

        Design: Difficulty/transitive_cascade/branch_divestiture_designation_cascades_to_condition_satisfaction
        """
        world = _kestrel_case_with_open_divestiture_condition()
        acquirer_id = world["acquirer"]["id"]

        designate_for_divestiture(world["branch_target_west"]["id"],
                                  world["application"]["id"], acquirer_id)

        analysis = read_analysis(world["analysis"]["id"])
        assert analysis["designated_divestiture_deposits_usd"] == 40_000_000
        assert analysis["hhi_post_mitigated"] == 5592, (
            f"260,000,000 combined plus a 40,000,000 entrant gives 5592, "
            f"got {analysis['hhi_post_mitigated']}"
        )
        assert analysis["mitigation_satisfied"] is True
        assert analysis["screen_result"] == "MITIGATION_REQUIRED", (
            "steps 4 through 6 layer mitigation on top and never revisit the first three"
        )

    def test_a_cleared_posture_satisfies_the_open_divestiture_condition_by_cascade(self):
        """PRD §3.6: "And, once that posture is `CLEARED` or `CLEARED_WITH_DIVESTITURE`, every
        approval condition on the application's decision whose `condition_type` is `DIVESTITURE` and
        whose `status` is `OPEN` becomes `SATISFIED`, with `satisfied_by_user_id` recorded as the
        literal string `"system"` and `satisfied_at` stamped from the logical clock."
        PRD §3.5: "Otherwise, if any analysis has a `screen_result` other than `PASS`, the posture is
        `CLEARED_WITH_DIVESTITURE` — a market that failed its screen but is fully mitigated still
        unblocks the case while recording that divestiture was needed."

        Design: Difficulty/transitive_cascade/branch_divestiture_designation_cascades_to_condition_satisfaction
        """
        world = _kestrel_case_with_open_divestiture_condition()
        assert world["condition"]["status"] == "OPEN"

        designate_for_divestiture(world["branch_target_west"]["id"],
                                  world["application"]["id"], world["acquirer"]["id"])

        application = read_application(world["application"]["id"], world["acquirer"]["id"])
        condition = read_condition(world["condition"]["id"])
        assert application["competitive_posture"] == "CLEARED_WITH_DIVESTITURE"
        assert condition["status"] == "SATISFIED"
        assert condition["satisfied_by_user_id"] == "system"
        assert_same_instant(condition["satisfied_at"], "2026-09-15T00:00:00Z", "satisfied_at")

    def test_designation_leaves_the_deposit_base_untouched(self):
        """PRD §2.8: "The consequence is deliberate and easy to get wrong: designating a branch for
        divestiture or for closure does **not** remove its deposits from the market's deposit base."
        PRD §2.8: "Designation is a promise, not a disposal, and keeping designated deposits in the
        base is what allows the mitigation arithmetic to be evaluated against a stable denominator
        rather than against a base that shifts every time the filer changes its mind."

        Design: Difficulty/transitive_cascade/branch_divestiture_designation_cascades_to_condition_satisfaction
        """
        world = _kestrel_case_with_open_divestiture_condition()

        branch = designate_for_divestiture(world["branch_target_west"]["id"],
                                           world["application"]["id"], world["acquirer"]["id"])

        assert_branch(branch)
        assert branch["status"] == "DESIGNATED_FOR_DIVESTITURE"
        market = read_market(world["market"]["id"])
        assert market["total_deposits_usd"] == 1_000_000_000
        assert market["participant_count"] == 3


class TestRescissionIsTheExactCompensatingAction:
    """Rescinding a divestiture designation reverses the cascade it caused."""

    def test_rescission_restores_the_three_mitigation_figures(self):
        """PRD §3.6: "From `DESIGNATED_FOR_DIVESTITURE → OPEN` it clears
        `designation_application_id`, recomputes the market's analysis figures —
        `designated_divestiture_deposits_usd`, `hhi_post_mitigated` and `mitigation_satisfied` —
        re-rolls the application's `competitive_posture`, and returns to `OPEN` any divestiture
        condition that had been satisfied by cascade once the posture is no longer `CLEARED` or
        `CLEARED_WITH_DIVESTITURE`."

        Design: Difficulty/compensating_invariant/designate_then_rescind_restores_market_base_and_pre_merger_hhi
        """
        world = kestrel_market_world()
        analysis = run_competitive_analysis(world["application"]["id"], world["market"]["id"])
        branch_id = world["branch_target_west"]["id"]
        designate_for_divestiture(branch_id, world["application"]["id"], world["acquirer"]["id"])

        branch = rescind_designation(branch_id, world["acquirer"]["id"])

        assert branch["status"] == "OPEN"
        assert branch["designation_application_id"] is None
        restored = read_analysis(analysis["id"])
        assert restored["designated_divestiture_deposits_usd"] == 0
        assert restored["hhi_post_mitigated"] == 5800
        assert restored["mitigation_satisfied"] is False
        assert restored["required_divestiture_deposits_usd"] == 39_000_000

    def test_rescission_re_rolls_the_posture_and_leaves_the_first_three_steps_alone(self):
        """PRD §3.5: "Steps 1 through 3 look only at current ownership and the unmitigated merger;
        steps 4 through 6 layer mitigation on top and never revisit the first three."
        PRD §3.5: "The roll-up is re-evaluated on every creation or recomputation of an analysis and
        on every branch designation or rescission."

        Design: Difficulty/compensating_invariant/designate_then_rescind_restores_market_base_and_pre_merger_hhi
        """
        world = kestrel_market_world()
        analysis = run_competitive_analysis(world["application"]["id"], world["market"]["id"])
        branch_id = world["branch_target_west"]["id"]
        designate_for_divestiture(branch_id, world["application"]["id"], world["acquirer"]["id"])
        rescind_designation(branch_id, world["acquirer"]["id"])

        restored = read_analysis(analysis["id"])
        application = read_application(world["application"]["id"], world["acquirer"]["id"])

        assert restored["hhi_pre_merger"] == 5400
        assert restored["hhi_post_unmitigated"] == 5800
        assert application["competitive_posture"] == "MITIGATION_REQUIRED"

    def test_neither_designation_nor_rescission_moves_the_deposit_base(self):
        """PRD §3.6: "Neither rescission edge changes the market's deposit base, because designation
        never removed the deposits from it in the first place."
        PRD §2.8: "An institution's `total_deposits_usd` is the sum of `deposits_usd` over its own
        includable branches, and its `branch_count` is the number of those branches."

        Design: Difficulty/compensating_invariant/designate_then_rescind_restores_market_base_and_pre_merger_hhi
        """
        world = kestrel_market_world()
        run_competitive_analysis(world["application"]["id"], world["market"]["id"])
        branch_id = world["branch_target_west"]["id"]
        designate_for_divestiture(branch_id, world["application"]["id"], world["acquirer"]["id"])
        rescind_designation(branch_id, world["acquirer"]["id"])

        market = read_market(world["market"]["id"])
        target = read_institution(world["target"]["id"])

        assert market["total_deposits_usd"] == 1_000_000_000
        assert market["participant_count"] == 3
        assert market["hhi_current"] == 5400
        assert target["total_deposits_usd"] == 100_000_000
        assert target["branch_count"] == 2


class TestClosureNoticeBufferAgainstTheConversionWindow:
    """The buffered closure window and the conversion window conflict when they merely touch."""

    def test_a_buffered_window_touching_the_conversion_window_is_refused(self):
        """PRD §2.10: "These two closed intervals conflict when the buffered closure window's start
        is at or before the conversion window's end **and** the conversion window's start is at or
        before the buffered closure window's end — so two windows that merely touch after buffering
        are already in conflict, which is the opposite of the comment-window rule."
        PRD §3.6: "Finally the buffered closure window described in §2.10 must not intersect the
        application's systems-conversion window, a conflict yielding
        `ERR_CONVERSION_BLACKOUT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/closure_notice_buffer_touching_conversion_window_rejected
        """
        world = fernwood_closure_world()

        response = api_client.designate_branch(
            world["branch"]["id"],
            {
                "application_id": world["application"]["id"],
                "designation_type": "CLOSURE",
                "notice_sent_at": "2027-06-30",
                "planned_closure_date": "2027-09-30",
            },
            make_filer_headers(world["acquirer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_CONVERSION_BLACKOUT_CONFLICT.value, 409)
        assert read_branch(world["branch"]["id"])["status"] == "OPEN", (
            "a refused designation leaves the branch OPEN"
        )

    def test_a_notice_one_day_later_clears_the_buffer_and_is_accepted(self):
        """PRD §2.10: "The window runs from 15 days before the branch-closing notice was mailed
        through 15 days after the office is planned to stop taking deposits, and both endpoints are
        inside the window."
        PRD §3.6: "From them the service computes `notice_lead_days` as the number of whole UTC days
        from `notice_sent_at` to `planned_closure_date`, discarding any partial day, and that lead
        time must be at least 90 days; anything shorter yields
        `ERR_CLOSURE_NOTICE_LEAD_INSUFFICIENT`."

        Design: Difficulty/resource_temporal_overlap/closure_notice_buffer_touching_conversion_window_rejected
        """
        world = fernwood_closure_world()

        branch = designate_for_closure(
            world["branch"]["id"], world["application"]["id"], world["acquirer"]["id"],
            notice_sent_at="2027-07-01", planned_closure_date="2027-09-30",
        )

        assert branch["status"] == "DESIGNATED_FOR_CLOSURE"
        assert branch["notice_lead_days"] == 91, (
            "the shorter lead is the one that clears the blackout, "
            f"got {branch['notice_lead_days']}"
        )
        assert branch["designation_application_id"] == world["application"]["id"]

    def test_a_closure_designation_leaves_the_conversion_plan_and_the_market_alone(self):
        """PRD §3.11: "The plan is created with `status` `DRAFT` and with
        `customer_disclosure_sent_at` and `disclosure_lead_days` null."
        PRD §2.8: "A branch is **includable** when its `status` is `OPEN`,
        `DESIGNATED_FOR_DIVESTITURE` or `DESIGNATED_FOR_CLOSURE`."

        Design: Difficulty/resource_temporal_overlap/closure_notice_buffer_touching_conversion_window_rejected
        """
        world = fernwood_closure_world()
        designate_for_closure(
            world["branch"]["id"], world["application"]["id"], world["acquirer"]["id"],
            notice_sent_at="2027-07-01", planned_closure_date="2027-09-30",
        )

        plan = read_conversion_plan(world["conversion_plan"]["id"])
        market = read_market(world["market"]["id"])

        assert plan["status"] == "DRAFT"
        assert market["total_deposits_usd"] == 35_000_000
