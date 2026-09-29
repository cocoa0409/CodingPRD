"""Settling the note: conveyance events, released commitments and program income."""

import pytest

from test_helpers import (
    api_client,
    assert_program_year_ledger_conserved,
    assert_settlement_identity_conserved,
    recapture_payload,
    validate_success,
)
from test_helpers.fixtures import (
    PROGRAM_MANAGER,
    build_program_year,
    close_out_loan,
    record_lien,
    refresh_application,
    refresh_contractor,
    refresh_loan,
    refresh_program_year,
    run_paid_draw,
    set_clock,
    setup_case,
)

HVAC_LINE = {
    "description": "Furnace and distribution replacement",
    "category": "HVAC",
    "priority_class": "HEALTH_SAFETY",
    "estimated_cost_cents": 2_800_000,
    "is_lead_hazard_reduction": False,
    "is_historic_sensitive": False,
}
CODE_LINE = {
    "description": "Service panel grounding",
    "category": "ELECTRICAL",
    "priority_class": "CODE",
    "estimated_cost_cents": 200_000,
    "is_lead_hazard_reduction": False,
    "is_historic_sensitive": False,
}


def _settled_forgivable_case(program_year):
    """Walk one 3,025,000 forgivable note all the way to `SERVICING`."""
    case = setup_case(
        stage="lien_recorded",
        program_year=program_year,
        lines=[dict(HVAC_LINE)],
        bid_amount_cents=3_000_000,
        loan_overrides={"structure_type": "FORGIVABLE", "forgiveness_term_months": 60},
    )
    run_paid_draw(
        application_id=case["application"]["id"],
        loan_id=case["loan"]["id"],
        contractor_id=case["contractor"]["id"],
        requested_amount_cents=3_000_000,
        is_final_draw=True,
    )
    case["loan"] = close_out_loan(case["loan"]["id"], completion_date="2026-10-30")
    return case


def _settle(loan_id, recapture_event_type, **overrides):
    payload = recapture_payload(
        recapture_event_type, recapture_event_date="2028-10-30", **overrides
    )
    return validate_success(
        api_client.record_recapture(loan_id, payload, PROGRAM_MANAGER), 200
    )


class TestConveyanceVariants:
    """Two identical notes, two conveyance types, two different recoveries."""

    @pytest.fixture
    def shared_program_year(self):
        """One 2026 program year that both settled notes draw from."""
        return build_program_year()

    def test_a_sale_recovers_no_more_than_the_net_proceeds(self, shared_program_year):
        """Twenty-four of sixty months are forgiven and thin proceeds cap the rest.

        PRD: "On a `SALE`, the program shares in net proceeds and collects nothing
        beyond them. The payload additionally carries `sale_price_cents`,
        `closing_costs_cents` and `homeowner_investment_cents`.
        `net_proceeds_cents` is the sale price less the case's
        `senior_lien_balance_cents`, less the closing costs, less the homeowner
        investment, floored at zero. `recapture_amount_cents` is the lesser of
        `unforgiven_balance_cents` and `net_proceeds_cents`."

        Design: Difficulty/dual_variant_calc/sale_vs_transfer_recapture_variants_on_identical_forgivable_loans
        """
        case = _settled_forgivable_case(shared_program_year)
        assert case["loan"]["principal_cents"] == 3_025_000
        set_clock("2028-10-30T00:00:00Z")

        settled = _settle(
            case["loan"]["id"],
            "SALE",
            sale_price_cents=15_000_000,
            closing_costs_cents=900_000,
            homeowner_investment_cents=1_500_000,
        )

        assert settled["forgiven_cents"] == 1_210_000, (
            "Twenty-four of sixty months forgive 1,210,000 of the 3,025,000 "
            f"principal, got {settled['forgiven_cents']}"
        )
        assert settled["unforgiven_balance_cents"] == 1_815_000
        assert settled["net_proceeds_cents"] == 600_000, (
            "15,000,000 less the 12,000,000 senior lien, 900,000 of closing costs "
            f"and 1,500,000 of homeowner investment leaves 600,000, got "
            f"{settled['net_proceeds_cents']}"
        )
        assert settled["recapture_amount_cents"] == 600_000
        assert settled["shortfall_forgiven_cents"] == 1_215_000
        assert settled["status"] == "RECAPTURED"
        assert_settlement_identity_conserved(settled)

    def test_a_transfer_recovers_the_whole_unforgiven_balance(
        self, shared_program_year
    ):
        """With no proceeds to share, the program pursues the entire balance.

        PRD: "On a `TRANSFER`, a `REFINANCE` or a `RENTAL_CONVERSION` there are no
        sale proceeds to share. `net_proceeds_cents` is zero and
        `recapture_amount_cents` is the entire `unforgiven_balance_cents`,
        regardless of any value the property may hold."

        Design: Difficulty/dual_variant_calc/sale_vs_transfer_recapture_variants_on_identical_forgivable_loans
        """
        case = _settled_forgivable_case(shared_program_year)
        set_clock("2028-10-30T00:00:00Z")

        settled = _settle(case["loan"]["id"], "TRANSFER")

        assert settled["forgiven_cents"] == 1_210_000
        assert settled["unforgiven_balance_cents"] == 1_815_000
        assert settled["net_proceeds_cents"] == 0
        assert settled["recapture_amount_cents"] == 1_815_000, (
            "A transfer recovers the whole unforgiven balance, got "
            f"{settled['recapture_amount_cents']}"
        )
        assert settled["shortfall_forgiven_cents"] == 0
        assert settled["status"] == "RECAPTURED"
        assert_settlement_identity_conserved(settled)

    def test_the_two_events_post_different_program_income_from_one_principal(
        self, shared_program_year
    ):
        """The same 3,025,000 note yields 600,000 on a sale and 1,815,000 on a transfer.

        PRD: "`program_income_posted_cents` equals `recapture_amount_cents`, and
        the program year's `program_income_balance_cents` increases by that
        figure, raising `uncommitted_amount_cents` by the same amount and making
        the recaptured money available to the next household."

        Design: Difficulty/dual_variant_calc/sale_vs_transfer_recapture_variants_on_identical_forgivable_loans
        """
        sale_case = _settled_forgivable_case(shared_program_year)
        transfer_case = _settled_forgivable_case(shared_program_year)
        set_clock("2028-10-30T00:00:00Z")

        sold = _settle(
            sale_case["loan"]["id"],
            "SALE",
            sale_price_cents=15_000_000,
            closing_costs_cents=900_000,
            homeowner_investment_cents=1_500_000,
        )
        transferred = _settle(transfer_case["loan"]["id"], "TRANSFER")

        assert sold["principal_cents"] == transferred["principal_cents"] == 3_025_000
        assert sold["forgiven_cents"] == transferred["forgiven_cents"] == 1_210_000
        assert sold["program_income_posted_cents"] == 600_000
        assert transferred["program_income_posted_cents"] == 1_815_000
        program_year = refresh_program_year(shared_program_year["id"])
        assert program_year["program_income_balance_cents"] == 2_415_000, (
            "The two settlements post 600,000 and 1,815,000 of program income, "
            f"got {program_year['program_income_balance_cents']}"
        )
        assert_program_year_ledger_conserved(program_year)


class TestProgramYearMoneyTriad:
    """Allocation plus program income equals uncommitted plus committed plus disbursed."""

    @pytest.fixture
    def amortizing_case(self):
        """A 3,225,000 amortizing note at 300 basis points over 120 months."""
        return setup_case(
            stage="structured",
            lines=[dict(HVAC_LINE), dict(CODE_LINE)],
            bid_amount_cents=3_200_000,
            loan_overrides={
                "structure_type": "AMORTIZING",
                "interest_rate_bps": 300,
                "term_months": 120,
            },
        )

    def test_recording_the_lien_commits_the_principal_and_passes_the_fee_through(
        self, amortizing_case
    ):
        """Before the lien nothing is committed; after it the fee is already spent.

        PRD: "The following identity must hold after every write:
        `allocation_budget_cents` plus `program_income_balance_cents` equals the
        sum of `uncommitted_amount_cents`, `committed_amount_cents` and
        `disbursed_amount_cents`."

        Design: Difficulty/compensating_invariant/program_year_money_triad_is_conserved_across_lien_draws_and_close_out_release
        """
        case = amortizing_case
        assert case["loan"]["principal_cents"] == 3_225_000
        assert case["loan"]["monthly_payment_cents"] == 31_141, (
            "A 3,225,000 principal at 300 basis points over 120 months carries a "
            f"31,141 payment, got {case['loan']['monthly_payment_cents']}"
        )
        before = refresh_program_year(case["program_year"]["id"])
        assert (before["committed_amount_cents"], before["disbursed_amount_cents"]) == (
            0,
            0,
        )
        assert before["uncommitted_amount_cents"] == 50_000_000
        assert_program_year_ledger_conserved(before)

        record_lien(case["loan"]["id"])

        after = refresh_program_year(case["program_year"]["id"])
        assert after["committed_amount_cents"] == 3_200_000
        assert after["disbursed_amount_cents"] == 25_000
        assert after["uncommitted_amount_cents"] == 46_775_000
        assert_program_year_ledger_conserved(after)

    def test_the_two_draws_move_retainage_without_unbalancing_the_triad(
        self, amortizing_case
    ):
        """Retainage is withheld on the ordinary draw and rides out with the final one.

        PRD: "On a final draw, no new retainage is withheld — `retainage_cents` is
        zero — and all retainage held on the loan to date is released with this
        payment, so `net_payment_cents` is the approved amount plus the loan's
        current `retainage_held_cents`."

        Design: Difficulty/compensating_invariant/program_year_money_triad_is_conserved_across_lien_draws_and_close_out_release
        """
        case = amortizing_case
        record_lien(case["loan"]["id"])
        common = {
            "application_id": case["application"]["id"],
            "loan_id": case["loan"]["id"],
            "contractor_id": case["contractor"]["id"],
        }

        first = run_paid_draw(
            requested_amount_cents=2_000_000, is_final_draw=False, **common
        )

        assert first["retainage_cents"] == 200_000
        assert first["net_payment_cents"] == 1_800_000
        mid_loan = refresh_loan(case["loan"]["id"])
        assert mid_loan["contract_earned_cents"] == 2_000_000
        assert mid_loan["retainage_held_cents"] == 200_000
        assert mid_loan["disbursed_cents"] == 1_825_000
        assert mid_loan["status"] == "DISBURSING"
        mid_year = refresh_program_year(case["program_year"]["id"])
        assert mid_year["committed_amount_cents"] == 1_400_000
        assert mid_year["disbursed_amount_cents"] == 1_825_000
        assert mid_year["uncommitted_amount_cents"] == 46_775_000
        assert_program_year_ledger_conserved(mid_year)

        final = run_paid_draw(
            requested_amount_cents=1_000_000, is_final_draw=True, **common
        )

        assert final["retainage_cents"] == 0
        assert final["net_payment_cents"] == 1_200_000, (
            "The final draw carries its own 1,000,000 plus the 200,000 held back, "
            f"got {final['net_payment_cents']}"
        )
        end_loan = refresh_loan(case["loan"]["id"])
        assert end_loan["contract_earned_cents"] == 3_000_000
        assert end_loan["retainage_held_cents"] == 0
        assert end_loan["disbursed_cents"] == 3_025_000
        assert end_loan["status"] == "DISBURSING", (
            "3,025,000 disbursed against a 3,225,000 principal is not full "
            f"disbursement, got {end_loan['status']}"
        )
        end_year = refresh_program_year(case["program_year"]["id"])
        assert end_year["committed_amount_cents"] == 200_000
        assert end_year["disbursed_amount_cents"] == 3_025_000
        assert_program_year_ledger_conserved(end_year)

    def test_close_out_releases_the_unspent_commitment_and_rewrites_the_note(
        self, amortizing_case
    ):
        """The 200,000 never spent goes back to uncommitted and the payment falls.

        PRD: "Close-out releases the unspent commitment: the released amount is
        `principal_cents` less `disbursed_cents`, and the program year's
        `committed_amount_cents` decreases by exactly that figure."

        Design: Difficulty/compensating_invariant/program_year_money_triad_is_conserved_across_lien_draws_and_close_out_release
        """
        case = amortizing_case
        record_lien(case["loan"]["id"])
        common = {
            "application_id": case["application"]["id"],
            "loan_id": case["loan"]["id"],
            "contractor_id": case["contractor"]["id"],
        }
        run_paid_draw(requested_amount_cents=2_000_000, is_final_draw=False, **common)
        run_paid_draw(requested_amount_cents=1_000_000, is_final_draw=True, **common)

        closed = close_out_loan(case["loan"]["id"], completion_date="2026-11-30")

        assert closed["principal_cents"] == 3_025_000, (
            "The note is reset to the money actually spent, got "
            f"{closed['principal_cents']}"
        )
        assert closed["monthly_payment_cents"] == 29_210, (
            "The annuity is recomputed on the reduced principal, falling from "
            f"31,141 to 29,210, got {closed['monthly_payment_cents']}"
        )
        assert closed["status"] == "SERVICING"
        assert closed["forgiveness_start_date"].startswith("2026-11-30")
        program_year = refresh_program_year(case["program_year"]["id"])
        assert program_year["committed_amount_cents"] == 0
        assert program_year["disbursed_amount_cents"] == 3_025_000
        assert program_year["uncommitted_amount_cents"] == 46_975_000
        assert_program_year_ledger_conserved(program_year)
        application = refresh_application(case["application"]["id"])
        assert application["workflow_state"] == "CLOSED"
        assert application["warranty_expires_at"].startswith("2027-11-30")
        assert refresh_contractor(case["contractor"]["id"])["on_time_completion_count"] == 1
