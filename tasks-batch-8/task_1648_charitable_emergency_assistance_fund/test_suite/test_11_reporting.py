"""Donor/grant reporting and household benefit summaries: the two measurement
bases (exposure vs committed, cash vs encumbrance), the benefit-year window,
and the per-category / households-served report fields."""
from test_helpers import (
    ApiErrorId,
    clear_payment,
    create_active_policy,
    create_funding_source,
    create_household,
    create_vendor,
    drive_application_to_approved,
    issue_payment,
    set_clock,
    setup_approved,
    TEST_USERS,
    validate_success,
)

PM1 = TEST_USERS["program_manager_headers"]
AUD1 = TEST_USERS["auditor_headers"]


class TestHouseholdBenefitSummaryBases:
    def _split_payment_setup(self):
        """One RENT award of 35000; 20000 of it CLEARED, 15000 still ISSUED."""
        ctx = setup_approved(
            requested_amount_cents=35000,
            source_overrides={"total_budget_cents": 200000},
        )
        pay1 = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 20000,
            payment_date="2026-08-02T00:00:00Z",
        )
        issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 15000,
            payment_date="2026-08-03T00:00:00Z",
        )
        clear_payment(pay1["id"])
        return ctx

    def test_exposure_counts_full_award_committed_counts_cleared_only(self, api):
        """PRD §3.9: "Two measurement bases diverge here deliberately: the
        exposure basis counts the full `awarded_amount_cents` of every
        non-`VOIDED` award in the benefit-year set, including approved-but-unpaid
        amounts, while the committed basis counts only `consumed_cents` across
        those awards' allocations — money actually cleared — so the two differ
        whenever an award is approved but not yet fully paid."

        Design: Difficulty/dual_variant_calc/household_exposure_vs_committed_variants
        """
        ctx = self._split_payment_setup()
        summary = validate_success(
            api.get_benefit_summary(ctx["household"]["id"], AUD1), 200
        )
        assert summary["ytd_exposure_cents"] == 35000
        assert summary["ytd_committed_cents"] == 20000
        assert summary["ytd_exposure_cents"] != summary["ytd_committed_cents"], (
            "the two bases must diverge while a payment is still ISSUED"
        )

    def test_remaining_caps_derived_from_exposure_basis(self, api):
        """PRD §3.5: "The remaining annual cap is the pinned policy's
        `max_annual_benefit_cents` minus the year-to-date exposure, and the
        remaining category cap is `rent_cap_cents` or `utility_cap_cents` minus
        the matching category figure."
        PRD §3.9: "A household's benefit summary answers with the current
        `benefit_year`, the household's `ytd_exposure_cents` and
        `ytd_committed_cents`, the `remaining_annual_cap_cents`, the per-category
        `rent_ytd_cents` and `utility_ytd_cents`, and the
        `remaining_rent_cap_cents` and `remaining_utility_cap_cents`, all
        evaluated against the currently `ACTIVE` policy."

        Design: Difficulty/dual_variant_calc/household_exposure_vs_committed_variants
        """
        ctx = self._split_payment_setup()
        summary = validate_success(
            api.get_benefit_summary(ctx["household"]["id"], AUD1), 200
        )
        assert summary["benefit_year"] == 2026
        assert summary["rent_ytd_cents"] == 35000
        assert summary["utility_ytd_cents"] == 0
        assert summary["remaining_annual_cap_cents"] == 100000 - 35000
        assert summary["remaining_rent_cap_cents"] == 50000 - 35000
        assert summary["remaining_utility_cap_cents"] == 40000


class TestSourceUtilizationBases:
    def _reserved_unpaid_setup(self):
        """Source B budget 100000 holding a fully-unpaid 40000 award."""
        return setup_approved(
            requested_amount_cents=40000,
            source_overrides={
                "name": "Grant B", "funder_name": "Rotary",
                "source_type": "GRANT_RESTRICTED", "total_budget_cents": 100000,
            },
            household_overrides={
                "head_of_household_name": "Ben Osei", "annual_income_cents": 900000,
            },
        )

    def test_cash_zero_while_encumbrance_reflects_reservation(self, api):
        """PRD §3.9: "The cash utilization percentage is `committed_cents`
        divided by `total_budget_cents` and expressed as a percentage; the
        encumbrance utilization percentage uses committed plus reserved as its
        numerator and is strictly greater than the cash figure whenever any
        `RESERVED` allocation is not fully consumed — the cash basis serves donor
        statements while the encumbrance basis serves grant pipeline reporting."

        Design: Difficulty/dual_variant_calc/source_cash_vs_encumbrance_utilization
        """
        ctx = self._reserved_unpaid_setup()
        report = validate_success(
            api.get_funding_source_report(ctx["source"]["id"], AUD1), 200
        )
        assert report["committed_cents"] == 0
        assert report["reserved_cents"] == 40000
        assert report["cash_utilization_pct"] == 0.0
        assert report["encumbrance_utilization_pct"] == 40.0
        assert report["households_served"] == 0

    def test_bases_converge_once_the_award_is_fully_paid(self, api):
        """PRD §3.9: "The cash utilization percentage is `committed_cents`
        divided by `total_budget_cents` and expressed as a percentage; the
        encumbrance utilization percentage uses committed plus reserved as its
        numerator and is strictly greater than the cash figure whenever any
        `RESERVED` allocation is not fully consumed — the cash basis serves donor
        statements while the encumbrance basis serves grant pipeline reporting."
        PRD §3.9: "`households_served` counts the distinct households with at
        least one `CLEARED` payment drawn on this source whose `cleared_at` falls
        inside the half-open funding period — a payment cleared exactly at
        `period_end` is excluded."

        Design: Difficulty/dual_variant_calc/source_cash_vs_encumbrance_utilization
        """
        ctx = self._reserved_unpaid_setup()
        payment = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], ctx["source"]["id"], 40000
        )
        clear_payment(payment["id"])
        report = validate_success(
            api.get_funding_source_report(ctx["source"]["id"], AUD1), 200
        )
        # Fully consumed: no RESERVED remainder, so the bases meet at 40.0.
        assert report["cash_utilization_pct"] == 40.0
        assert report["encumbrance_utilization_pct"] == 40.0
        assert report["households_served"] == 1


class TestBenefitYearWindow:
    def test_benefit_year_rollover_resets_household_caps(self, api):
        """PRD §2.4: "An award's benefit year is the four-digit UTC calendar year
        of the logical clock at the moment of approval, stored as the integer
        `benefit_year`. All per-year caps group awards by this stored integer;
        the grouping is never recomputed from other dates."
        PRD §3.5: "Household benefit usage is then measured over the household's
        current benefit-year award set — every award of that household in
        `ACTIVE`, `PARTIALLY_DISBURSED`, or `DISBURSED` status (`VOIDED` awards
        are excluded) whose `benefit_year` equals the logical clock's current
        calendar year."

        Design: Corner/calculations/benefit_year_rollover_resets_household_caps
        """
        create_active_policy(rent_cap_cents=60000)
        vendor = create_vendor("LANDLORD")
        household = create_household()
        create_funding_source(
            name="GF", total_budget_cents=200000,
            period_start="2026-01-01T00:00:00Z", period_end="2027-06-30T00:00:00Z",
        )
        set_clock("2026-12-20T00:00:00Z")
        approved = drive_application_to_approved(
            household["id"], vendor["id"], requested_amount_cents=40000,
            service_month="2026-12",
        )
        assert approved["award"]["benefit_year"] == 2026
        set_clock("2027-01-05T00:00:00Z")
        summary = validate_success(api.get_benefit_summary(household["id"], PM1), 200)
        assert summary["benefit_year"] == 2027
        assert summary["ytd_exposure_cents"] == 0, (
            "the 2026 award is outside the 2027 benefit-year window"
        )
        assert summary["remaining_annual_cap_cents"] == 100000, (
            "caps reset fully at the calendar-year boundary"
        )
        award = validate_success(api.get_award(approved["award"]["id"], PM1), 200)
        assert award["benefit_year"] == 2026, "the stored benefit year never migrates"


class TestSourceReportComposition:
    def test_report_category_split_and_households_served_half_open(self, api):
        """PRD §3.9: "`rent_committed_cents` and `utility_committed_cents` sum
        `consumed_cents` over allocations whose award's application falls in the
        matching category. `households_served` counts the distinct households
        with at least one `CLEARED` payment drawn on this source whose
        `cleared_at` falls inside the half-open funding period — a payment
        cleared exactly at `period_end` is excluded."

        Design: Corner/calculations/report_category_split_and_households_served_half_open
        """
        create_active_policy(rent_cap_cents=60000)
        landlord = create_vendor("LANDLORD")
        utility = create_vendor(vendor_type="UTILITY", name="City Power & Light")
        household1 = create_household(head_of_household_name="Rep One")
        household2 = create_household(head_of_household_name="Rep Two")
        source = create_funding_source(
            name="RPT", funder_name="Funder RPT", source_type="GRANT_RESTRICTED",
            period_start="2026-01-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
            total_budget_cents=200000,
        )
        # HH1: RENT award 10000, payment cleared mid-period.
        first = drive_application_to_approved(
            household1["id"], landlord["id"], requested_amount_cents=10000,
            service_month="2026-08",
        )
        p1 = issue_payment(
            first["award"]["id"], landlord["id"], source["id"], 10000,
            payment_date="2026-08-05T00:00:00Z",
        )
        set_clock("2026-08-05T12:00:00Z")
        clear_payment(p1["id"])
        # HH2: UTILITY award 8000, payment cleared mid-period.
        second = drive_application_to_approved(
            household2["id"], utility["id"], category="UTILITY",
            requested_amount_cents=8000, service_month="2026-08",
        )
        p2 = issue_payment(
            second["award"]["id"], utility["id"], source["id"], 8000,
            payment_date="2026-08-10T00:00:00Z",
        )
        set_clock("2026-08-10T12:00:00Z")
        clear_payment(p2["id"])
        # HH1 again: RENT award 5000 cleared exactly AT period_end.
        third = drive_application_to_approved(
            household1["id"], landlord["id"], requested_amount_cents=5000,
            service_month="2026-09",
        )
        p3 = issue_payment(
            third["award"]["id"], landlord["id"], source["id"], 5000,
            payment_date="2026-08-20T00:00:00Z",
        )
        set_clock("2026-09-01T00:00:00Z")  # exactly period_end
        clear_payment(p3["id"])
        report = validate_success(
            api.get_funding_source_report(source["id"], AUD1), 200
        )
        assert report["committed_cents"] == 23000, (
            "all consumed allocations count toward committed, regardless of period"
        )
        assert report["rent_committed_cents"] == 15000
        assert report["utility_committed_cents"] == 8000
        assert report["households_served"] == 2, (
            "the payment cleared exactly at period_end falls outside the "
            "half-open window and its household is not counted for it"
        )
