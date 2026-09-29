"""Freezing a demand basis: which forecasts qualify, and how they are weighted.

Sizing is an aggregation with a filter on its input set and a single rounding on
its output; both halves are observable through `consumption_basis_gallons`.
"""

from test_helpers import (
    ANALYST,
    ERR_NO_FORECAST_BASIS,
    assert_program_coverage,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

CORNER_POLICY = dict(
    policy_code="FY27-CORNER",
    min_coverage_pct=5.00,
    max_single_counterparty_pct=100.00,
    max_earnings_volatility_usd=500000.00,
)


def _publish(api, **overrides):
    return fx.do_create_published_forecast(api, **overrides)


class TestSeasonWeighting:
    @staticmethod
    def _size_a_programme_over_all_four_seasons(api):
        policy = fx.do_create_policy(api, **CORNER_POLICY)
        _publish(
            api,
            fleet_type="NARROWBODY",
            route_group="DOMESTIC_SHORT",
            season="WINTER",
            forecast_gallons=1000000,
        )
        _publish(
            api,
            fleet_type="NARROWBODY",
            route_group="DOMESTIC_LONG",
            season="SPRING",
            forecast_gallons=5000000,
        )
        _publish(
            api,
            fleet_type="WIDEBODY",
            route_group="TRANSATLANTIC",
            season="SUMMER",
            forecast_gallons=2000000,
        )
        _publish(
            api,
            fleet_type="REGIONAL",
            route_group="DOMESTIC_SHORT",
            season="FALL",
            forecast_gallons=1000000,
        )
        program = fx.do_create_program(
            api,
            policy["id"],
            program_code="HP-SEASONS",
            route_groups=["DOMESTIC_SHORT", "DOMESTIC_LONG", "TRANSATLANTIC"],
            target_coverage_pct=30.00,
        )
        return validate_success(api.size_hedge_program(program["id"], headers=ANALYST))

    def test_each_forecast_carries_its_own_season_factor_into_the_sum(self, api):
        """PRD §3.3: "each forecast contributes its `forecast_gallons` multiplied
        by a seasonal weighting: `WINTER` counts at 1.00, `SPRING` at 0.95,
        `SUMMER` at 1.10 and `FALL` at 0.98."

        1,000,000 at 1.00 plus 5,000,000 at 0.95 plus 2,000,000 at 1.10 plus
        1,000,000 at 0.98 is 8,930,000 — neither the 9,000,000 an unweighted sum
        would give nor anything a single averaged factor could produce.

        Design: Corner/calculations/sizing_applies_one_season_factor_per_forecast_then_rounds_once
        """
        data = self._size_a_programme_over_all_four_seasons(api)

        assert data["status"] == "SIZING"
        assert_program_coverage(data, consumption_basis_gallons=8930000)

    def test_sizing_only_freezes_demand_and_bumps_the_programme_version(self, api):
        """PRD §3.3: "Those products are summed without any intermediate rounding,
        and the single sum is then rounded to whole gallons and written to
        `consumption_basis_gallons`, overwriting whatever a previous sizing run
        had left there. Sizing also recomputes the programme's three coverage
        percentages and increments the programme's `version` by one."

        With no instruments on the programme all three percentages recompute to
        zero, and the create-then-size pair leaves the version at 2.

        Design: Corner/calculations/sizing_applies_one_season_factor_per_forecast_then_rounds_once
        """
        data = self._size_a_programme_over_all_four_seasons(api)

        assert data["version"] == 2
        assert_program_coverage(
            data,
            coverage_pct_notional=0.00,
            coverage_pct_delta=0.00,
            planned_coverage_pct_delta=0.00,
        )


class TestBasisInputFiltering:
    @staticmethod
    def _four_decoys_and_one_qualifying_forecast(api):
        policy = fx.do_create_policy(
            api,
            policy_code="FY27-FILTER",
            min_coverage_pct=5.00,
            max_single_counterparty_pct=100.00,
            max_earnings_volatility_usd=500000.00,
            eligible_fleet_types=["NARROWBODY"],
        )
        qualifying = _publish(
            api,
            fleet_type="NARROWBODY",
            route_group="DOMESTIC_SHORT",
            season="SUMMER",
            forecast_gallons=4000000,
        )
        # Left in DRAFT. Its fleet, route group and window all qualify, so
        # status is the only clause excluding it. PRD §3.3 forbids publishing a
        # forecast whose half-open interval intersects a PUBLISHED sibling with
        # the same fleet_type *and* route_group, so this row sits on
        # DOMESTIC_LONG over 2027-01 up to (but not including) 2027-03 — it
        # merely touches the 2027-03..2027-06 DOMESTIC_LONG decoy below and can
        # therefore be published later in the re-size test.
        draft = fx.do_create_forecast(
            api,
            fleet_type="NARROWBODY",
            route_group="DOMESTIC_LONG",
            season="WINTER",
            period_start_month="2027-01",
            period_end_month="2027-03",
            forecast_gallons=1000000,
        )
        # Fleet type outside the policy's eligible_fleet_types.
        _publish(
            api,
            fleet_type="WIDEBODY",
            route_group="DOMESTIC_SHORT",
            season="SUMMER",
            forecast_gallons=3000000,
        )
        # Route group outside the programme's route_groups.
        _publish(
            api,
            fleet_type="NARROWBODY",
            route_group="TRANSPACIFIC",
            season="SUMMER",
            forecast_gallons=2000000,
        )
        # Window runs past month_after(2027-03).
        _publish(
            api,
            fleet_type="NARROWBODY",
            route_group="DOMESTIC_LONG",
            season="SUMMER",
            period_start_month="2027-03",
            period_end_month="2027-06",
            forecast_gallons=500000,
        )
        program = fx.do_create_program(
            api,
            policy["id"],
            program_code="HP-FILTER",
            route_groups=["DOMESTIC_SHORT", "DOMESTIC_LONG"],
            target_coverage_pct=30.00,
        )
        return {"program": program, "draft": draft, "qualifying": qualifying}

    def test_a_forecast_enters_the_basis_only_when_all_four_clauses_hold(self, api):
        """PRD §3.3: "A forecast enters the basis only if all four of the
        following hold: its `status` is `PUBLISHED`; its `fleet_type` is one of
        the governing policy's `eligible_fleet_types`; its `route_group` is one
        of the programme's `route_groups`; and its month window sits wholly
        inside the programme's."

        PRD §3.3: "A forecast that only partially overlaps the programme window is
        excluded in its entirety; there is no pro-rating." Pro-rating the
        2027-03..2027-06 row would add 137,500 gallons.

        Design: Corner/calculations/sizing_input_set_excludes_draft_wrong_fleet_wrong_route_and_partial_window
        """
        ctx = self._four_decoys_and_one_qualifying_forecast(api)

        sized = fx.do_size_program(api, ctx["program"]["id"])

        assert sized["status"] == "SIZING"
        assert sized["version"] == 2
        assert_program_coverage(sized, consumption_basis_gallons=4400000)

    def test_publishing_the_held_back_draft_admits_it_on_a_re_size(self, api):
        """PRD §3.3: "Re-sizing is the only route by which a forecast published
        after an earlier sizing run enters an already-sized programme."

        The `DRAFT` row was excluded for status alone; once published it
        contributes its `WINTER` weighting of 1.00, taking the basis from
        4,400,000 to 5,400,000.

        Design: Corner/calculations/sizing_input_set_excludes_draft_wrong_fleet_wrong_route_and_partial_window
        """
        ctx = self._four_decoys_and_one_qualifying_forecast(api)
        fx.do_size_program(api, ctx["program"]["id"])

        fx.do_publish_forecast(api, ctx["draft"]["id"])
        resized = fx.do_size_program(api, ctx["program"]["id"])

        assert resized["status"] == "SIZING"
        assert_program_coverage(resized, consumption_basis_gallons=5400000)


class TestEmptyMatchedSet:
    def test_no_matching_forecast_is_an_error_rather_than_a_zero_basis(self, api):
        """PRD §3.3: "If no forecast matches, sizing fails with
        `ERR_NO_FORECAST_BASIS`."

        PRD §2.5: "**Forecast basis present** on programme sizing, otherwise
        `ERR_NO_FORECAST_BASIS` (422)."

        A zero basis would instead make every coverage percentage 0.00 and let
        every ceiling pass, so the programme must stay `DRAFT` with its basis
        still at its creation value.

        Design: Corner/calculations/size_with_empty_matched_set_returns_422_no_forecast_basis
        """
        policy = fx.do_create_policy(api, **CORNER_POLICY)
        _publish(api, fleet_type="NARROWBODY", route_group="DOMESTIC_SHORT")
        program = fx.do_create_program(
            api,
            policy["id"],
            program_code="HP-LATAM",
            route_groups=["LATAM"],
            target_coverage_pct=30.00,
        )

        validate_error(
            api.size_hedge_program(program["id"], headers=ANALYST),
            ERR_NO_FORECAST_BASIS,
            422,
        )

        after = fx.read_program(api, program["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] == 1
        assert_program_coverage(after, consumption_basis_gallons=0)
