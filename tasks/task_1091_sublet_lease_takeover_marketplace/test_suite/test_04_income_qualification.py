"""Income qualification: STANDARD ratio vs STRICT multiple, and the 40x boundary."""
import pytest
from test_helpers import (
    set_clock, new_landlord, new_leaseholder, new_applicant, new_verified_lease,
    new_open_listing, new_application, screen_application,
)


class TestIncomeQualificationRatioVsMultiple:
    """Difficulty: dual_variant_calc — the STANDARD ratio and STRICT multiple variants
    can disagree for identical income/rent inputs."""

    def _setup_two_policies(self, api):
        set_clock(api)
        landlord = new_landlord(api)
        leaseholder = new_leaseholder(api)
        applicant = new_applicant(api, annual_income_cents=11000000, monthly_debt_cents=0, credit_score=700)
        lease = new_verified_lease(api, landlord, leaseholder,
                                   monthly_rent_cents=300000, security_deposit_cents=500000, allows_sublet=True)
        listing_std = new_open_listing(api, lease, leaseholder, landlord,
                                       listing_type="SUBLET", asking_rent_cents=300000,
                                       min_term_months=2, screening_policy="STANDARD")
        listing_strict = new_open_listing(api, lease, leaseholder, landlord,
                                          listing_type="SUBLET", asking_rent_cents=300000,
                                          min_term_months=2, screening_policy="STRICT")
        app_std = new_application(api, listing_std, applicant,
                                  proposed_move_in_date="2026-06-01", proposed_move_out_date="2026-08-31")
        app_strict = new_application(api, listing_strict, applicant,
                                     proposed_move_in_date="2026-06-01", proposed_move_out_date="2026-08-31")
        report_std = screen_application(api, app_std, credit_score=700)
        report_strict = screen_application(api, app_strict, credit_score=700)
        return report_std, report_strict

    def test_standard_ratio_passes(self, api):
        """PRD §3.3: "Under the `STANDARD` policy, the qualification uses the ratio
        variant: the `qualification_result` is `PASS` when the affordability ratio is at
        most the maximum rent-to-income ratio of 0.35, and `FAIL` otherwise".

        Design: Difficulty/dual_variant_calc/income_qualification_ratio_vs_multiple
        """
        report_std, _ = self._setup_two_policies(api)
        assert report_std["qualification_result"] == "PASS", "STANDARD ratio 0.3273 <= 0.35 must PASS"
        assert report_std["affordability_ratio"] == pytest.approx(0.3273, abs=1e-6)

    def test_strict_multiple_fails_for_same_inputs(self, api):
        """PRD §3.3: "Under the `STRICT` policy, the qualification uses the
        income-multiple variant: the result is `PASS` when the income multiple is at
        least 40, and `FAIL` otherwise".

        Design: Difficulty/dual_variant_calc/income_qualification_ratio_vs_multiple
        """
        _, report_strict = self._setup_two_policies(api)
        assert report_strict["qualification_result"] == "FAIL", "STRICT multiple 36.6667 < 40 must FAIL"
        assert report_strict["income_multiple"] == pytest.approx(36.6667, abs=1e-6)


class TestIncomeMultipleExact40xBoundary:
    """Difficulty: boundary_precision_check — the STRICT income-multiple threshold at
    exactly 40x."""

    def _setup_strict_pair(self, api):
        set_clock(api)
        landlord = new_landlord(api)
        leaseholder = new_leaseholder(api)
        ap_pass = new_applicant(api, name="AP1", email="ap1@x.com", annual_income_cents=12000000, credit_score=720)
        ap_fail = new_applicant(api, name="AP2", email="ap2@x.com", annual_income_cents=11999999, credit_score=720)
        lease = new_verified_lease(api, landlord, leaseholder,
                                   monthly_rent_cents=300000, allows_sublet=True)
        listing = new_open_listing(api, lease, leaseholder, landlord,
                                   listing_type="SUBLET", asking_rent_cents=300000,
                                   min_term_months=2, screening_policy="STRICT")
        app_pass = new_application(api, listing, ap_pass,
                                   proposed_move_in_date="2026-06-01", proposed_move_out_date="2026-08-31")
        app_fail = new_application(api, listing, ap_fail,
                                   proposed_move_in_date="2026-06-01", proposed_move_out_date="2026-08-31")
        report_pass = screen_application(api, app_pass, credit_score=720)
        report_fail = screen_application(api, app_fail, credit_score=720)
        return report_pass, report_fail

    def test_income_exactly_40x_passes(self, api):
        """PRD §3.3: "the result is `PASS` when the income multiple is at least 40, and
        `FAIL` otherwise". PRD §2.7: "the qualifying comparison that consumes it is
        evaluated at full precision before that rounding".

        Design: Difficulty/boundary_precision_check/income_multiple_exact_40x_boundary
        """
        report_pass, _ = self._setup_strict_pair(api)
        assert report_pass["income_multiple"] == pytest.approx(40.0, abs=1e-6)
        assert report_pass["qualification_result"] == "PASS", "income exactly 40x must PASS"

    def test_income_just_below_40x_fails(self, api):
        """PRD §3.3: "the result is `PASS` when the income multiple is at least 40, and
        `FAIL` otherwise". PRD §2.7: "the qualifying comparison that consumes it is
        evaluated at full precision before that rounding".

        Design: Difficulty/boundary_precision_check/income_multiple_exact_40x_boundary
        """
        _, report_fail = self._setup_strict_pair(api)
        assert report_fail["qualification_result"] == "FAIL", "income one cent below 40x must FAIL"
