"""Renewal pricing and the season revenue analysis."""

import pytest

from test_helpers import (
    BRONZE,
    GOLD,
    ApiErrorId,
    GateCode,
    ProgramStatus,
    VisitStatus,
    assert_revenue_summary,
    build_active_pass,
    build_program,
    close_visit,
    compliance_officer_headers,
    create_park_day,
    create_program,
    get_pass,
    get_passholder,
    program_admin_headers,
    record_visit,
    renewal_quote,
    revenue_summary,
    set_clock,
    validate_error,
    validate_success,
    clerk_headers,
)


def _five_visit_bronze_pass(api):
    program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SEASON_ACTIVE.value)
    days = [
        create_park_day(api, program.id, f"2026-09-0{index}")
        for index in range(1, 6)
    ]
    pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
    for index, day in enumerate(days, start=1):
        record_visit(
            api, pass_ctx.id, day["id"], f"2026-09-0{index}T10:00:00Z", GateCode.NORTH.value
        )
    return program, pass_ctx


class TestRenewalQuotePricing:
    """The quote is four movements: price, discount, credit, total."""

    def test_inside_the_early_bird_window_the_discount_and_the_credit_both_apply(
        self, api, default_clock
    ):
        """The worked example of the contract: 30000 becomes 25500 and then 24000.

        PRD: "Worked through: a target Gold tier at 30000 cents, with the logical clock at
        the first of November 2026 and the programme's `early_bird_deadline` at the
        fifteenth, and a prior pass with a `visit_count` of 6 — early bird applies, the
        discount is 4500, the discounted price is 25500, the raw retention credit is 1500,
        the cap is twenty percent of 25500 truncated, which is 5100, so the credit stays 1500
        and the quoted price is 24000."

        Design: Corner/calculations/renewal_quote_applies_early_bird_then_capped_retention_credit
        """
        program, pass_ctx = _five_visit_bronze_pass(api)
        assert get_pass(api, pass_ctx.id)["visit_count"] == 5, (
            "the guest should have five recorded entries for the mid-band credit"
        )
        set_clock(api, "2026-11-01T00:00:00Z")

        quote = renewal_quote(api, pass_ctx.id, program.tier_id("GOLD"))

        assert quote["standard_price_cents"] == 30000, (
            f"the standard price is the target tier list price, got {quote['standard_price_cents']!r}"
        )
        assert quote["early_bird_applied"] is True, (
            "the first of November is inside a window closing on the fifteenth"
        )
        assert quote["discounted_price_cents"] == 25500, (
            f"30000 less fifteen percent is 25500, got {quote['discounted_price_cents']!r}"
        )
        assert quote["retention_credit_cents"] == 1500, (
            "five visits earn the 1500-cent band, under the 5100 cap, got "
            f"{quote['retention_credit_cents']!r}"
        )
        assert quote["quoted_price_cents"] == 24000, (
            f"25500 less the 1500 credit is 24000, got {quote['quoted_price_cents']!r}"
        )
        assert get_passholder(api, pass_ctx.holder_id)["sharing_risk_score"] == 0, (
            "five entries outside the trailing window score nothing"
        )

    def test_one_day_past_the_deadline_the_discount_drops_but_the_credit_stays(
        self, api, default_clock
    ):
        """The deadline is inclusive, so the sixteenth is outside the window.

        PRD: "`early_bird_applied` is true when the logical clock's current date is on or
        before the programme's `early_bird_deadline`, the deadline day itself counting as
        inside the window, and false otherwise."

        Design: Corner/calculations/renewal_quote_applies_early_bird_then_capped_retention_credit
        """
        program, pass_ctx = _five_visit_bronze_pass(api)
        set_clock(api, "2026-11-16T00:00:00Z")

        quote = renewal_quote(api, pass_ctx.id, program.tier_id("GOLD"))

        assert quote["early_bird_applied"] is False, (
            "one day past the deadline the early-bird window has closed"
        )
        assert quote["discounted_price_cents"] == 30000, (
            f"without the discount the price stands at the list price, got {quote['discounted_price_cents']!r}"
        )
        assert quote["retention_credit_cents"] == 1500, (
            "the loyalty credit is unaffected by the deadline, got "
            f"{quote['retention_credit_cents']!r}"
        )
        assert quote["quoted_price_cents"] == 28500, (
            f"30000 less the 1500 credit is 28500, got {quote['quoted_price_cents']!r}"
        )


class TestSpendSetCountsOnlyClosedVisits:
    """The visit set and the spend set are different sets."""

    def test_an_open_visit_counts_as_a_visit_but_not_as_spend(self, api, default_clock):
        """The open visit raises the visit count and stays out of the spend average.

        PRD: "The **spend set** is the visit set restricted to visits whose `status` is
        `CLOSED`."

        Design: Corner/calculations/revenue_spend_set_counts_only_closed_visits
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-09-01")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        first = record_visit(
            api, pass_ctx.id, day["id"], "2026-09-01T10:00:00Z", GateCode.NORTH.value
        )
        second = record_visit(
            api, pass_ctx.id, day["id"], "2026-09-01T12:00:00Z", GateCode.SOUTH.value
        )

        closed = close_visit(api, first["id"], 4000)

        assert closed["status"] == VisitStatus.CLOSED.value, (
            f"closing the visit should move it to CLOSED, got {closed['status']!r}"
        )
        assert closed["spend_cents"] == 4000, (
            f"the posted spend should be stored, got {closed['spend_cents']!r}"
        )
        assert closed["discount_applied_pct"] == pytest.approx(0.05, abs=0.0001), (
            "the entering tier's discount should be snapshotted onto the visit, got "
            f"{closed['discount_applied_pct']!r}"
        )
        still_open = validate_success(api.get_visit(second["id"], headers=clerk_headers()))
        assert still_open["status"] == VisitStatus.OPEN.value, (
            f"the second visit should still be OPEN, got {still_open['status']!r}"
        )
        assert still_open["spend_cents"] == 0, (
            f"an open visit has posted no spend, got {still_open['spend_cents']!r}"
        )
        assert_revenue_summary(
            revenue_summary(api, program.id),
            active_passes=1,
            visits=2,
            visits_per_active_pass=2.00,
            spend=4000,
            spend_per_visit=4000,
        )


class TestRevenueAnalysisPrecision:
    """One response carries a rounded rate and a floored rate."""

    def test_the_visit_rate_rounds_half_up_while_the_spend_rate_floors(self, api, default_clock):
        """Five visits over three passes is 1.67; 2001 over two visits is 1000.

        PRD: "`visits_per_active_pass` is `total_visit_count` divided by
        `active_pass_count`, rounded half up to two decimal places, except that when
        `active_pass_count` is zero the figure is reported as `0.00` rather than dividing."

        Design: Corner/calculations/revenue_analysis_rounds_visit_rate_and_floors_spend_rate
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        first_day = create_park_day(api, program.id, "2026-09-01")
        second_day = create_park_day(api, program.id, "2026-09-02")
        holders = []
        for label in ("a", "b", "c"):
            holders.append(
                build_active_pass(
                    api,
                    program,
                    tier_name="BRONZE",
                    holder_overrides={"email": f"rate-{label}@example.com"},
                )
            )
        first_visits = [
            record_visit(
                api, holder.id, first_day["id"], "2026-09-01T10:00:00Z", GateCode.NORTH.value
            )
            for holder in holders
        ]
        for holder in holders[:2]:
            record_visit(
                api, holder.id, second_day["id"], "2026-09-02T10:00:00Z", GateCode.NORTH.value
            )
        close_visit(api, first_visits[0]["id"], 1000)
        close_visit(api, first_visits[1]["id"], 1001)

        summary = revenue_summary(api, program.id)

        assert_revenue_summary(
            summary,
            base=36000,
            recognized=36000,
            deferred=0,
            forfeited=0,
            active_passes=3,
            visits=5,
            visits_per_active_pass=1.67,
            spend=2001,
            spend_per_visit=1000,
        )

    def test_a_programme_with_no_passes_reports_the_zero_denominator_guards(
        self, api, default_clock
    ):
        """Neither rate divides by zero; both report their pinned guard value.

        PRD: "`spend_per_visit_cents` is `total_in_park_spend_cents` divided by the number
        of members of the spend set, truncated down to a whole number of cents, except that
        when the spend set is empty the figure is reported as `0` rather than dividing."

        Design: Corner/calculations/revenue_analysis_rounds_visit_rate_and_floors_spend_rate
        """
        empty = create_program(api, season_year=2028, park_name="Quiet Ridge")

        summary = revenue_summary(api, empty["id"])

        assert_revenue_summary(
            summary,
            base=0,
            recognized=0,
            deferred=0,
            forfeited=0,
            active_passes=0,
            visits=0,
            visits_per_active_pass=0.00,
            spend=0,
            spend_per_visit=0,
        )


class TestTheRevenueSummaryIsAReadOnlyProjection:
    """One paid pass and nothing else: every figure follows from the four sets."""

    def _one_paid_pass_programme(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        build_active_pass(api, program, tier_name="BRONZE")
        return program

    def test_a_single_paid_pass_reports_base_equal_to_recognized_with_nothing_deferred(
        self, api, default_clock
    ):
        """A PAY_IN_FULL pass has paid its whole contract value, so nothing is outstanding.

        PRD: "`base_revenue_cents` is the sum of `contract_value_cents` over the revenue
        set."

        Design: Corner/endpoints/revenue_summary_is_a_computed_read_over_the_program
        """
        program = self._one_paid_pass_programme(api)

        summary = revenue_summary(api, program.id)

        assert_revenue_summary(
            summary,
            base=12000,
            recognized=12000,
            deferred=0,
            forfeited=0,
            active_passes=1,
            visits=0,
            visits_per_active_pass=0.00,
            spend=0,
            spend_per_visit=0,
        )

    def test_reading_it_twice_changes_nothing_and_both_permitted_roles_may_read(
        self, api, default_clock
    ):
        """The analysis is derived on demand, and the role list is closed.

        PRD: "A `ProgramAdmin` or a `ComplianceOfficer` reads the programme's revenue and
        visitation analysis, which is computed over four explicitly-defined sets."

        Design: Corner/endpoints/revenue_summary_is_a_computed_read_over_the_program
        """
        program = self._one_paid_pass_programme(api)
        before = validate_success(
            api.get_pass_program(program.id, headers=program_admin_headers())
        )

        first = revenue_summary(api, program.id)
        second = revenue_summary(api, program.id)

        assert first == second, "two identical reads should return the identical body"
        after = validate_success(
            api.get_pass_program(program.id, headers=program_admin_headers())
        )
        assert after["version"] == before["version"], (
            f"a read must not bump the programme's version, got {after['version']!r}"
        )
        officer = validate_success(
            api.get_revenue_summary(program.id, headers=compliance_officer_headers())
        )
        assert officer == first, "the compliance officer should see the same analysis"
        validate_error(
            api.get_revenue_summary(program.id, headers=clerk_headers()),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
