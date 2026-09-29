"""Derived arithmetic: pro-rata allocation, market thresholds and the waiting period."""
import pytest

from test_helpers import ApiErrorId, TEST_USERS, api_client, make_filer_headers
from test_helpers.assertions import (
    assert_approval_decision,
    assert_benefits_plan,
    assert_competitive_analysis,
    assert_line_item,
    assert_performance_report,
    assert_pro_forma_schedule,
    assert_same_instant,
)
from test_helpers.constants import STANDARD_LINE_ITEMS
from test_helpers.fixtures import (
    add_line_item,
    application_under_review,
    close_comment_period,
    create_regulatory_schedule,
    create_undercapitalized_schedule,
    decide_hearing,
    designate_for_divestiture,
    execute_plan,
    executed_standard_plan,
    file_report,
    file_substantive_protest,
    granite_market_world,
    issue_decision,
    pinehill_rural_world,
    propose_plan,
    read_analysis,
    read_application,
    read_branch,
    read_market,
    read_plan,
    read_schedule,
    recommend_application,
    request_hearing,
    set_clock,
    submit_application,
    two_bank_world,
)
from prd_bench_local_runner.testing import validate_error, validate_success

ANALYST = TEST_USERS["analyst_headers"]

TERM_YEARS = 3
# 250,000,000 / 120,000,000 / 7,000,000 / 15,000,000 over a three-year term.
EXPECTED_TARGETS = {
    "MORTGAGE_LENDING": (83_333_333, 83_333_334),
    "SMALL_BUSINESS_LENDING": (40_000_000, 40_000_000),
    "PHILANTHROPY": (2_333_333, 2_333_334),
    "CDFI_INVESTMENT": (5_000_000, 5_000_000),
}


class TestCommitmentProRataAllocation:
    """Flooring each annual target and letting the final year absorb the remainder."""

    def test_01_the_final_year_absorbs_every_flooring_remainder(self):
        """PRD §3.9: "Its `annual_target_usd` is `committed_usd` divided by the plan's `term_years`,
        floored to a whole dollar."
        PRD §3.9: "Its `final_year_target_usd` is `committed_usd` less `annual_target_usd`
        multiplied by one fewer than `term_years` — so the final year absorbs the entire flooring
        remainder and the per-item totals reconcile exactly, even though the annual target
        multiplied by the term may fall short of the commitment."

        Design: Corner/calculations/commitment_pro_rata_final_year_absorbs_every_floor_remainder
        """
        world = application_under_review()
        acquirer_id = world["acquirer"]["id"]
        plan = propose_plan(world["application"]["id"], acquirer_id, term_years=TERM_YEARS,
                            measurement_basis="CUMULATIVE_TO_DATE")

        items = {}
        for category, committed in STANDARD_LINE_ITEMS:
            items[category] = add_line_item(plan["id"], acquirer_id, category, committed)

        for category, (annual, final_year) in EXPECTED_TARGETS.items():
            item = items[category]
            assert_line_item(item)
            assert item["annual_target_usd"] == annual, (
                f"{category} annual target should be {annual}, got {item['annual_target_usd']}"
            )
            assert item["final_year_target_usd"] == final_year, (
                f"{category} final-year target should be {final_year}, "
                f"got {item['final_year_target_usd']}"
            )
            reconciled = annual * (TERM_YEARS - 1) + final_year
            assert reconciled == item["committed_usd"], (
                f"{category} loses or invents dollars: {reconciled} != {item['committed_usd']}"
            )

    def test_02_the_plan_sums_the_floored_annual_targets_rather_than_flooring_the_sum(self):
        """PRD §3.9: "Adding a line item also recomputes three plan aggregates:
        `total_committed_usd` as the sum of `committed_usd` across the plan's line items,
        `annual_target_total_usd` as the sum of the individual `annual_target_usd` values — each
        floored first, then summed, never the other way round — and `quarterly_target_total_usd` as
        `annual_target_total_usd` divided by the four quarters of a year, floored to a whole dollar."

        Design: Corner/calculations/commitment_pro_rata_final_year_absorbs_every_floor_remainder
        """
        world = application_under_review()
        acquirer_id = world["acquirer"]["id"]
        plan = propose_plan(world["application"]["id"], acquirer_id, term_years=TERM_YEARS,
                            measurement_basis="CUMULATIVE_TO_DATE")
        for category, committed in STANDARD_LINE_ITEMS:
            add_line_item(plan["id"], acquirer_id, category, committed)

        stored = read_plan(plan["id"])

        assert_benefits_plan(stored)
        assert stored["total_committed_usd"] == 392_000_000
        assert stored["annual_target_total_usd"] == 130_666_666, (
            "83,333,333 + 40,000,000 + 2,333,333 + 5,000,000 sums the already-floored targets"
        )

    def test_03_the_quarterly_target_floors_the_half_dollar_at_execution(self):
        """PRD §3.9: "Adding a line item also recomputes three plan aggregates:
        `total_committed_usd` as the sum of `committed_usd` across the plan's line items,
        `annual_target_total_usd` as the sum of the individual `annual_target_usd` values — each
        floored first, then summed, never the other way round — and `quarterly_target_total_usd` as
        `annual_target_total_usd` divided by the four quarters of a year, floored to a whole dollar."
        PRD §3.9: "Execution freezes `total_committed_usd`, `annual_target_total_usd` and
        `quarterly_target_total_usd` from the line items as they stand at that moment, sets
        `compliance_status` to `COMPLIANT`, sets `credited_to_date_usd` to 0 and sets
        `remaining_commitment_usd` to `total_committed_usd`."

        Design: Corner/calculations/quarterly_target_total_floors_the_half_dollar
        """
        world = application_under_review()
        acquirer_id = world["acquirer"]["id"]
        plan = propose_plan(world["application"]["id"], acquirer_id, term_years=TERM_YEARS,
                            measurement_basis="CUMULATIVE_TO_DATE")
        for category, committed in STANDARD_LINE_ITEMS:
            add_line_item(plan["id"], acquirer_id, category, committed)

        executed = execute_plan(plan["id"], acquirer_id)

        assert executed["status"] == "EXECUTED"
        assert executed["annual_target_total_usd"] == 130_666_666
        assert executed["quarterly_target_total_usd"] == 32_666_666, (
            "the exact quarter is 32,666,666.50, and flooring keeps 32,666,666"
        )
        assert executed["credited_to_date_usd"] == 0
        assert executed["remaining_commitment_usd"] == 392_000_000
        assert executed["compliance_status"] == "COMPLIANT"


class TestScheduleInputSetFiltering:
    """Only the current regulatory schedule is read by the submission gate."""

    def test_04_a_superseded_undercapitalized_schedule_never_gates_the_filing(self):
        """PRD §3.3: "Building a new schedule on a basis moves the prior current schedule of that
        same basis to `SUPERSEDED`, and increments the application's `version` by 1."
        PRD §3.4: "Finally that schedule's `capital_adequacy_flag` must be `WELL_CAPITALIZED`, and
        any weaker flag yields `ERR_PRO_FORMA_CAPITAL_INSUFFICIENT`."

        Design: Corner/calculations/superseded_schedule_never_gates_the_submission
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        weak = create_undercapitalized_schedule(application_id, acquirer_id, expected_version=1)
        strong = create_regulatory_schedule(application_id, acquirer_id, expected_version=2)

        submitted = submit_application(application_id, acquirer_id)

        assert submitted["filing_status"] == "SUBMITTED", (
            "the gate reads only the CURRENT schedule, so the superseded one never refuses"
        )
        weak = read_schedule(weak["id"])
        assert_pro_forma_schedule(weak)
        assert weak["status"] == "SUPERSEDED"
        assert weak["pro_forma_cet1_ratio_pct"] == pytest.approx(0.28, abs=0.005), (
            f"Expected 0.28, got {weak['pro_forma_cet1_ratio_pct']} on the heavier adjustments"
        )
        assert weak["capital_adequacy_flag"] == "UNDERCAPITALIZED"
        strong = read_schedule(strong["id"])
        assert strong["status"] == "CURRENT"
        assert strong["pro_forma_cet1_ratio_pct"] == pytest.approx(7.74, abs=0.005), (
            f"Expected 7.74, got {strong['pro_forma_cet1_ratio_pct']}"
        )
        assert strong["pro_forma_tier1_leverage_pct"] == pytest.approx(6.52, abs=0.005), (
            f"Expected 6.52, got {strong['pro_forma_tier1_leverage_pct']}"
        )
        assert strong["capital_adequacy_flag"] == "WELL_CAPITALIZED"


class TestMarketClassThresholds:
    """The post-merger ceiling is chosen from the market's class, not from the arithmetic."""

    def test_05_a_rural_county_ceiling_clears_a_level_an_msa_would_flag(self):
        """PRD §3.5: "The post-merger ceiling depends on the market class: 1800 for a market whose
        `market_type` is `MSA`, and 2200 for a market whose `market_type` is `RURAL_COUNTY`."
        PRD §3.5: "First, if `hhi_post_unmitigated` is strictly below that ceiling, `screen_result`
        is `PASS`."
        PRD §3.5: "When `screen_result` is `PASS`, `required_divestiture_deposits_usd` is 0."

        Design: Corner/calculations/rural_county_threshold_clears_a_market_an_msa_would_flag
        """
        world = pinehill_rural_world()
        market = read_market(world["market"]["id"])
        assert market["total_deposits_usd"] == 1_000_000_000
        assert market["participant_count"] == 6

        response = api_client.create_competitive_analysis(
            {"application_id": world["application"]["id"], "market_id": world["market"]["id"]},
            ANALYST,
        )
        analysis = validate_success(response, 201)

        assert_competitive_analysis(analysis)
        assert analysis["hhi_pre_merger"] == 1750
        assert analysis["hhi_post_unmitigated"] == 2050
        assert analysis["hhi_delta_unmitigated"] == 300
        assert analysis["screen_result"] == "PASS", (
            "2050 is strictly below the 2200 rural ceiling, even though a delta of 300 "
            "would fail the delta branch"
        )
        assert analysis["required_divestiture_deposits_usd"] == 0
        application = read_application(world["application"]["id"], world["acquirer"]["id"])
        assert application["competitive_posture"] == "CLEARED"


class TestRequiredDivestitureIsPinned:
    """The step-4 requirement is fixed by the unmitigated screen and never relaxed."""

    def test_06_designating_mitigation_does_not_relax_the_required_amount(self):
        """PRD §3.5: "Steps 1 through 3 look only at current ownership and the unmitigated merger;
        steps 4 through 6 layer mitigation on top and never revisit the first three."
        PRD §3.5: "`mitigation_satisfied` is true when two things both hold:
        `designated_divestiture_deposits_usd` is at least `required_divestiture_deposits_usd`,
        **and** either `hhi_post_mitigated` is strictly below the market's ceiling or
        `hhi_post_mitigated` less `hhi_pre_merger` is at most 200."
        PRD §3.5: "Otherwise, if any analysis has a `screen_result` other than `PASS`, the posture is
        `CLEARED_WITH_DIVESTITURE` — a market that failed its screen but is fully mitigated still
        unblocks the case while recording that divestiture was needed."

        Design: Corner/calculations/required_divestiture_stays_pinned_to_the_unmitigated_screen_after_mitigation
        """
        world = granite_market_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        analysis_id = world["analysis"]["id"]
        assert world["analysis"]["required_divestiture_deposits_usd"] == 139_000_000, (
            "139,000,000 is the smallest whole million whose trial delta falls to at most 200"
        )

        branch = designate_for_divestiture(world["branch_target"]["id"], application_id,
                                           acquirer_id)

        assert branch["status"] == "DESIGNATED_FOR_DIVESTITURE"
        assert branch["designation_application_id"] == application_id
        analysis = read_analysis(analysis_id)
        assert analysis["hhi_pre_merger"] == 3800, "step 1 is untouched by the designation"
        assert analysis["hhi_post_unmitigated"] == 5000
        assert analysis["hhi_delta_unmitigated"] == 1200
        assert analysis["screen_result"] == "PRESUMPTIVE_VIOLATION"
        assert analysis["required_divestiture_deposits_usd"] == 139_000_000, (
            "the requirement stays pinned to the step-3 inputs rather than relaxing to 0"
        )
        assert analysis["designated_divestiture_deposits_usd"] == 200_000_000
        assert analysis["hhi_post_mitigated"] == 3800
        assert analysis["mitigation_satisfied"] is True
        assert read_application(application_id, acquirer_id)["competitive_posture"] == \
            "CLEARED_WITH_DIVESTITURE"
        market = read_market(world["market"]["id"])
        assert market["total_deposits_usd"] == 1_000_000_000, (
            "a designated branch is still includable"
        )
        assert market["participant_count"] == 3

    def test_07_redesignating_the_same_branch_reaches_a_fixed_point(self):
        """PRD §3.6: "A branch that is not `OPEN` cannot be designated, an attempt yielding
        `ERR_INVALID_BRANCH_STATE`."
        PRD §3.5: "`designated_divestiture_deposits_usd` is the sum of `deposits_usd` over the
        branches in this market whose `status` is `DESIGNATED_FOR_DIVESTITURE` and whose
        `designation_application_id` equals this application."

        Design: Corner/calculations/required_divestiture_stays_pinned_to_the_unmitigated_screen_after_mitigation
        """
        world = granite_market_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        branch_id = world["branch_target"]["id"]
        designate_for_divestiture(branch_id, application_id, acquirer_id)

        response = api_client.designate_branch(
            branch_id,
            {"application_id": application_id, "designation_type": "DIVESTITURE"},
            make_filer_headers(acquirer_id),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_BRANCH_STATE.value, 409)
        assert read_branch(branch_id)["status"] == "DESIGNATED_FOR_DIVESTITURE"
        analysis = read_analysis(world["analysis"]["id"])
        assert analysis["designated_divestiture_deposits_usd"] == 200_000_000, (
            "the refused second designation double-counts nothing"
        )
        assert analysis["hhi_post_mitigated"] == 3800
        assert analysis["required_divestiture_deposits_usd"] == 139_000_000
        assert analysis["mitigation_satisfied"] is True


class TestReportBasisAndFulfilment:
    """A report freezes the plan's measurement basis at the instant it is filed."""

    def test_08_the_report_copies_the_plans_annual_pro_rata_basis(self):
        """PRD §3.12: "The report also copies the plan's `measurement_basis` at filing time onto
        itself, and that copy, not the plan's later value, decides the outcome."
        PRD §3.12: "Under the `ANNUAL_PRO_RATA` basis, each quarter is judged on its own: fulfilment
        is the report's `credited_usd` divided by the plan's frozen `quarterly_target_total_usd`,
        multiplied by 100 and rounded half-up to two decimal places."
        PRD §3.12: "The value under the report's own `measurement_basis` is stored as
        `fulfillment_pct`; the value under the other basis is stored as
        `alternate_fulfillment_pct`, which is disclosure only and never drives an outcome."

        Design: Corner/calculations/report_copies_the_plan_measurement_basis_at_filing_time
        """
        world = application_under_review()
        acquirer_id = world["acquirer"]["id"]
        executed = executed_standard_plan(world["application"]["id"], acquirer_id,
                                          measurement_basis="ANNUAL_PRO_RATA",
                                          term_years=TERM_YEARS)
        plan_id = executed["plan"]["id"]
        assert executed["plan"]["quarterly_target_total_usd"] == 32_666_666

        report = file_report(plan_id, acquirer_id, "2027Q1", 1, {
            "MORTGAGE_LENDING": 20_000_000,
            "SMALL_BUSINESS_LENDING": 5_000_000,
        })

        assert_performance_report(report)
        assert report["measurement_basis"] == "ANNUAL_PRO_RATA", (
            "the basis is copied from the plan rather than defaulted to CUMULATIVE_TO_DATE"
        )
        assert report["credited_usd"] == 25_000_000
        assert report["excess_uncredited_usd"] == 0
        assert report["fulfillment_pct"] == pytest.approx(76.53, abs=0.005), (
            f"Expected 76.53, got {report['fulfillment_pct']} against a 32,666,666 quarter"
        )
        assert report["alternate_fulfillment_pct"] == pytest.approx(76.53, abs=0.005), (
            "the two bases coincide at period_index 1"
        )
        assert report["status"] == "FILED"
        plan = read_plan(plan_id)
        assert plan["credited_to_date_usd"] == 0, "filing does not move the plan ledger"
        assert plan["remaining_commitment_usd"] == 392_000_000
        assert plan["filed_report_count"] == 0


class TestWaitingPeriodStacking:
    """A granted hearing and an unresolved protest both add to the base period."""

    def test_09_hearing_and_protest_additions_stack_and_defeat_expediting(self):
        """PRD §3.10: "The base period is 30 days when the `structure` is `HOLDCO_ACQUISITION` and 15
        days for either bank-level structure."
        PRD §3.10: "Adjustments are then applied to the base: 15 days are added when a hearing has
        been granted, 10 days are added when the `unresolved_protest_count` is greater than 0, and 10
        days are subtracted when `expedited_processing` is true."
        PRD §3.10: "`consummation_window_open_at` is `decided_at` advanced by `waiting_period_days`
        whole days, and consummation is permitted at that instant inclusive."
        PRD §3.10: "`consummation_deadline_at` is `decided_at` advanced by 180 whole days, and
        consummation is permitted through that instant inclusive."

        Design: Corner/calculations/waiting_period_stacks_hearing_and_protest_additions_without_expediting
        """
        world = application_under_review()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        set_clock("2026-08-10T00:00:00Z")
        comment = file_substantive_protest(world["period"]["id"])
        petition = request_hearing(application_id, comment["id"])
        decide_hearing(petition["id"], outcome="GRANTED",
                       rationale="The lending record warrants a public hearing.")
        close_comment_period(world["period"]["id"])
        set_clock("2026-10-15T00:00:00Z")
        recommend_application(application_id, "APPROVE_WITH_CONDITIONS")

        decision = issue_decision(application_id, "CONDITIONALLY_APPROVED")

        assert_approval_decision(decision)
        assert decision["expedited_processing"] is False, (
            "a granted hearing and an unresolved protest each disqualify expediting"
        )
        assert decision["waiting_period_days"] == 40, (
            "15 days of bank-level base plus 15 for the hearing plus 10 for the protest"
        )
        assert_same_instant(decision["decided_at"], "2026-10-15T00:00:00Z", "decided_at")
        assert_same_instant(decision["consummation_window_open_at"], "2026-11-24T00:00:00Z",
                            "consummation_window_open_at")
        assert_same_instant(decision["consummation_deadline_at"], "2027-04-13T00:00:00Z",
                            "consummation_deadline_at")
        assert decision["status"] == "ISSUED"
        application = read_application(application_id, acquirer_id)
        assert application["filing_status"] == "DECIDED"
        assert application["public_review_status"] == "COMMENT_CLOSED", (
            "the protest is still unresolved, so the review dimension never reached CLEARED"
        )
