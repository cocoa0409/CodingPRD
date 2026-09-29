"""Two interval conventions in one system, and the endpoint they disagree about.

A forecast period is half-open, so two of them may share a boundary month. A
supply-contract term is closed and additionally fenced by a week-long changeover
buffer, so sharing a boundary day is an intersection and a six-day gap is still
too tight. The same arithmetic therefore produces opposite answers depending on
which resource is asked.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    ERR_CONTRACT_BUFFER_VIOLATION,
    ERR_CONTRACT_TERM_OVERLAP,
    ERR_FORECAST_PERIOD_OVERLAP,
    assert_price,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_paginated,
)

#: The published forecast every candidate in the first scenario is measured
#: against: NARROWBODY / DOMESTIC_SHORT over [2027-01, 2027-04).
BASE_FORECAST = dict(
    fleet_type="NARROWBODY",
    route_group="DOMESTIC_SHORT",
    season="SUMMER",
    period_start_month="2027-01",
    period_end_month="2027-04",
    forecast_gallons=4000000,
)

#: A March start intersects the base interval; an April start only touches it;
#: and the same March start on another route group is a different key entirely.
CLASHING_FORECAST = dict(
    fleet_type="NARROWBODY",
    route_group="DOMESTIC_SHORT",
    season="SUMMER",
    period_start_month="2027-03",
    period_end_month="2027-06",
    forecast_gallons=2000000,
)
TOUCHING_FORECAST = dict(
    fleet_type="NARROWBODY",
    route_group="DOMESTIC_SHORT",
    season="FALL",
    period_start_month="2027-04",
    period_end_month="2027-07",
    forecast_gallons=2000000,
)
OTHER_ROUTE_FORECAST = dict(
    fleet_type="NARROWBODY",
    route_group="DOMESTIC_LONG",
    season="SUMMER",
    period_start_month="2027-03",
    period_end_month="2027-06",
    forecast_gallons=2000000,
)

#: The clock the contract scenario reads its statuses at.
CONTRACT_CLOCK = "2027-02-10T00:00:00Z"

#: The sitting contract and the four candidates that follow it.
SITTING_TERM = dict(
    contract_ref="ORD-Q1",
    index_price_usd_per_gal=2.4000,
    differential_usd_per_gal=0.0250,
    term_start_date="2027-01-01",
    term_end_date="2027-03-31",
)
SIX_DAY_GAP = dict(
    contract_ref="ORD-BUFFER6",
    index_price_usd_per_gal=2.5000,
    differential_usd_per_gal=0.0300,
    term_start_date="2027-04-06",
    term_end_date="2027-04-06",
)
SEVEN_DAY_GAP = dict(
    contract_ref="ORD-Q2",
    index_price_usd_per_gal=2.5000,
    differential_usd_per_gal=0.0300,
    term_start_date="2027-04-07",
    term_end_date="2027-06-30",
)
SHARED_LAST_DAY = dict(
    contract_ref="ORD-TOUCH",
    index_basis="PLATTS_NWE",
    index_price_usd_per_gal=2.6000,
    differential_usd_per_gal=0.0400,
    term_start_date="2027-06-30",
    term_end_date="2027-07-31",
)
NEXT_QUARTER = dict(
    contract_ref="ORD-Q3",
    index_basis="PLATTS_NWE",
    index_price_usd_per_gal=2.6000,
    differential_usd_per_gal=0.0400,
    term_start_date="2027-07-07",
    term_end_date="2027-09-30",
)


def _forecast_by_id(api, forecast_id):
    """Forecasts are readable only through the collection endpoint."""
    rows = get_success_data(api.list_consumption_forecasts(headers=ANALYST))
    matches = [row for row in rows if row["id"] == forecast_id]
    assert matches, f"forecast {forecast_id} not listed"
    return matches[0]


class TestForecastHalfOpenMonthIntervals:
    @staticmethod
    def _one_published_forecast_and_three_drafts(api):
        published = fx.do_create_published_forecast(api, **BASE_FORECAST)
        return {
            "published": published,
            "clashing": fx.do_create_forecast(api, **CLASHING_FORECAST),
            "touching": fx.do_create_forecast(api, **TOUCHING_FORECAST),
            "other_route": fx.do_create_forecast(api, **OTHER_ROUTE_FORECAST),
        }

    def test_an_intersecting_interval_cannot_be_published(self, api):
        """PRD §3.3: "Publication is the gate that lets a forecast enter a sizing
        basis, and it is guarded by an overlap rule that is enforced only against
        already-`PUBLISHED` siblings: no other `PUBLISHED` forecast with the same
        `fleet_type` *and* the same `route_group` may have a half-open month interval
        that intersects this one."

        PRD §3.3: "Drafts may overlap each other freely; the constraint bites only at
        publication."

        All three candidates were created without complaint, which is the point: the
        interval running from March to June genuinely intersects the published
        January-to-April row, and only its publication is refused.

        Design: Difficulty/resource_temporal_overlap/forecast_half_open_month_interval_allows_touching_periods
        """
        ctx = self._one_published_forecast_and_three_drafts(api)
        assert ctx["published"]["status"] == "PUBLISHED"
        assert ctx["clashing"]["status"] == "DRAFT"

        validate_error(
            api.publish_consumption_forecast(ctx["clashing"]["id"], headers=ANALYST),
            ERR_FORECAST_PERIOD_OVERLAP,
            409,
        )

        refused = _forecast_by_id(api, ctx["clashing"]["id"])
        assert refused["status"] == "DRAFT"
        assert refused["published_at"] is None

    def test_two_intervals_that_merely_touch_are_both_allowed(self, api):
        """PRD §3.3: "Because the intervals are half-open, two forecasts that merely
        touch — where one's `period_end_month` equals the other's
        `period_start_month` — do not intersect and are both allowed."

        PRD §3.3: "Publishing a forecast advances it `DRAFT → PUBLISHED`, stamps
        `published_at` with the logical clock instant and increments the forecast's
        `version` by one."

        The base row ends at 2027-04 and this one starts at 2027-04. One month
        later than the interval that was just refused, and the shared endpoint
        belongs to neither.

        Design: Difficulty/resource_temporal_overlap/forecast_half_open_month_interval_allows_touching_periods
        """
        ctx = self._one_published_forecast_and_three_drafts(api)
        validate_error(
            api.publish_consumption_forecast(ctx["clashing"]["id"], headers=ANALYST),
            ERR_FORECAST_PERIOD_OVERLAP,
            409,
        )

        published = fx.do_publish_forecast(api, ctx["touching"]["id"])
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None
        assert published["period_start_month"] == "2027-04"
        assert ctx["published"]["period_end_month"] == "2027-04"

    def test_the_exclusion_key_is_fleet_type_and_route_group_together(self, api):
        """PRD §3.3: "Its period is expressed as two `YYYY-MM` strings, and it is
        deliberately half-open: the forecast covers `period_start_month` inclusive up
        to but not including `period_end_month`, which must be strictly later than
        the start."

        The refused candidate and this one share the very same March-to-June
        interval and the same fleet. Only `route_group` differs, and that is enough
        for the two rows to be siblings of nobody: the `DOMESTIC_LONG` forecast
        publishes.

        Design: Difficulty/resource_temporal_overlap/forecast_half_open_month_interval_allows_touching_periods
        """
        ctx = self._one_published_forecast_and_three_drafts(api)
        validate_error(
            api.publish_consumption_forecast(ctx["clashing"]["id"], headers=ANALYST),
            ERR_FORECAST_PERIOD_OVERLAP,
            409,
        )

        published = fx.do_publish_forecast(api, ctx["other_route"]["id"])
        assert published["status"] == "PUBLISHED"
        assert published["fleet_type"] == ctx["clashing"]["fleet_type"]
        assert published["period_start_month"] == ctx["clashing"]["period_start_month"]
        assert published["period_end_month"] == ctx["clashing"]["period_end_month"]
        assert published["route_group"] == "DOMESTIC_LONG"


class TestSupplyContractClosedIntervalsAndChangeoverBuffer:
    @staticmethod
    def _station_holding_one_first_quarter_contract(api):
        fx.set_clock(api, CONTRACT_CLOCK)
        station = fx.do_create_station(api)
        sitting = fx.do_create_contract(api, station["id"], **SITTING_TERM)
        return {"station": station, "sitting": sitting}

    @staticmethod
    def _offer(api, station_id, **contract):
        return api.create_supply_contract(
            station_id, f.supply_contract_payload(**contract), headers=ADMIN
        )

    def test_six_clear_days_is_one_short_and_seven_is_enough(self, api):
        """PRD §3.2: "Second, consecutive non-intersecting contracts at one station
        must be separated by a changeover buffer of at least a full week: the number
        of days from the earlier contract's `term_end_date` to the later contract's
        `term_start_date` must be at least seven, so a gap of exactly seven days is
        accepted while a gap of six days is rejected with
        `ERR_CONTRACT_BUFFER_VIOLATION`."

        Both candidates start after the sitting term ends on 2027-03-31, so neither
        intersects anything; the sixth of April is refused and the seventh, one day
        later, is accepted.

        Design: Difficulty/resource_temporal_overlap/supply_contract_closed_interval_with_changeover_buffer
        """
        ctx = self._station_holding_one_first_quarter_contract(api)
        assert ctx["sitting"]["term_end_date"] == "2027-03-31"

        error = validate_error(
            self._offer(api, ctx["station"]["id"], **SIX_DAY_GAP),
            ERR_CONTRACT_BUFFER_VIOLATION,
            409,
        )
        assert error["error_id"] != ERR_CONTRACT_TERM_OVERLAP

        accepted = fx.do_create_contract(api, ctx["station"]["id"], **SEVEN_DAY_GAP)
        assert accepted["term_start_date"] == "2027-04-07"
        assert_price(
            accepted["all_in_price_usd_per_gal"], 2.5750, "all_in_price_usd_per_gal"
        )

    def test_sharing_a_single_boundary_day_is_an_intersection_here(self, api):
        """PRD §3.2: "First, because contract terms are closed intervals, two
        contracts at the same station may not share even a single day; any
        intersection is rejected with `ERR_CONTRACT_TERM_OVERLAP`."

        PRD §3.2: "The term is a closed interval of ISO 8601 dates,
        `term_start_date` through `term_end_date`, both days inclusive, with the end
        no earlier than the start."

        The candidate starts on 2027-06-30, the last day of the contract just
        accepted, and 2027-06-30 belongs to both terms. Where a forecast would have
        touched cleanly, a contract overlaps — and the answer is the overlap, not
        the buffer.

        Design: Difficulty/resource_temporal_overlap/supply_contract_closed_interval_with_changeover_buffer
        """
        ctx = self._station_holding_one_first_quarter_contract(api)
        sitting_q2 = fx.do_create_contract(api, ctx["station"]["id"], **SEVEN_DAY_GAP)
        assert sitting_q2["term_end_date"] == "2027-06-30"

        error = validate_error(
            self._offer(api, ctx["station"]["id"], **SHARED_LAST_DAY),
            ERR_CONTRACT_TERM_OVERLAP,
            409,
        )
        assert error["error_id"] != ERR_CONTRACT_BUFFER_VIOLATION

    def test_the_station_ends_with_three_rows_priced_and_dated_from_the_clock(
        self, api
    ):
        """PRD §3.2: "Before `term_start_date` the contract is `SCHEDULED`; from
        `term_start_date` through `term_end_date` inclusive it is `ACTIVE`; after
        `term_end_date` it is `EXPIRED`."

        PRD §3.2: "On creation the server computes `all_in_price_usd_per_gal` as the
        sum of `index_price_usd_per_gal`, `differential_usd_per_gal` and the
        station's `into_plane_fee_usd_per_gal`, rounded to four decimal places — this
        is the price every tankering calculation uses."

        A third quarter starting exactly seven days after 2027-06-30 is accepted,
        and the two refusals left nothing behind: three rows, one `ACTIVE` at the
        February clock and two `SCHEDULED` ahead of it, priced at 2.5750 and 2.6850
        over a 0.0450 fee.

        Design: Difficulty/resource_temporal_overlap/supply_contract_closed_interval_with_changeover_buffer
        """
        ctx = self._station_holding_one_first_quarter_contract(api)
        station_id = ctx["station"]["id"]
        validate_error(
            self._offer(api, station_id, **SIX_DAY_GAP),
            ERR_CONTRACT_BUFFER_VIOLATION,
            409,
        )
        second = fx.do_create_contract(api, station_id, **SEVEN_DAY_GAP)
        validate_error(
            self._offer(api, station_id, **SHARED_LAST_DAY),
            ERR_CONTRACT_TERM_OVERLAP,
            409,
        )
        third = fx.do_create_contract(api, station_id, **NEXT_QUARTER)

        rows, _ = validate_paginated(api.list_supply_contracts(station_id, headers=ADMIN))
        assert len(rows) == 3
        by_id = {row["id"]: row for row in rows}
        assert by_id[ctx["sitting"]["id"]]["status"] == "ACTIVE"
        assert by_id[second["id"]]["status"] == "SCHEDULED"
        assert by_id[third["id"]]["status"] == "SCHEDULED"
        assert_price(
            by_id[second["id"]]["all_in_price_usd_per_gal"],
            2.5750,
            "all_in_price_usd_per_gal",
        )
        assert_price(
            by_id[third["id"]]["all_in_price_usd_per_gal"],
            2.6850,
            "all_in_price_usd_per_gal",
        )
