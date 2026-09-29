"""Money derivation: the unitary charge, the drawdown waterfall and handback sizing."""
from test_helpers import api_client, validate_success
from test_helpers.assertions import (
    assert_concession,
    assert_drawdown_milestone,
    assert_drawdown_split_sums,
)
from test_helpers.constants import FINANCIAL_CLOSE_DATE
from test_helpers.factories import financial_close_payload, handback_survey_payload
from test_helpers.fixtures import (
    ALPHA,
    CERTIFIER,
    LENDER,
    approve_milestone,
    list_deduction_events_for_period,
    refresh_concession,
    refresh_service_period,
    request_milestone,
    setup_concession_in_construction,
    setup_drafted_concession,
    setup_verified_period,
)


class TestMonthlyUnitaryChargeDerivation:
    def test_charge_indexes_the_monthly_quotient_before_its_single_rounding_step(self):
        """Financial close derives the charge from a 100,000,000 cent annual payment.

        PRD: "Take the Maximum Annual Service Payment in cents, divide it by the
        twelve months of the contract year, multiply the resulting quotient by one
        plus the indexation fraction, and round that single composed expression half
        up to a whole cent."

        Design: Difficulty/combinatorial_formula/monthly_unitary_charge_indexes_before_dividing_and_rounds_once
        """
        ctx = setup_drafted_concession()

        response = api_client.financial_close(
            ctx["concession_id"], financial_close_payload(FINANCIAL_CLOSE_DATE), ALPHA
        )

        concession = validate_success(response)
        assert_concession(concession)
        # 100000000 / 12 = 8333333.333..., uplifted by 1.0325 = 8604166.66..., one
        # rounding step half up at the end. Rounding the quotient first yields
        # 8333333 * 1.0325 = 8604166.2 -> 8604166, one cent low.
        assert concession["monthly_unitary_charge_cents"] == 8604167
        assert concession["status"] == "FINANCIAL_CLOSE"
        assert concession["financial_close_date"] == FINANCIAL_CLOSE_DATE
        assert concession["version"] == 2

    def test_a_smaller_project_shows_the_rounding_step_falling_the_other_way(self):
        """A second concession sized at 8,000,000 cents rounds down, not up.

        PRD: "There is exactly one rounding step and it comes last."

        Design: Difficulty/combinatorial_formula/monthly_unitary_charge_indexes_before_dividing_and_rounds_once
        """
        ctx = setup_drafted_concession(
            legal_name="Tarn Valley Roads Holdco",
            sponsor_equity_commitment_cents=10000000,
            project_name="Tarn Valley Link",
            masp_cents=8000000,
            total_project_cost_cents=40000000,
            senior_debt_committed_cents=30000000,
            equity_committed_cents=10000000,
            base_case_equity_irr_bps=1100,
            scheduled_service_commencement="2027-06-01",
            ld_daily_rate_cents=40000,
            ld_cap_cents=800000,
            lifecycle_reserve_target_cents=2000000,
        )

        response = api_client.financial_close(
            ctx["concession_id"], financial_close_payload(FINANCIAL_CLOSE_DATE), ALPHA
        )

        concession = validate_success(response)
        # 8000000 / 12 = 666666.666..., uplifted by 1.0325 = 688333.33... -> 688333.
        # Rounding the quotient to 666667 first would give 688334, one cent high.
        assert concession["monthly_unitary_charge_cents"] == 688333
        assert concession["status"] == "FINANCIAL_CLOSE"


class TestDrawdownEquityFirstWaterfall:
    def test_the_first_milestone_is_split_by_the_lower_of_the_two_equity_ceilings(self):
        """A 120,000,000 cent certified cost fills the committed-equity bucket first.

        PRD: "The size of the equity bucket is the lower of two independently
        sourced ceilings: thirty per cent of the certified total project cost,
        rounded half up to a whole cent, and the equity actually committed at
        financial close."

        Design: Difficulty/combinatorial_formula/drawdown_split_applies_two_ceilings_in_pinned_order
        """
        ctx = setup_concession_in_construction()

        milestone = ctx["milestone"]
        assert_drawdown_milestone(milestone)
        # 30% of 400000000 is 120000000; committed equity is 100000000; the lower
        # of the two ceilings governs, so equity absorbs only 100000000.
        assert milestone["equity_portion_cents"] == 100000000
        assert milestone["debt_portion_cents"] == 20000000
        assert_drawdown_split_sums(milestone)
        assert milestone["status"] == "DISBURSED"

    def test_a_second_milestone_finds_the_equity_bucket_empty_and_draws_only_debt(self):
        """With the equity ceiling already reached, the whole cost goes to debt.

        PRD: "The room still left in that bucket is the ceiling less the equity
        already drawn, floored at zero."

        Design: Difficulty/combinatorial_formula/drawdown_split_applies_two_ceilings_in_pinned_order
        """
        ctx = setup_concession_in_construction()
        refresh_concession(ctx)
        second = request_milestone(ctx, "M2 Structures Complete", 60000000)
        approve_milestone(ctx, second["id"], 60000000)

        response = api_client.disburse_drawdown_milestone(second["id"], LENDER)

        milestone = validate_success(response)
        assert milestone["equity_portion_cents"] == 0
        assert milestone["debt_portion_cents"] == 60000000
        assert_drawdown_split_sums(milestone)
        assert milestone["status"] == "DISBURSED"
        concession = refresh_concession(ctx)
        assert concession["equity_drawn_cents"] == 100000000
        assert concession["senior_debt_drawn_cents"] == 80000000
        assert (
            concession["equity_drawn_cents"] + concession["senior_debt_drawn_cents"]
            == 180000000
        )


class TestHandbackRequiredReserveSinglePass:
    def test_the_penalty_is_sized_from_the_pre_penalty_shortfall_only(self):
        """A 12,000,000 cent rectification cost against an 8,000,000 cent reserve.

        PRD: "The penalty is fifteen per cent of that pre-penalty shortfall,
        rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/handback_required_reserve_is_single_pass_not_a_fixed_point
        """
        ctx = setup_verified_period()

        response = api_client.handback_survey(
            ctx["concession_id"], handback_survey_payload("2027-04-05", 12000000), CERTIFIER
        )

        concession = validate_success(response)
        assert_concession(concession)
        # pre-penalty shortfall 12000000 - 8000000 = 4000000; penalty 600000;
        # required 12600000. Re-basing the penalty on the new shortfall would
        # converge on 12690000 or higher.
        assert concession["handback_required_reserve_cents"] == 12600000
        assert concession["handback_shortfall_cents"] == 4600000
        assert concession["handback_status"] == "FAILED"
        assert concession["lifecycle_reserve_balance_cents"] == 8000000

    def test_the_failed_survey_charges_the_shortfall_to_the_last_verified_period(self):
        """The shortfall becomes a points-denominated deduction the period cap truncates.

        PRD: "The system appends one deduction event of `deduction_type`
        `HANDBACK_SHORTFALL` against the concession's most recent verified service
        period, meaning the one with the highest `period_index` among those whose
        reporting axis has reached `VERIFIED`, sized so that its raw amount
        reproduces the shortfall exactly: its `points` are the shortfall divided by
        the 1,250-cent point value, rounded half up to a whole point."

        Design: Difficulty/combinatorial_formula/handback_required_reserve_is_single_pass_not_a_fixed_point
        """
        ctx = setup_verified_period()

        api_client.handback_survey(
            ctx["concession_id"], handback_survey_payload("2027-04-05", 12000000), CERTIFIER
        )

        rows, meta = list_deduction_events_for_period(ctx["service_period_id"])
        assert meta["total_count"] == 1
        event = rows[0]
        assert event["deduction_type"] == "HANDBACK_SHORTFALL"
        assert event["points"] == 3680
        assert event["raw_amount_cents"] == 4600000
        assert event["allowed_amount_cents"] == 1720833
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 1720833
        assert period["net_payment_cents"] == 6883334
