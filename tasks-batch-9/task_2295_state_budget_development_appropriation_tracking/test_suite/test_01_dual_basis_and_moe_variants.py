"""Two figures computed from one row: the two balance bases and the two MOE bases."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_two_bases,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_success,
)


class TestAppropriationBalanceBases:
    def test_balance_summary_reports_both_bases_and_their_delta(self, api, budget_analyst_headers):
        """PRD §3.7: "The **cash basis**, `available_cash_cents`, is `released_cents` minus `expended_cents`."
        PRD §3.7: "The **authority basis**, `available_authority_cents`, is current authority minus `expended_cents`."
        PRD §3.7: "A read-only balance summary exposes both side by side, reporting `appropriation_id`, `authority_cents` (the current authority figure), `released_cents`, `expended_cents`, `available_cash_cents`, `available_authority_cents`, and `basis_delta_cents`, the last being `available_authority_cents` minus `available_cash_cents`."

        Design: Difficulty/dual_variant_calc/available_balance_cash_basis_vs_authority_basis_diverge
        """
        ctx = fixtures.setup_appropriation_with_released_cash(requested_cents=400_000_000)
        appropriation = ctx["appropriation"]

        response = api.get_appropriation_balance_summary(
            appropriation["id"], budget_analyst_headers
        )
        summary = validate_success(response, 200)

        assert summary["released_cents"] == 400_000_000
        assert summary["expended_cents"] == 0
        assert summary["authority_cents"] == 2_000_000_000
        assert summary["available_cash_cents"] == 400_000_000
        assert summary["available_authority_cents"] == 2_000_000_000
        assert summary["basis_delta_cents"] == 1_600_000_000
        assert_two_bases(appropriation)

    def test_charge_clearing_authority_but_not_released_cash_is_rejected_on_the_cash_basis(
        self, api, budget_analyst_headers
    ):
        """PRD §3.7: "Posting an expenditure is checked against **both**, authority first: a charge exceeding `available_authority_cents` is `ERR_APPROPRIATION_OVERSPEND`, and a charge that clears authority but exceeds `available_cash_cents` is `ERR_INSUFFICIENT_CASH_RELEASED`."
        PRD §2.12: "The charge fits within the appropriation's `available_cash_cents` — otherwise `ERR_INSUFFICIENT_CASH_RELEASED` (422)."

        Design: Difficulty/dual_variant_calc/available_balance_cash_basis_vs_authority_basis_diverge
        """
        ctx = fixtures.setup_appropriation_with_released_cash(requested_cents=400_000_000)
        appropriation = ctx["appropriation"]

        response = api.create_expenditure(
            {
                "appropriation_id": appropriation["id"],
                "quarter": 1,
                "amount_cents": 500_000_000,
                "object_code": "6100",
                "vendor_reference": "INV-9001",
            },
            make_agency_officer_headers(ctx["agency"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_CASH_RELEASED, 422)

        after = fixtures.read_appropriation(appropriation["id"])
        assert after["expended_cents"] == 0
        assert after["available_cash_cents"] == 400_000_000
        assert after["available_authority_cents"] == 2_000_000_000


class TestMaintenanceOfEffortBases:
    @staticmethod
    def _grant_with_leaner_prior_years():
        ctx = fixtures.setup_appropriation_with_released_cash(
            requested_cents=400_000_000, expenditure_cents=300_000_000
        )
        grant = fixtures.record_federal_grant(
            ctx["agency"]["id"],
            ctx["cycle"]["id"],
            award_cents=400_000_000,
            moe_baseline_cents=300_000_000,
            required_match_ratio=0.25,
            moe_prior_year1_spend_cents=250_000_000,
            moe_prior_year2_spend_cents=200_000_000,
        )
        return ctx, grant

    def test_single_year_basis_counts_current_spend_alone_and_is_compliant(
        self, api, budget_analyst_headers
    ):
        """PRD §3.8: "Under `SINGLE_YEAR` the assessed spend is `moe_current_spend_cents` alone, so a state that front-loads the current year passes."
        PRD §3.8: "The verdict compares integers, never the reported ratio: `moe_compliance_status` is `COMPLIANT` when the assessed spend is greater than or equal to `moe_baseline_cents` — exact equality is compliant — and `DEFICIENT` otherwise."

        Design: Difficulty/dual_variant_calc/moe_single_year_vs_three_year_average_flips_verdict
        """
        _ctx, grant = self._grant_with_leaner_prior_years()

        response = api.assess_grant_moe(
            grant["id"], {"basis": "SINGLE_YEAR"}, budget_analyst_headers
        )
        assessed = validate_success(response, 200)

        assert assessed["moe_current_spend_cents"] == 300_000_000
        assert assessed["moe_compliance_status"] == "COMPLIANT"
        assert assessed["moe_compliance_ratio"] == pytest.approx(1.000000, abs=1e-9)
        assert assessed["moe_assessed_basis"] == "SINGLE_YEAR"
        assert assessed["required_state_match_cents"] == 100_000_000

    def test_three_year_average_basis_lowers_the_assessed_figure_and_flips_to_deficient(
        self, api, budget_analyst_headers
    ):
        """PRD §3.8: "Under `THREE_YEAR_AVERAGE` the assessed spend is the sum of `moe_current_spend_cents`, `moe_prior_year1_spend_cents`, and `moe_prior_year2_spend_cents` divided by three, rounded half up to the cent before any comparison; identical current-year data therefore yields a lower assessed figure whenever the prior years were leaner, and the same grant can be `COMPLIANT` under one basis and `DEFICIENT` under the other."
        PRD §3.8: "The assessment also writes `moe_compliance_ratio`, the assessed spend divided by `moe_baseline_cents` rounded half up to 6 decimal places, and records the basis used in `moe_assessed_basis`."

        Design: Difficulty/dual_variant_calc/moe_single_year_vs_three_year_average_flips_verdict
        """
        _ctx, grant = self._grant_with_leaner_prior_years()

        first = validate_success(
            api.assess_grant_moe(grant["id"], {"basis": "SINGLE_YEAR"}, budget_analyst_headers),
            200,
        )
        assert first["moe_compliance_status"] == "COMPLIANT"

        second = validate_success(
            api.assess_grant_moe(
                grant["id"], {"basis": "THREE_YEAR_AVERAGE"}, budget_analyst_headers
            ),
            200,
        )

        assert second["moe_current_spend_cents"] == 300_000_000
        assert second["moe_compliance_status"] == "DEFICIENT"
        assert second["moe_compliance_ratio"] == pytest.approx(0.833333, abs=1e-9)
        assert second["moe_assessed_basis"] == "THREE_YEAR_AVERAGE"
        assert second["required_state_match_cents"] == 100_000_000
