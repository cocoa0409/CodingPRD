"""The two allocation bases and the subsidy draw that follows a period close."""

from test_helpers import (
    ApiErrorId,
    AllocationBasis,
    BusinessLineStatus,
    SubsidyPeriodStatus,
    assert_hours,
    assert_per_hour_cents,
    assert_ratio,
    assert_subsidy_period,
    fixtures,
    make_funder_analyst_headers,
    validate_error,
    validate_success,
)


class TestAllocationBasisVariants:
    """One September ledger of 371800 cents, read under each allocation basis."""

    def test_hours_basis_reports_mission_share_of_0_2308(self, api):
        """The hours basis divides trainee hours by trainee plus supervisor hours.

        "Under the **hours basis**, which is what an `OPEN` period always uses and
        what a what-if analysis requested on the hours basis reports,
        `mission_share` is `trainee_hours` divided by the sum of `trainee_hours`
        and `supervisor_hours`, rounded half up to four decimal places" — with
        trainee hours of 12.000 against supervisor hours of 40.0 that is 0.2308,
        and the PRD states the resulting `mission_cost_cents` of 85810 for this
        exact ledger.

        Design: Difficulty/dual_variant_calc/subsidy_allocation_hours_vs_revenue_split_same_ledger
        """
        program = fixtures.closed_period_program(api)
        period_id = program["subsidy_period"]["id"]

        response = api.get_true_cost_analysis(
            period_id,
            make_funder_analyst_headers(),
            {"allocation_basis": AllocationBasis.HOURS},
        )
        analysis = validate_success(response)

        assert analysis["subsidy_period_id"] == period_id
        assert analysis["allocation_basis"] == AllocationBasis.HOURS
        assert_ratio(analysis["mission_share"], 0.2308, "mission_share")
        assert analysis["mission_cost_cents"] == 85810
        assert analysis["business_operating_cost_cents"] == 285990
        assert analysis["total_cost_cents"] == 371800
        assert_hours(analysis["trainee_hours"], 12.000, "trainee_hours")
        assert_per_hour_cents(
            analysis["true_cost_per_trainee_hour_cents"],
            30983.33,
            "true_cost_per_trainee_hour_cents",
        )
        assert_per_hour_cents(
            analysis["subsidy_per_trainee_hour_cents"],
            7150.83,
            "subsidy_per_trainee_hour_cents",
        )

    def test_revenue_basis_reports_mission_share_of_0_3276(self, api):
        """The revenue basis reads mission cost as the unfunded fraction of spend.

        "Under the **revenue basis**, used when a period closes on that basis and
        when a what-if analysis on a closed period requests it, `mission_share` is
        one minus `revenue_cents` divided by gross cost, floored at zero and
        rounded half up to four decimal places" — the PRD works this exact ledger
        through and states that "the revenue basis yields a `mission_share` of
        0.3276 and `mission_cost_cents` of 116766".

        Design: Difficulty/dual_variant_calc/subsidy_allocation_hours_vs_revenue_split_same_ledger
        """
        program = fixtures.closed_period_program(api)

        response = api.get_true_cost_analysis(
            program["subsidy_period"]["id"],
            make_funder_analyst_headers(),
            {"allocation_basis": AllocationBasis.REVENUE},
        )
        analysis = validate_success(response)

        assert analysis["allocation_basis"] == AllocationBasis.REVENUE
        assert_ratio(analysis["mission_share"], 0.3276, "mission_share")
        assert analysis["mission_cost_cents"] == 116766
        assert analysis["business_operating_cost_cents"] == 255034
        assert analysis["total_cost_cents"] == 371800
        assert_hours(analysis["trainee_hours"], 12.000, "trainee_hours")
        assert_per_hour_cents(
            analysis["true_cost_per_trainee_hour_cents"],
            30983.33,
            "true_cost_per_trainee_hour_cents",
        )
        assert_per_hour_cents(
            analysis["subsidy_per_trainee_hour_cents"],
            9730.50,
            "subsidy_per_trainee_hour_cents",
        )

    def test_what_if_basis_does_not_move_the_stored_ledger(self, api):
        """Asking the revenue what-if leaves the period frozen on its own basis.

        "An `allocation_basis` may be supplied to ask the what-if question,
        defaulting to the period's own stored basis; the answer never persists, so
        asking the question does not move the ledger."

        Design: Difficulty/dual_variant_calc/subsidy_allocation_hours_vs_revenue_split_same_ledger
        """
        program = fixtures.closed_period_program(api)
        period_id = program["subsidy_period"]["id"]

        validate_success(
            api.get_true_cost_analysis(
                period_id,
                make_funder_analyst_headers(),
                {"allocation_basis": AllocationBasis.REVENUE},
            )
        )

        stored = fixtures.read_subsidy_period(api, period_id)
        assert_subsidy_period(stored)
        assert stored["allocation_basis"] == AllocationBasis.HOURS
        assert_ratio(stored["mission_share"], 0.2308, "mission_share")
        assert stored["mission_cost_cents"] == 85810
        assert stored["business_operating_cost_cents"] == 285990
        assert stored["total_cost_cents"] == 371800


class TestSubsidyDrawTier:
    """The draw is chosen from the pre-subsidy margin, in the pinned order."""

    def test_margin_from_pre_subsidy_business_cost_selects_the_0_90_tier(self, api):
        """The margin is taken before any subsidy is drawn.

        "The margin is taken from the *pre-subsidy* position: `margin_pct` is
        negative 1.0000 when `revenue_cents` is zero, and otherwise `revenue_cents`
        minus `business_operating_cost_cents`, divided by `revenue_cents`, rounded
        half up to four decimal places" and "`subsidy_rate` is chosen from that
        **rounded** margin: 0.50 when `margin_pct` is at least 0.2000, 0.70 when
        `margin_pct` is at least 0.0500 but below 0.2000, and 0.90 when
        `margin_pct` is below 0.0500."

        Design: Difficulty/combinatorial_formula/subsidy_draw_tier_from_presubsidy_margin_ordering
        """
        program = fixtures.canonical_ledger_program(api)
        fixtures.set_clock(api, "2026-10-01T00:00:00Z")

        closed = fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 250000
        )

        assert closed["status"] == SubsidyPeriodStatus.CLOSED
        assert closed["business_operating_cost_cents"] == 285990
        assert_ratio(closed["margin_pct"], -0.1440, "margin_pct")
        assert closed["subsidy_rate"] == 0.90

    def test_draw_is_mission_cost_times_rate_and_accrues_on_the_line(self, api):
        """The draw is a consequence of the margin, never an input to it.

        "`subsidy_draw_cents` is then `mission_cost_cents` multiplied by
        `subsidy_rate`, rounded half up to whole cents." and "the business line's
        `cumulative_subsidy_cents` is re-derived as the sum of `subsidy_draw_cents`
        over all `CLOSED` periods of that line."

        Design: Difficulty/combinatorial_formula/subsidy_draw_tier_from_presubsidy_margin_ordering
        """
        program = fixtures.canonical_ledger_program(api)
        fixtures.set_clock(api, "2026-10-01T00:00:00Z")

        closed = fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 250000
        )

        assert closed["mission_cost_cents"] == 85810
        assert closed["subsidy_draw_cents"] == 77229
        assert closed["subsidy_draw_cents"] != 60067

        line = fixtures.read_business_line(api, program["business_line"]["id"])
        assert line["cumulative_subsidy_cents"] == 77229
        assert line["status"] == BusinessLineStatus.LAUNCHED


class TestRevenueBasisRequiresRevenue:
    """A revenue-basis question is unanswerable while the period has no revenue."""

    def test_revenue_basis_on_an_open_period_is_refused(self, api):
        """An open period has no revenue, so the revenue what-if has no input.

        "Asking for the revenue basis on a period that has no `revenue_cents` at
        all is refused with `ERR_REVENUE_NOT_AVAILABLE`."

        Design: Difficulty/dual_variant_calc/subsidy_allocation_hours_vs_revenue_split_same_ledger
        """
        program = fixtures.canonical_ledger_program(api)

        response = api.get_true_cost_analysis(
            program["subsidy_period"]["id"],
            make_funder_analyst_headers(),
            {"allocation_basis": AllocationBasis.REVENUE},
        )

        validate_error(response, ApiErrorId.ERR_REVENUE_NOT_AVAILABLE)
