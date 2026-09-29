"""Post-closing commitment monitoring: the two bases, the review cycle and the reopen reversal."""
import pytest

from test_helpers.assertions import (
    assert_benefits_plan,
    assert_benefits_plan_ledger_identity,
    assert_line_item,
    assert_performance_report,
    assert_same_instant,
)
from test_helpers.fixtures import (
    application_under_review,
    community_benefits_monitoring_world,
    executed_standard_plan,
    file_report,
    read_application,
    read_condition,
    read_line_item,
    read_plan,
    read_report,
    reopen_report,
    review_report,
)

FIRST_QUARTER_ACHIEVED = {
    "MORTGAGE_LENDING": 30_000_000,
    "SMALL_BUSINESS_LENDING": 8_000_000,
    "PHILANTHROPY": 500_000,
    "BRANCH_RETENTION": 1_000_000,
}
SECOND_QUARTER_ACHIEVED = {
    "MORTGAGE_LENDING": 20_000_000,
    "SMALL_BUSINESS_LENDING": 5_000_000,
}
THIRD_QUARTER_ACHIEVED = {
    "MORTGAGE_LENDING": 15_000_000,
    "SMALL_BUSINESS_LENDING": 5_000_000,
}


def _monitored_plan(measurement_basis):
    """An UNDER_REVIEW application carrying an EXECUTED 392,000,000 plan on the given basis."""
    world = application_under_review()
    executed = executed_standard_plan(world["application"]["id"], world["acquirer"]["id"],
                                      measurement_basis=measurement_basis)
    world["plan"] = executed["plan"]
    world["line_items"] = executed["line_items"]
    return world


class TestCumulativeBasisDecidesTheOutcome:
    """A strong quarter carries a weak one on the cumulative basis."""

    def test_the_second_quarter_is_accepted_on_the_cumulative_reading(self):
        """PRD §3.12: "Under the `CUMULATIVE_TO_DATE` basis, a strong quarter carries a weak one:
        take the sum of `credited_usd` across the plan's reports whose `period_index` is at or below
        this report's `period_index` and whose `status` is `ACCEPTED` or `DEFICIENT`, add this
        report's own `credited_usd` so that it is counted exactly once, then divide by the plan's
        frozen `quarterly_target_total_usd` multiplied by this report's `period_index`, multiply by
        100, and round half-up to two decimal places."
        PRD §3.12: "When the report's `fulfillment_pct` is at least 90.00 the report moves
        `FILED → ACCEPTED`; when it is strictly below 90.00 the report moves `FILED → DEFICIENT`."

        Design: Difficulty/dual_variant_calc/commitment_fulfillment_dual_basis_flips_review_outcome
        """
        world = _monitored_plan("CUMULATIVE_TO_DATE")
        plan_id = world["plan"]["id"]
        acquirer_id = world["acquirer"]["id"]
        assert world["plan"]["total_committed_usd"] == 392_000_000
        assert world["plan"]["quarterly_target_total_usd"] == 32_666_666
        first = file_report(plan_id, acquirer_id, "2027Q1", 1, FIRST_QUARTER_ACHIEVED)
        review_report(first["id"])
        second = file_report(plan_id, acquirer_id, "2027Q2", 2, SECOND_QUARTER_ACHIEVED)

        reviewed = review_report(second["id"])

        assert_performance_report(reviewed)
        assert reviewed["credited_usd"] == 25_000_000
        assert reviewed["fulfillment_pct"] == pytest.approx(97.19, abs=0.005), (
            f"63,500,000 over two quarters of target gives 97.19, got {reviewed['fulfillment_pct']}"
        )
        assert reviewed["status"] == "ACCEPTED"

    def test_the_alternate_reading_is_disclosure_only(self):
        """PRD §3.12: "The value under the report's own `measurement_basis` is stored as
        `fulfillment_pct`; the value under the other basis is stored as
        `alternate_fulfillment_pct`, which is disclosure only and never drives an outcome."
        PRD §3.12: "Identical report data can be accepted on one basis and found deficient on the
        other, and the plan's stored basis is what decides."

        Design: Difficulty/dual_variant_calc/commitment_fulfillment_dual_basis_flips_review_outcome
        """
        world = _monitored_plan("CUMULATIVE_TO_DATE")
        plan_id = world["plan"]["id"]
        acquirer_id = world["acquirer"]["id"]
        first = file_report(plan_id, acquirer_id, "2027Q1", 1, FIRST_QUARTER_ACHIEVED)
        review_report(first["id"])
        second = file_report(plan_id, acquirer_id, "2027Q2", 2, SECOND_QUARTER_ACHIEVED)

        reviewed = review_report(second["id"])

        assert reviewed["alternate_fulfillment_pct"] == pytest.approx(76.53, abs=0.005), (
            "the same 25,000,000 read one quarter at a time is 76.53, "
            f"got {reviewed['alternate_fulfillment_pct']}"
        )
        assert reviewed["status"] == "ACCEPTED", (
            "the alternate reading is below 90.00 yet the outcome still follows the stored basis"
        )

    def test_two_accepted_reviews_move_the_ledger_once_each(self):
        """PRD §3.12: "the plan's `credited_to_date_usd` increases by the report's `credited_usd`
        while its `remaining_commitment_usd` decreases by exactly the same amount, and the plan's
        `filed_report_count` increments by 1."
        PRD §3.12: "An acceptance resets the plan's `consecutive_deficient_periods` to 0 and
        recomputes `compliance_status`."

        Design: Difficulty/dual_variant_calc/commitment_fulfillment_dual_basis_flips_review_outcome
        """
        world = _monitored_plan("CUMULATIVE_TO_DATE")
        plan_id = world["plan"]["id"]
        acquirer_id = world["acquirer"]["id"]
        first = file_report(plan_id, acquirer_id, "2027Q1", 1, FIRST_QUARTER_ACHIEVED)
        review_report(first["id"])
        second = file_report(plan_id, acquirer_id, "2027Q2", 2, SECOND_QUARTER_ACHIEVED)
        review_report(second["id"])

        plan = read_plan(plan_id)

        assert_benefits_plan(plan)
        assert plan["credited_to_date_usd"] == 63_500_000
        assert plan["remaining_commitment_usd"] == 328_500_000
        assert_benefits_plan_ledger_identity(plan)
        assert plan["consecutive_deficient_periods"] == 0
        assert plan["compliance_status"] == "COMPLIANT"


class TestReviewReopenReviewCycle:
    """Reviewing, reopening and reviewing again lands on exactly the first outcome."""

    def test_the_second_review_reproduces_the_deficient_outcome(self):
        """PRD §3.12: "Under the `ANNUAL_PRO_RATA` basis, each quarter is judged on its own:
        fulfilment is the report's `credited_usd` divided by the plan's frozen
        `quarterly_target_total_usd`, multiplied by 100 and rounded half-up to two decimal places."
        PRD §3.12: "Either way `reviewed_at` is stamped from the logical clock,
        `reviewed_by_user_id` records the acting `X-User-ID`, the report's `credited_usd` is applied
        to each `CommitmentLineItem`'s `credited_usd` capped per item at that item's
        `committed_usd`, the plan's `credited_to_date_usd` increases by the report's `credited_usd`
        while its `remaining_commitment_usd` decreases by exactly the same amount, and the plan's
        `filed_report_count` increments by 1."

        Design: Difficulty/non_linear_state_machine/performance_report_review_reopen_review_cycle_on_commitment_ledger
        """
        world = _monitored_plan("ANNUAL_PRO_RATA")
        report = file_report(world["plan"]["id"], world["acquirer"]["id"], "2027Q1", 1,
                            SECOND_QUARTER_ACHIEVED)
        first_pass = review_report(report["id"])
        assert first_pass["status"] == "DEFICIENT"
        reopen_report(report["id"])

        second_pass = review_report(report["id"])

        assert second_pass["status"] == "DEFICIENT"
        assert second_pass["credited_usd"] == 25_000_000
        assert second_pass["excess_uncredited_usd"] == 0
        assert second_pass["fulfillment_pct"] == pytest.approx(76.53, abs=0.005)
        assert second_pass["alternate_fulfillment_pct"] == pytest.approx(76.53, abs=0.005), (
            "on the first quarter the two bases coincide"
        )
        assert_same_instant(second_pass["reviewed_at"], "2026-08-01T00:00:00Z", "reviewed_at")

    def test_the_cycle_never_double_credits_the_ledger(self):
        """PRD §3.12: "Reopening clears `reviewed_at` and `reviewed_by_user_id` to null, removes from
        each line item's `credited_usd` exactly the amount applied to it at review, returns the
        plan's `credited_to_date_usd` and `remaining_commitment_usd` to their pre-review values, and
        decrements `filed_report_count` by 1."

        Design: Difficulty/non_linear_state_machine/performance_report_review_reopen_review_cycle_on_commitment_ledger
        """
        world = _monitored_plan("ANNUAL_PRO_RATA")
        report = file_report(world["plan"]["id"], world["acquirer"]["id"], "2027Q1", 1,
                            SECOND_QUARTER_ACHIEVED)
        review_report(report["id"])
        reopen_report(report["id"])
        review_report(report["id"])

        plan = read_plan(world["plan"]["id"])

        assert plan["credited_to_date_usd"] == 25_000_000
        assert plan["remaining_commitment_usd"] == 367_000_000
        assert_benefits_plan_ledger_identity(plan)
        assert plan["filed_report_count"] == 1

    def test_the_cycle_leaves_the_deficiency_run_at_one(self):
        """PRD §3.12: "A deficiency increments `consecutive_deficient_periods` by 1 and recomputes
        `compliance_status` from it: a run of 0 is `COMPLIANT`, a run of exactly 1 is `WATCH`, and a
        run of 2 or more is `DEFICIENT`."
        PRD §3.12: "Reopening a deficient review additionally decrements
        `consecutive_deficient_periods` by 1 and recomputes `compliance_status`; if that drops the
        run below 2, an approval condition that this review had breached returns `BREACHED → OPEN`
        and the application's `post_closing_monitoring_status` returns to `MONITORING`."

        Design: Difficulty/non_linear_state_machine/performance_report_review_reopen_review_cycle_on_commitment_ledger
        """
        world = _monitored_plan("ANNUAL_PRO_RATA")
        report = file_report(world["plan"]["id"], world["acquirer"]["id"], "2027Q1", 1,
                            SECOND_QUARTER_ACHIEVED)
        review_report(report["id"])
        reopen_report(report["id"])
        review_report(report["id"])

        plan = read_plan(world["plan"]["id"])

        assert plan["consecutive_deficient_periods"] == 1, (
            "one deficiency, one reversal and one deficiency again is a run of exactly 1"
        )
        assert plan["compliance_status"] == "WATCH"


class TestReopenRestoresTheLedgerPartition:
    """The reopen is a dollar-for-dollar reversal of the review it undoes."""

    def test_reopen_returns_the_plan_ledger_to_its_pre_review_partition(self):
        """PRD §2.9: "Reopening a reviewed performance report reverses the review cascade dollar for
        dollar: exactly the credits applied at review are removed, the deficiency counters are
        stepped back, and a condition that this review had breached returns to `OPEN`."
        PRD §2.9: "The ledger identity that makes the reversal verifiable is that a plan's
        `credited_to_date_usd` plus its `remaining_commitment_usd` always equals its
        `total_committed_usd`, before the review and after the reopen alike."

        Design: Difficulty/compensating_invariant/report_reopen_restores_the_commitment_ledger_partition
        """
        world = _monitored_plan("CUMULATIVE_TO_DATE")
        report = file_report(world["plan"]["id"], world["acquirer"]["id"], "2027Q1", 1,
                             FIRST_QUARTER_ACHIEVED)
        review_report(report["id"])

        reopen_report(report["id"])

        plan = read_plan(world["plan"]["id"])
        assert plan["total_committed_usd"] == 392_000_000
        assert plan["credited_to_date_usd"] == 0
        assert plan["remaining_commitment_usd"] == 392_000_000
        assert_benefits_plan_ledger_identity(plan)
        assert plan["filed_report_count"] == 0
        assert plan["consecutive_deficient_periods"] == 0
        assert plan["compliance_status"] == "COMPLIANT"

    def test_reopen_clears_the_review_stamps_but_keeps_the_filing_arithmetic(self):
        """PRD §3.12: "Reopening drives `ACCEPTED → FILED` or `DEFICIENT → FILED`, and is permitted
        only when no later report of the same plan has been reviewed; otherwise it is refused with
        `ERR_INVALID_REPORT_STATE`, as is a reopen of a report that is already `FILED` or a review of
        a report that is not `FILED`."
        PRD §3.12: "Filing already computes the fulfilment figures, though it does not yet move the
        plan's ledger."

        Design: Difficulty/compensating_invariant/report_reopen_restores_the_commitment_ledger_partition
        """
        world = _monitored_plan("CUMULATIVE_TO_DATE")
        report = file_report(world["plan"]["id"], world["acquirer"]["id"], "2027Q1", 1,
                             FIRST_QUARTER_ACHIEVED)
        review_report(report["id"])

        reopen_report(report["id"])

        reopened = read_report(report["id"])
        assert reopened["status"] == "FILED"
        assert reopened["reviewed_at"] is None
        assert reopened["reviewed_by_user_id"] is None
        assert reopened["credited_usd"] == 38_500_000
        assert reopened["excess_uncredited_usd"] == 1_000_000, (
            "the BRANCH_RETENTION dollars never had a line item to land on"
        )
        assert reopened["fulfillment_pct"] == pytest.approx(117.86, abs=0.005)

    def test_reopen_strips_every_line_item_credit_it_had_applied(self):
        """PRD §3.9: "Its `annual_target_usd` is `committed_usd` divided by the plan's `term_years`,
        floored to a whole dollar."
        PRD §3.9: "Its `final_year_target_usd` is `committed_usd` less `annual_target_usd`
        multiplied by one fewer than `term_years` — so the final year absorbs the entire flooring
        remainder and the per-item totals reconcile exactly, even though the annual target
        multiplied by the term may fall short of the commitment."

        Design: Difficulty/compensating_invariant/report_reopen_restores_the_commitment_ledger_partition
        """
        world = _monitored_plan("CUMULATIVE_TO_DATE")
        report = file_report(world["plan"]["id"], world["acquirer"]["id"], "2027Q1", 1,
                             FIRST_QUARTER_ACHIEVED)
        review_report(report["id"])

        reopen_report(report["id"])

        for category, item in world["line_items"].items():
            restored = read_line_item(item["id"])
            assert_line_item(restored)
            assert restored["credited_usd"] == 0, f"{category} kept a credit after the reopen"
        mortgage = read_line_item(world["line_items"]["MORTGAGE_LENDING"]["id"])
        assert mortgage["annual_target_usd"] == 83_333_333
        assert mortgage["final_year_target_usd"] == 83_333_334


class TestSecondDeficiencyEscalatesTheCase:
    """Two consecutive deficiencies breach the condition and escalate the application."""

    def test_the_expedited_order_lands_on_the_waiting_period_floor(self):
        """PRD §3.10: "The application is eligible for `expedited_processing` — a boolean stored on
        the order — when four things hold together: its `unresolved_protest_count` is 0, no hearing
        request on it has been granted, the largest `hhi_delta_unmitigated` across its analyses is at
        most 200 (taken as 0 when it has no analyses), and its `management_rating` is exactly
        `SATISFACTORY`."
        PRD §3.10: "`waiting_period_days` is the larger of the adjusted figure and a floor of 5
        days."
        PRD §3.10: "`consummation_deadline_at` is `decided_at` advanced by 180 whole days, and
        consummation is permitted through that instant inclusive."

        Design: Difficulty/transitive_cascade/deficient_report_cascades_to_post_closing_monitoring_escalation
        """
        world = community_benefits_monitoring_world()

        decision = world["decision"]

        assert decision["expedited_processing"] is True
        assert decision["waiting_period_days"] == 5, (
            "a 15-day bank-level base less the 10-day expedited reduction is 5, which is the floor"
        )
        assert_same_instant(decision["consummation_window_open_at"], "2026-09-20T00:00:00Z",
                            "consummation_window_open_at")
        assert_same_instant(decision["consummation_deadline_at"], "2027-03-14T00:00:00Z",
                            "consummation_deadline_at")

    def test_the_second_deficient_quarter_is_judged_on_its_own_credited_dollars(self):
        """PRD §3.12: "Credit is capped per category against the line item's remaining headroom."
        PRD §3.12: "Under the `ANNUAL_PRO_RATA` basis, each quarter is judged on its own: fulfilment
        is the report's `credited_usd` divided by the plan's frozen `quarterly_target_total_usd`,
        multiplied by 100 and rounded half-up to two decimal places."

        Design: Difficulty/transitive_cascade/deficient_report_cascades_to_post_closing_monitoring_escalation
        """
        world = community_benefits_monitoring_world()
        plan_id = world["plan"]["id"]
        acquirer_id = world["acquirer"]["id"]
        first = file_report(plan_id, acquirer_id, "2027Q1", 1, SECOND_QUARTER_ACHIEVED)
        review_report(first["id"])
        second = file_report(plan_id, acquirer_id, "2027Q2", 2, THIRD_QUARTER_ACHIEVED)

        reviewed = review_report(second["id"])

        assert reviewed["credited_usd"] == 20_000_000
        assert reviewed["fulfillment_pct"] == pytest.approx(61.22, abs=0.005)
        assert reviewed["alternate_fulfillment_pct"] == pytest.approx(68.88, abs=0.005)
        assert reviewed["status"] == "DEFICIENT"

    def test_the_run_of_two_breaches_the_condition_and_escalates_the_application(self):
        """PRD §3.12: "When that run reaches 2, the cascade continues two links further: the `OPEN`
        approval condition on the application's order whose `condition_type` is `COMMUNITY_BENEFITS`
        and whose `timing` is `POST_CLOSING` moves `OPEN → BREACHED`, and — caused by that breach —
        the application's `post_closing_monitoring_status` becomes `ESCALATED`."
        PRD §3.12: "Crediting happens on a deficient review just as on an accepted one — falling
        short of the target does not forfeit the dollars actually delivered."

        Design: Difficulty/transitive_cascade/deficient_report_cascades_to_post_closing_monitoring_escalation
        """
        world = community_benefits_monitoring_world()
        plan_id = world["plan"]["id"]
        acquirer_id = world["acquirer"]["id"]
        first = file_report(plan_id, acquirer_id, "2027Q1", 1, SECOND_QUARTER_ACHIEVED)
        review_report(first["id"])
        second = file_report(plan_id, acquirer_id, "2027Q2", 2, THIRD_QUARTER_ACHIEVED)
        review_report(second["id"])

        plan = read_plan(plan_id)
        condition = read_condition(world["condition"]["id"])
        application = read_application(world["application"]["id"], acquirer_id)

        assert plan["consecutive_deficient_periods"] == 2
        assert plan["compliance_status"] == "DEFICIENT"
        assert plan["credited_to_date_usd"] == 45_000_000
        assert plan["remaining_commitment_usd"] == 347_000_000
        assert plan["filed_report_count"] == 2
        assert condition["status"] == "BREACHED"
        assert application["post_closing_monitoring_status"] == "ESCALATED"
        assert application["filing_status"] == "CONSUMMATED"
