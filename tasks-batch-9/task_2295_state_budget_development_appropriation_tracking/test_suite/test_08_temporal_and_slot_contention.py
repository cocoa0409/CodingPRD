"""Contended resources: the quarter release slot, adopted forecast windows, pledge capacity."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestQuarterSlotOccupancy:
    @staticmethod
    def _released_quarter_one():
        ctx = fixtures.setup_execution_cycle()
        released = fixtures.released_allotment(
            ctx["appropriation"]["id"], quarter=1, requested_cents=400_000_000
        )
        assert released["status"] == "RELEASED"
        assert released["released_cents"] == 400_000_000
        ctx["allotment"] = released
        return ctx

    def test_a_released_row_still_occupies_its_quarter_while_the_next_quarter_is_free(self, api):
        """PRD §3.5: "At most one live allotment may occupy a given appropriation-and-quarter slot: if another allotment on the same `appropriation_id` and `quarter` sits in `DRAFT`, `PREPARED`, `APPROVED`, or `RELEASED`, the creation is rejected with `ERR_ALLOTMENT_QUARTER_OCCUPIED`."
        PRD §3.5: "The requested quarter may be the current cycle quarter or a later one; naming an already-past quarter is `ERR_QUARTER_CLOSED`."
        PRD §2.12: "No other allotment on the same `appropriation_id` and `quarter` is in status `DRAFT`, `PREPARED`, `APPROVED`, or `RELEASED` — otherwise `ERR_ALLOTMENT_QUARTER_OCCUPIED` (409). Applies to `POST /fiscal/allotments`."

        Design: Difficulty/resource_temporal_overlap/allotment_quarter_slot_occupancy_survives_release_and_frees_on_recall
        """
        ctx = self._released_quarter_one()
        appropriation_id = ctx["appropriation"]["id"]

        blocked = api.create_allotment(
            {
                "appropriation_id": appropriation_id,
                "quarter": 1,
                "requested_cents": 10_000_000,
                "allow_partial": False,
            },
            fixtures.ANALYST,
        )
        validate_error(blocked, ApiErrorId.ERR_ALLOTMENT_QUARTER_OCCUPIED, 409)

        adjacent = validate_success(
            api.create_allotment(
                {
                    "appropriation_id": appropriation_id,
                    "quarter": 2,
                    "requested_cents": 10_000_000,
                    "allow_partial": False,
                },
                fixtures.ANALYST,
            ),
            201,
        )
        assert adjacent["quarter"] == 2
        assert adjacent["status"] == "DRAFT"

    def test_recall_takes_the_row_out_of_the_blocking_set_and_frees_the_slot(self, api):
        """PRD §3.5: "Recall is the compensating action of release and is likewise the controller's."
        PRD §3.5: "It moves the allotment `RELEASED → RECALLED`, requires the row to be in `RELEASED`, takes a `reason` stored in `recall_reason`, and requires that the recall not push the appropriation's released cash below what it has already spent — formally, that the appropriation's `available_cash_cents` minus the allotment's `released_cents` be at least zero — otherwise `ERR_INSUFFICIENT_CASH_RELEASED`."
        PRD §2.12: "No other allotment on the same `appropriation_id` and `quarter` is in status `DRAFT`, `PREPARED`, `APPROVED`, or `RELEASED` — otherwise `ERR_ALLOTMENT_QUARTER_OCCUPIED` (409). Applies to `POST /fiscal/allotments`."

        Design: Difficulty/resource_temporal_overlap/allotment_quarter_slot_occupancy_survives_release_and_frees_on_recall
        """
        ctx = self._released_quarter_one()
        appropriation_id = ctx["appropriation"]["id"]

        recalled = fixtures.recall_allotment(ctx["allotment"]["id"], "cash plan revised")
        assert recalled["status"] == "RECALLED"
        assert recalled["released_cents"] == 0

        replacement = validate_success(
            api.create_allotment(
                {
                    "appropriation_id": appropriation_id,
                    "quarter": 1,
                    "requested_cents": 10_000_000,
                    "allow_partial": False,
                },
                fixtures.ANALYST,
            ),
            201,
        )
        assert replacement["quarter"] == 1

        assert fixtures.read_appropriation(appropriation_id)["released_cents"] == 0
        assert fixtures.read_budget_cycle(ctx["cycle"]["id"])["total_released_cents"] == 0


class TestForecastQuietBuffer:
    @staticmethod
    def _cycle_with_competing_windows():
        ctx = fixtures.setup_cycle(
            stop_after="DEVELOPMENT", appropriations=(), adopt_revenue=False
        )
        cycle_id = ctx["cycle"]["id"]
        incumbent = fixtures.record_and_adopt_forecast(
            cycle_id,
            source_code="SALES_TAX",
            amount_cents=5_000_000_000,
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-10-01T00:00:00Z",
        )
        fourteen_days_later = fixtures.record_forecast(
            cycle_id,
            source_code="SALES_TAX",
            amount_cents=3_000_000_000,
            effective_from="2026-10-15T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
        )
        thirty_one_days_later = fixtures.record_forecast(
            cycle_id,
            source_code="SALES_TAX",
            amount_cents=3_000_000_000,
            effective_from="2026-11-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
        )
        other_source = fixtures.record_forecast(
            cycle_id,
            source_code="INCOME_TAX",
            amount_cents=2_000_000_000,
            effective_from="2026-10-15T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
        )
        ctx["incumbent"] = incumbent
        ctx["too_close"] = fourteen_days_later
        ctx["far_enough"] = thirty_one_days_later
        ctx["other_source"] = other_source
        return ctx

    def test_a_window_inside_the_buffer_is_refused_and_one_outside_it_is_adopted(
        self, api, budget_director_headers
    ):
        """PRD §3.1: "Adoption also enforces a **30-day quiet buffer**: no other `ADOPTED` forecast of the same cycle and the same `source_code` — excluding the row explicitly being superseded — may sit within thirty days of the window being adopted, and a collision is rejected with `ERR_FORECAST_WINDOW_CONFLICT`."
        PRD §2.12: "The adopted window keeps a 30-day quiet buffer from every other adopted window of the same cycle and `source_code`, excluding the row named in `supersedes_forecast_id` — otherwise `ERR_FORECAST_WINDOW_CONFLICT` (409). Applies to `POST /fiscal/revenue-forecasts/{id}/adopt`."
        PRD §3.1: "The estimate is recorded in `DRAFT`."

        Design: Difficulty/resource_temporal_overlap/forecast_adoption_thirty_day_quiet_buffer_is_scoped_per_source_code
        """
        ctx = self._cycle_with_competing_windows()

        response = api.adopt_revenue_forecast(
            ctx["too_close"]["id"], budget_director_headers, {}
        )
        validate_error(response, ApiErrorId.ERR_FORECAST_WINDOW_CONFLICT, 409)

        drafts, _meta = validate_paginated(
            api.list_cycle_revenue_forecasts(
                ctx["cycle"]["id"], fixtures.ANALYST, {"status": "DRAFT"}
            )
        )
        assert ctx["too_close"]["id"] in [row["id"] for row in drafts]

        adopted = validate_success(
            api.adopt_revenue_forecast(ctx["far_enough"]["id"], budget_director_headers, {}), 200
        )
        assert adopted["status"] == "ADOPTED"

    def test_the_buffer_does_not_cross_source_code_boundaries(
        self, api, budget_director_headers
    ):
        """PRD §3.1: "Adoption also enforces a **30-day quiet buffer**: no other `ADOPTED` forecast of the same cycle and the same `source_code` — excluding the row explicitly being superseded — may sit within thirty days of the window being adopted, and a collision is rejected with `ERR_FORECAST_WINDOW_CONFLICT`."
        PRD §3.1: "The cycle's `adopted_general_fund_revenue_cents` is the sum of `amount_cents` over every forecast of that cycle whose status is `ADOPTED` and whose `fund_type` is `GENERAL`; `DRAFT` and `SUPERSEDED` rows contribute nothing, and `FEDERAL` and `DEDICATED` rows contribute nothing regardless of status."

        Design: Difficulty/resource_temporal_overlap/forecast_adoption_thirty_day_quiet_buffer_is_scoped_per_source_code
        """
        ctx = self._cycle_with_competing_windows()
        validate_error(
            api.adopt_revenue_forecast(ctx["too_close"]["id"], budget_director_headers, {}),
            ApiErrorId.ERR_FORECAST_WINDOW_CONFLICT,
            409,
        )
        validate_success(
            api.adopt_revenue_forecast(ctx["far_enough"]["id"], budget_director_headers, {}), 200
        )

        other = validate_success(
            api.adopt_revenue_forecast(ctx["other_source"]["id"], budget_director_headers, {}), 200
        )
        assert other["status"] == "ADOPTED"
        assert other["source_code"] == "INCOME_TAX"

        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert cycle["adopted_general_fund_revenue_cents"] == 10_000_000_000


class TestMatchPledgeHalfOpenOverlap:
    @staticmethod
    def _three_grants_on_one_line():
        ctx = fixtures.setup_execution_cycle(
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 1_000_000_000,
                },
            )
        )
        agency_id = ctx["agency"]["id"]
        cycle_id = ctx["cycle"]["id"]
        first_half = fixtures.record_federal_grant(
            agency_id,
            cycle_id,
            cfda_number="93.001",
            award_cents=2_400_000_000,
            required_match_ratio=0.25,
            period_start="2026-07-01T00:00:00Z",
            period_end="2027-01-01T00:00:00Z",
        )
        second_half = fixtures.record_federal_grant(
            agency_id,
            cycle_id,
            cfda_number="93.002",
            award_cents=2_400_000_000,
            required_match_ratio=0.25,
            period_start="2027-01-01T00:00:00Z",
            period_end="2027-07-01T00:00:00Z",
        )
        straddling = fixtures.record_federal_grant(
            agency_id,
            cycle_id,
            cfda_number="93.003",
            award_cents=400_000_000,
            required_match_ratio=0.25,
            period_start="2026-12-01T00:00:00Z",
            period_end="2027-06-01T00:00:00Z",
        )
        ctx["first_half"] = first_half
        ctx["second_half"] = second_half
        ctx["straddling"] = straddling
        return ctx

    def test_periods_that_only_touch_do_not_contend_for_the_same_authority(self, api):
        """PRD §3.8: "Overlap is half-open in both directions: two periods overlap when the existing grant's `period_start` is strictly earlier than the incoming grant's `period_end` and the incoming grant's `period_start` is strictly earlier than the existing grant's `period_end`, so periods that merely touch end-to-start do **not** overlap."
        PRD §3.8: "When a new commitment is created, gather the existing commitments on the same `appropriation_id` whose status is `COMMITTED` and whose grant's performance period overlaps the incoming grant's period."
        PRD §3.8: "At creation the grant's `required_state_match_cents` is fixed once as `award_cents` multiplied by `required_match_ratio`, rounded half up to the cent; `committed_match_cents` and `moe_current_spend_cents` are 0, `moe_compliance_ratio` is 0, `moe_assessed_basis` is null, `match_status` is `UNMET`, and `moe_compliance_status` is `NOT_ASSESSED`."

        Design: Difficulty/resource_temporal_overlap/match_pledge_capacity_counts_half_open_overlaps_and_ignores_touching_periods
        """
        ctx = self._three_grants_on_one_line()
        officer = make_agency_officer_headers(ctx["agency"]["id"])
        assert ctx["first_half"]["required_state_match_cents"] == 600_000_000
        assert ctx["straddling"]["required_state_match_cents"] == 100_000_000

        first = validate_success(
            api.create_match_commitment(
                {
                    "federal_grant_id": ctx["first_half"]["id"],
                    "appropriation_id": ctx["appropriation"]["id"],
                    "committed_match_cents": 600_000_000,
                },
                officer,
            ),
            201,
        )
        second = validate_success(
            api.create_match_commitment(
                {
                    "federal_grant_id": ctx["second_half"]["id"],
                    "appropriation_id": ctx["appropriation"]["id"],
                    "committed_match_cents": 600_000_000,
                },
                officer,
            ),
            201,
        )

        assert first["status"] == "COMMITTED"
        assert second["status"] == "COMMITTED"
        assert fixtures.read_federal_grant(ctx["first_half"]["id"])["match_status"] == "MET"
        assert fixtures.read_federal_grant(ctx["second_half"]["id"])["match_status"] == "MET"

    def test_a_straddling_period_is_refused_on_the_aggregate_capacity(self, api):
        """PRD §3.8: "Sum `committed_match_cents` over that gathered set, add the incoming pledge, and if the result exceeds the appropriation's `available_authority_cents`, reject with `ERR_MATCH_AGGREGATE_CAPACITY_EXCEEDED`."
        PRD §2.12: "Overlapping committed match pledges plus the new pledge fit inside the appropriation's available authority — otherwise `ERR_MATCH_AGGREGATE_CAPACITY_EXCEEDED` (422). Applies to `POST /fiscal/match-commitments`."
        PRD §3.8: "Behind the grants, each agency's `federal_compliance_flag` resolves from the grants it owns: `DEFICIENT` when any grant of the agency is in `SHORTFALL`, otherwise `AT_RISK` when any grant is in `AT_RISK`, otherwise `CLEAR`."

        Design: Difficulty/resource_temporal_overlap/match_pledge_capacity_counts_half_open_overlaps_and_ignores_touching_periods
        """
        ctx = self._three_grants_on_one_line()
        officer = make_agency_officer_headers(ctx["agency"]["id"])
        for grant_key in ("first_half", "second_half"):
            validate_success(
                api.create_match_commitment(
                    {
                        "federal_grant_id": ctx[grant_key]["id"],
                        "appropriation_id": ctx["appropriation"]["id"],
                        "committed_match_cents": 600_000_000,
                    },
                    officer,
                ),
                201,
            )

        response = api.create_match_commitment(
            {
                "federal_grant_id": ctx["straddling"]["id"],
                "appropriation_id": ctx["appropriation"]["id"],
                "committed_match_cents": 100_000_000,
            },
            officer,
        )
        validate_error(response, ApiErrorId.ERR_MATCH_AGGREGATE_CAPACITY_EXCEEDED, 422)

        straddling = fixtures.read_federal_grant(ctx["straddling"]["id"])
        assert straddling["committed_match_cents"] == 0
        assert straddling["match_status"] == "UNMET"
        assert fixtures.read_agency(ctx["agency"]["id"])["federal_compliance_flag"] == "CLEAR"
