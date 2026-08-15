"""Compensating invariants: post/void restores rollups and budget actuals (PRD §2.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    setup_case_with_lines,
    setup_card_rvu,
    setup_ortho_tdabc,
    setup_posted_card_case,
    post_case,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]


class TestServiceLineRollupCompensation:
    def test_case_post_void_restores_service_line_rollup(self, api):
        """PRD §2.8: "Voiding a posted case is a compensation, not a deletion:
        the service line's `total_direct_cost`, `total_revenue`, and
        `contribution_margin` are reduced by exactly the contribution the case
        previously added, and the budget period's actual volume is reduced with
        its flex and variance recomputed."

        Design: Difficulty/compensating_invariant/case_post_void_restores_service_line_rollup
        """
        scenario = setup_ortho_tdabc(rate_factor=1.20)
        sl_id = scenario["service_line"]["id"]

        before = validate_success(api.get_service_line(sl_id, FC))
        assert before["total_direct_cost"] == pytest.approx(0.00, abs=0.005)
        assert before["total_revenue"] == pytest.approx(0.00, abs=0.005)

        case = setup_case_with_lines(scenario, [100, 120, 130, 80])
        post_case(case["id"], scenario["model_version"])

        after_post = validate_success(api.get_service_line(sl_id, FC))
        # activity = (180+216+234+144) = 774.00; rollup = base 9000 + indirect
        # (774.00 activity + 7000.00 pool = 7774.00) = 16774.00 per PRD §2.8:
        # total_direct_cost = base_direct_cost + sum(total_indirect_allocated).
        # The instance's own conserved-quantity claim is what is pinned here:
        # void must restore the pre-post values exactly.
        post_tdc = after_post["total_direct_cost"]
        post_rev = after_post["total_revenue"]
        assert post_rev == pytest.approx(30000.00, abs=0.005)

        validate_success(api.void_case(case["id"], CA))

        after_void = validate_success(api.get_service_line(sl_id, FC))
        assert after_void["total_direct_cost"] == pytest.approx(
            before["total_direct_cost"], abs=0.005
        ), "void must restore total_direct_cost to its pre-post value"
        assert after_void["total_revenue"] == pytest.approx(
            before["total_revenue"], abs=0.005
        ), "void must restore total_revenue to its pre-post value"
        assert after_void["contribution_margin"] == pytest.approx(
            before["contribution_margin"], abs=0.005
        )

    def test_void_compensation_is_exact_under_repeated_post_void(self, api):
        """PRD §2.8: "Voiding a posted case is a compensation, not a deletion:
        the service line's `total_direct_cost`, `total_revenue`, and
        `contribution_margin` are reduced by exactly the contribution the case
        previously added, and the budget period's actual volume is reduced with
        its flex and variance recomputed."

        Design: Difficulty/compensating_invariant/case_post_void_restores_service_line_rollup
        """
        scenario = setup_ortho_tdabc(rate_factor=1.20)
        sl_id = scenario["service_line"]["id"]

        case_one = setup_case_with_lines(scenario, [100])
        post_case(case_one["id"], scenario["model_version"])
        case_two = setup_case_with_lines(scenario, [200])
        post_case(case_two["id"], scenario["model_version"])
        mid = validate_success(api.get_service_line(sl_id, FC))

        # Voiding the second case must leave exactly the first case's contribution.
        validate_success(api.void_case(case_two["id"], CA))
        after = validate_success(api.get_service_line(sl_id, FC))
        first_only = mid["total_revenue"] - 30000.00
        assert after["total_revenue"] == pytest.approx(first_only, abs=0.005)
        assert after["total_revenue"] == pytest.approx(30000.00, abs=0.005)


class TestBudgetActualsCompensation:
    def test_budget_actuals_restored_after_void(self, api):
        """PRD §2.8: "Voiding a posted case is a compensation, not a deletion:
        the service line's `total_direct_cost`, `total_revenue`, and
        `contribution_margin` are reduced by exactly the contribution the case
        previously added, and the budget period's actual volume is reduced with
        its flex and variance recomputed."

        Design: Difficulty/compensating_invariant/budget_actuals_restored_after_void
        """
        scenario = setup_card_rvu(period="2026-08", with_budget_period=True,
                                  static_budget_amount=7000.00)
        bp_id = scenario["budget_period"]["id"]

        before = validate_success(api.get_budget_period(bp_id, FC))
        assert before["actual_indirect_volume"] == pytest.approx(0.00, abs=0.005)

        case = setup_posted_card_case(scenario, lab_qty=4, rad_qty=6)
        after_post = validate_success(api.get_budget_period(bp_id, FC))
        assert after_post["actual_indirect_volume"] == pytest.approx(28000.00, abs=0.005)

        validate_success(api.void_case(case["id"], CA))
        after_void = validate_success(api.get_budget_period(bp_id, FC))
        assert after_void["actual_indirect_volume"] == pytest.approx(0.00, abs=0.005)
        assert after_void["flexed_overhead"] == pytest.approx(0.00, abs=0.005)
        assert after_void["variance_amount"] == pytest.approx(-7000.00, abs=0.005)
        assert after_void["variance_direction"] == "FAVORABLE"

    def test_voided_case_excluded_from_actuals_while_sibling_remains(self, api):
        """PRD §3.5: "`actual_indirect_volume` is the sum, over all `POSTED` and
        `LOCKED` cases in the period that were priced by any model drawing on
        this overhead pool, of each case's pre-overhead activity total — that is,
        the case's `total_indirect_allocated` minus the overhead pool amount that
        was added to it at pricing time. `DRAFT` and `VOIDED` cases never count."

        Design: Difficulty/compensating_invariant/budget_actuals_restored_after_void
        """
        scenario = setup_card_rvu(period="2026-08", with_budget_period=True,
                                  static_budget_amount=7000.00)
        bp_id = scenario["budget_period"]["id"]

        case_a = setup_posted_card_case(scenario, lab_qty=4, rad_qty=None)
        case_b = setup_posted_card_case(scenario, lab_qty=4, rad_qty=None)
        mid = validate_success(api.get_budget_period(bp_id, FC))
        # 2 cases x (4 * 2500) = 20000.00
        assert mid["actual_indirect_volume"] == pytest.approx(20000.00, abs=0.005)

        validate_success(api.void_case(case_b["id"], CA))
        after = validate_success(api.get_budget_period(bp_id, FC))
        assert after["actual_indirect_volume"] == pytest.approx(10000.00, abs=0.005)
        # 10000.00 -> tier 0.30 -> flex 3000.00; variance 3000 - 7000 = -4000 FAVORABLE
        assert after["flexed_overhead"] == pytest.approx(3000.00, abs=0.005)
        assert after["variance_amount"] == pytest.approx(-4000.00, abs=0.005)
        assert after["variance_direction"] == "FAVORABLE"
