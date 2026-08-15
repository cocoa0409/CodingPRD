"""The eligibility score: pinned weighted-GPA variant, multi-input weighted
sum (GPA + probation + athletics components), and the 70.00 approval
threshold."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_athletics_block,
    add_member,
    api_client,
    close_cycle_nominations,
    create_active_chapter,
    create_cycle,
    list_applications,
    nominate,
    open_cycle_nominations,
    open_probation_case,
    resolve_probation_case,
    set_clock,
    setup_cycle_in_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADVISOR = TEST_USERS["advisor_headers"]


class TestEligibilityScoreWeightedGpaVariant:
    def test_score_uses_weighted_gpa_on_five_point_scale(self):
        """PRD section 3.2: "The GPA component expresses the member's
        `weighted_gpa` as a percentage of the 5.0 scale — the GPA divided by
        5.0 and multiplied by 100 — clamps the result into the inclusive range
        from 0 to 100, and weights it at 40 percent."
        PRD section 3.2: "The five weighted components are summed, the raw
        total is clamped into the inclusive range from 0 to 100, and the result
        is rounded half-up to two decimal places to yield the final
        `eligibility_score`."

        Design: Difficulty/dual_variant_calc/eligibility_score_weighted_vs_unweighted_gpa_diverge
        """
        # weighted 3.45 (below the 3.50 weighted bar) with unweighted 3.30
        # (above the 3.25 unweighted bar): nomination passes on the unweighted
        # leg, and the pinned formula reads weighted_gpa only.
        env = setup_cycle_in_review(
            member_overrides=[{"weighted_gpa": 3.45, "unweighted_gpa": 3.30}])
        app = env["applications"][0]
        # gpa component: 100 * (3.45 / 5.0) * 0.40 = 27.60; all other
        # components are zero (no verified hours, no office, no strikes, no
        # athletics block).
        assert app["eligibility_score"] == pytest.approx(27.60, abs=0.01), (
            f"expected the weighted-GPA variant (27.60), got "
            f"{app['eligibility_score']}"
        )
        # The unweighted variant would have produced 100*(3.30/4.0)*0.40=33.00.
        assert not (app["eligibility_score"] == pytest.approx(33.00, abs=0.01))

    def test_weighted_variant_score_below_threshold_blocks_approval(self):
        """PRD section 3.2: "Approval is granted only when the application's
        `eligibility_score` is at least 70.00 and the member's `good_standing`
        is true — where the service-hour reading used for induction eligibility
        is the strict per-semester variant of §3.3 — and a failure on
        either front is rejected with
        `ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        Design: Difficulty/dual_variant_calc/eligibility_score_weighted_vs_unweighted_gpa_diverge
        """
        env = setup_cycle_in_review(
            member_overrides=[{"weighted_gpa": 3.45, "unweighted_gpa": 3.30}])
        app = env["applications"][0]
        assert app["eligibility_score"] == pytest.approx(27.60, abs=0.01)
        resp = api_client.approve_application(
            env["chapter"]["id"], env["cycle"]["id"], app["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD)
        after = validate_success(api_client.get_application(
            env["chapter"]["id"], env["cycle"]["id"], app["id"], ADVISOR))
        assert after["status"] == "UNDER_REVIEW"


class TestEligibilityScoreMultiInput:
    def test_probation_strike_subtracts_weighted_points(self):
        """PRD section 3.2: "The probation component subtracts 20 points for
        each of the member's `probation_strikes`, weighted at 10 percent."
        PRD section 3.7: "their `probation_strikes` — the count of their
        `RESOLVED` cases bearing a confirmed outcome — increases by one".

        Design: Difficulty/combinatorial_formula/eligibility_score_multi_input_weighted_clamp
        """
        set_clock()
        chapter = create_active_chapter()
        member = add_member(chapter["id"], weighted_gpa=4.50,
                            unweighted_gpa=3.90)
        # One confirmed, resolved case before nomination => one strike.
        case = open_probation_case(chapter["id"], member["id"])
        resolve_probation_case(chapter["id"], member["id"], case["id"])
        cycle = create_cycle(chapter["id"])
        open_cycle_nominations(chapter["id"], cycle["id"])
        nominate(chapter["id"], member["id"])
        close_cycle_nominations(chapter["id"], cycle["id"])
        app = list_applications(chapter["id"], cycle["id"])[0]
        # gpa: 100 * (4.50 / 5.0) * 0.40 = 36.00; probation: -20 * 1 * 0.10
        # = -2.00; total 34.00.
        assert app["eligibility_score"] == pytest.approx(34.00, abs=0.01), (
            f"expected 34.00 (36.00 GPA component minus 2.00 probation "
            f"component), got {app['eligibility_score']}"
        )

    def test_athletics_overlap_subtracts_weighted_points(self):
        """PRD section 3.2: "The athletics component subtracts 10 points when
        an `ACTIVE` athletics block belonging to the member overlaps the
        cycle's `induction_date`, and 0 otherwise, weighted at 5 percent."

        Design: Difficulty/combinatorial_formula/eligibility_score_multi_input_weighted_clamp
        """
        set_clock()
        chapter = create_active_chapter()
        member = add_member(chapter["id"], weighted_gpa=4.50,
                            unweighted_gpa=3.90)
        cycle = create_cycle(chapter["id"])
        open_cycle_nominations(chapter["id"], cycle["id"])
        nominate(chapter["id"], member["id"])
        # Block registered after nomination, overlapping the induction date.
        add_athletics_block(chapter["id"], member["id"],
                            block_start="2026-08-30T00:00:00Z",
                            block_end="2026-09-05T00:00:00Z", priority="GAME")
        close_cycle_nominations(chapter["id"], cycle["id"])
        app = list_applications(chapter["id"], cycle["id"])[0]
        # gpa 36.00; athletics: -10 * 0.05 = -0.50; total 35.50.
        assert app["eligibility_score"] == pytest.approx(35.50, abs=0.01), (
            f"expected 35.50 (36.00 GPA component minus 0.50 athletics "
            f"component), got {app['eligibility_score']}"
        )


class TestEligibilityScoreThreshold:
    def test_max_gpa_only_application_scores_40_and_is_rejected(self):
        """PRD section 3.2: "The GPA component expresses the member's
        `weighted_gpa` as a percentage of the 5.0 scale — the GPA divided by
        5.0 and multiplied by 100 — clamps the result into the inclusive range
        from 0 to 100, and weights it at 40 percent."

        Design: Difficulty/boundary_precision_check/eligibility_score_exact_threshold_70_00
        """
        env = setup_cycle_in_review(
            member_overrides=[{"weighted_gpa": 5.00, "unweighted_gpa": 4.00}])
        app = env["applications"][0]
        # Clamped GPA component: 100 * 0.40 = 40.00; every other component 0.
        assert app["eligibility_score"] == pytest.approx(40.00, abs=0.01)

    def test_score_below_70_threshold_blocks_approval(self):
        """PRD section 3.2: "Approval is granted only when the application's
        `eligibility_score` is at least 70.00 and the member's `good_standing`
        is true — where the service-hour reading used for induction eligibility
        is the strict per-semester variant of §3.3 — and a failure on
        either front is rejected with
        `ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/eligibility_score_exact_threshold_70_00
        """
        env = setup_cycle_in_review(
            member_overrides=[{"weighted_gpa": 5.00, "unweighted_gpa": 4.00}])
        app = env["applications"][0]
        assert app["eligibility_score"] == pytest.approx(40.00, abs=0.01)
        assert 40.00 < 70.00
        resp = api_client.approve_application(
            env["chapter"]["id"], env["cycle"]["id"], app["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD)
        after = validate_success(api_client.get_application(
            env["chapter"]["id"], env["cycle"]["id"], app["id"], ADVISOR))
        assert after["status"] == "UNDER_REVIEW"
