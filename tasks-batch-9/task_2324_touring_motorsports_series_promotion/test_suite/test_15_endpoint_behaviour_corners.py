"""Endpoint behaviour at its boundaries.

Five endpoints are pushed to their edges: the partial logistics patch together with
the show-timing triple, the sales actions and the states they are declared from,
the by-market report's double filter and its ordering, the run-order segment's link
to a featured entry, and the conditions that guard sponsorship activation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CLOCK_DEFAULT_UTC,
    DEFAULT_DOORS_OPEN_UTC,
    DEFAULT_LOAD_IN_START_UTC,
    DEFAULT_SCHEDULED_ARRIVAL_UTC,
    DEFAULT_SHOW_START_UTC,
    DEFAULT_SHOW_WINDOW_MINUTES,
    DEFAULT_TEAR_DOWN_END_UTC,
    DEFAULT_TOUR_DATE,
    DEFAULT_VENUE_CITY,
    DEFAULT_VENUE_MARKET_CODE,
    DEFAULT_VENUE_NAME,
    DEFAULT_VENUE_STATE_CODE,
    NON_EXISTENT_UUID,
    SECOND_DOORS_OPEN_UTC,
    SECOND_LOAD_IN_START_UTC,
    SECOND_SHOW_START_UTC,
    SECOND_TEAR_DOWN_END_UTC,
    SECOND_TOUR_DATE,
    SECOND_VENUE_CITY,
    SECOND_VENUE_MARKET_CODE,
    SECOND_VENUE_NAME,
    SECOND_VENUE_STATE_CODE,
    THIRD_LOAD_IN_START_UTC,
    THIRD_TEAR_DOWN_END_UTC,
    THIRD_TOUR_DATE,
    THIRD_VENUE_CITY,
    THIRD_VENUE_MARKET_CODE,
    THIRD_VENUE_NAME,
    THIRD_VENUE_STATE_CODE,
    assert_market_report,
    certified_safety_plan,
    commit_marketing_allocation,
    confirmed_booking as make_confirmed_booking,
    create_season,
    create_show_segment,
    create_sponsor,
    create_sponsorship_activation,
    create_ticket_tier,
    create_vehicle_entry,
    fetch_entry,
    fetch_season,
    fetch_stop,
    fetch_tier,
    get_success_data,
    make_series_promoter_headers,
    make_show_segment_payload,
    make_ticketing_manager_headers,
    place_paid_ticket_order,
    settle_closed_stop,
    staged_entry,
    stop_with_show_timing,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Module-local helpers
# ---------------------------------------------------------------------------

def _instant(value: str) -> datetime:
    """The UTC instant a timestamp denotes, whichever fractional form it carries."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


#: One market of the by-market report is built with a single expensive tier that
#: sells out completely, so its money is a small set of exact integers.
_REPORT_TIER_CODE = "PREM"
_REPORT_TIER_PRICE_CENTS = 10000
_REPORT_TIER_ALLOTMENT = 500
_REPORT_MARKETING_CENTS = 500000
_REPORT_SEGMENT_MINUTES = 40

#: Provisioning that meets every requirement floor of a 500-seat stop exactly,
#: so both markets carry the same safety bill.
_REPORT_PLAN: Dict[str, int] = {
    "barrier_linear_feet": 1200,
    "catch_fence_height_ft": 6,
    "medical_als_staff_count": 1,
    "medical_bls_staff_count": 2,
    "ambulance_count": 1,
    "emergency_access_lanes": 1,
}


def _report_market_stop(
    api: ApiClient,
    season_id: str,
    *,
    venue_kwargs: Dict[str, Any],
    booking_kwargs: Dict[str, Any],
    doors_open_utc: str,
    show_start_utc: str,
    on_sale_end_utc: str,
) -> Dict[str, Any]:
    """Build one market of the report to the point just before sales open.

    The stop gets its show timing, one competition segment, one tier that is the
    whole price card, a certified safety plan and one committed marketing
    allocation. The per-market booking terms differ, which is what makes the two
    markets' net figures differ.
    """
    promoter = make_series_promoter_headers()
    state = make_confirmed_booking(
        api, season_id=season_id, **venue_kwargs, **booking_kwargs
    )
    stop_id = state["stop_id"]
    state["stop"] = get_success_data(
        api.update_tour_stop_logistics(
            stop_id,
            {
                "doors_open_utc": doors_open_utc,
                "show_start_utc": show_start_utc,
                "show_window_minutes": DEFAULT_SHOW_WINDOW_MINUTES,
            },
            headers=promoter,
        )
    )
    state.update(
        create_show_segment(
            api,
            stop_id,
            segment_title="Feature",
            duration_minutes=_REPORT_SEGMENT_MINUTES,
        )
    )
    state.update(
        create_ticket_tier(
            api,
            stop_id,
            tier_code=_REPORT_TIER_CODE,
            price_cents=_REPORT_TIER_PRICE_CENTS,
            allotment=_REPORT_TIER_ALLOTMENT,
            on_sale_start_utc=CLOCK_DEFAULT_UTC,
            on_sale_end_utc=on_sale_end_utc,
        )
    )
    return state


def _report_sell_out_and_settle(
    api: ApiClient, state: Dict[str, Any], purchaser: str
) -> Dict[str, Any]:
    """Open the stop, sell the tier out, close the window and approve a settlement."""
    ticketing = make_ticketing_manager_headers()
    state["stop"] = get_success_data(
        api.open_tour_stop_sales(state["stop_id"], headers=ticketing)
    )
    state.update(
        place_paid_ticket_order(
            api,
            state["stop_id"],
            state["tier_id"],
            qty=_REPORT_TIER_ALLOTMENT,
            purchaser_name=purchaser,
            purchaser_email="house@example.com",
        )
    )
    state["stop"] = get_success_data(
        api.close_tour_stop_sales(state["stop_id"], headers=ticketing)
    )
    return settle_closed_stop(api, state, approve=True)


def _two_settled_markets_and_one_untouched(api: ApiClient) -> Dict[str, Any]:
    """A season with two approved markets and a third stop nobody has worked on.

    Atlanta and Dallas are both taken all the way to an approved settlement on
    different booking terms, while Omaha is left at ``SALES_PENDING``. All three
    bookings are confirmed before the clock moves, because a booking still has to
    clear its lead time when it is filed.
    """
    season_id = create_season(api)["season_id"]

    atl = _report_market_stop(
        api,
        season_id,
        venue_kwargs={
            "venue_name": DEFAULT_VENUE_NAME,
            "market_code": DEFAULT_VENUE_MARKET_CODE,
            "city": DEFAULT_VENUE_CITY,
            "state_code": DEFAULT_VENUE_STATE_CODE,
        },
        booking_kwargs={
            "tour_date": DEFAULT_TOUR_DATE,
            "rental_base_cents": 3000000,
            "revenue_share_pct": 0.12,
            "per_ticket_facility_fee_cents": 350,
            "load_in_start_utc": DEFAULT_LOAD_IN_START_UTC,
            "tear_down_end_utc": DEFAULT_TEAR_DOWN_END_UTC,
        },
        doors_open_utc=DEFAULT_DOORS_OPEN_UTC,
        show_start_utc=DEFAULT_SHOW_START_UTC,
        on_sale_end_utc="2026-11-14T18:00:00Z",
    )
    dal = _report_market_stop(
        api,
        season_id,
        venue_kwargs={
            "venue_name": SECOND_VENUE_NAME,
            "market_code": SECOND_VENUE_MARKET_CODE,
            "city": SECOND_VENUE_CITY,
            "state_code": SECOND_VENUE_STATE_CODE,
        },
        booking_kwargs={
            "tour_date": SECOND_TOUR_DATE,
            "rental_base_cents": 2900000,
            "revenue_share_pct": 0.11,
            "per_ticket_facility_fee_cents": 400,
            "load_in_start_utc": SECOND_LOAD_IN_START_UTC,
            "tear_down_end_utc": SECOND_TEAR_DOWN_END_UTC,
        },
        doors_open_utc=SECOND_DOORS_OPEN_UTC,
        show_start_utc=SECOND_SHOW_START_UTC,
        on_sale_end_utc="2026-12-05T18:00:00Z",
    )
    oma = make_confirmed_booking(
        api,
        season_id=season_id,
        venue_name=THIRD_VENUE_NAME,
        market_code=THIRD_VENUE_MARKET_CODE,
        city=THIRD_VENUE_CITY,
        state_code=THIRD_VENUE_STATE_CODE,
        tour_date=THIRD_TOUR_DATE,
        load_in_start_utc=THIRD_LOAD_IN_START_UTC,
        tear_down_end_utc=THIRD_TEAR_DOWN_END_UTC,
    )

    for state in (atl, dal):
        state.update(certified_safety_plan(api, state["stop_id"], **_REPORT_PLAN))
        state.update(
            commit_marketing_allocation(
                api,
                state["stop_id"],
                season_id,
                channel="RADIO",
                amount_cents=_REPORT_MARKETING_CENTS,
            )
        )

    # Atlanta alone earns a competitor purse, because only its entry is staged, and
    # staging is only admissible once the stop's safety plan is certified.
    atl.update(
        staged_entry(
            api,
            atl["stop_id"],
            vehicle_number="61",
            vehicle_weight_lbs=7000,
            entry_haul_distance_miles=100,
            scheduled_arrival_utc=DEFAULT_SCHEDULED_ARRIVAL_UTC,
        )
    )

    _report_sell_out_and_settle(api, atl, "Atlanta House")
    _report_sell_out_and_settle(api, dal, "Dallas House")

    return {
        "season_id": season_id,
        "atl": atl,
        "dal": dal,
        "oma": oma,
    }


def _propose_activation(
    api: ApiClient,
    stop_id: str,
    *,
    sponsor_id: str,
    tier_id: str,
    entry_id: str,
    fee_cents: int,
    hospitality_seat_count: int,
) -> str:
    """Propose one package holding hospitality seats and one branding slot."""
    state = create_sponsorship_activation(
        api,
        stop_id,
        sponsor_id=sponsor_id,
        hospitality_tier_id=tier_id,
        branded_vehicle_entry_id=entry_id,
        fee_cents=fee_cents,
        vehicle_branding_slots=1,
        signage_units=4,
        hospitality_seat_count=hospitality_seat_count,
    )
    assert state["activation"]["state"] == "PROPOSED"
    return state["activation_id"]


def _hospitality_stop(api: ApiClient) -> Dict[str, Any]:
    """A stop carrying a 20-seat hospitality tier and one entry that can be branded."""
    state = stop_with_show_timing(api)
    state.update(
        create_ticket_tier(
            api,
            state["stop_id"],
            tier_code="HOSP",
            price_cents=5000,
            allotment=20,
        )
    )
    state.update(
        create_vehicle_entry(
            api,
            state["stop_id"],
            vehicle_number="81",
            vehicle_weight_lbs=7000,
            entry_haul_distance_miles=100,
            scheduled_arrival_utc=DEFAULT_SCHEDULED_ARRIVAL_UTC,
        )
    )
    return state


# ---------------------------------------------------------------------------
# The logistics patch
# ---------------------------------------------------------------------------


class TestTourStopLogisticsPatch:
    """PATCH /tour-stops/{id}/logistics: a partial write under a bounded triple."""

    def test_logistics_patch_accepts_a_one_hour_gap_and_then_only_the_named_field(
        self, api: ApiClient, confirmed_booking: Dict[str, Any], promoter_headers
    ) -> None:
        """The promoter fills that in with a logistics update, which accepts any subset of `doors_open_utc`, `show_start_utc`, `show_window_minutes`, `pit_party_price_cents`, `pit_party_capacity`, `preceding_stop_id` and `haul_distance_miles`. `show_window_minutes` is the total on-floor minutes available to the run order and defaults to 150; `pit_party_price_cents` is the per-head price of the pre-show pit party add-on and defaults to 2450; `pit_party_capacity` is the maximum number of pit party heads the stop will sell and defaults to 0. (§3.2)

        Design: Corner/endpoints/corner_endpoint_logistics_patch_is_partial_and_show_timing_is_bounded
        """
        stop_id = confirmed_booking["stop_id"]

        timed = validate_success(
            api.update_tour_stop_logistics(
                stop_id,
                {
                    "doors_open_utc": "2026-11-14T22:00:00Z",
                    "show_start_utc": "2026-11-14T23:00:00Z",
                    "show_window_minutes": 150,
                },
                headers=promoter_headers,
            ),
            200,
        )
        assert _instant(timed["doors_open_utc"]) == _instant("2026-11-14T22:00:00Z")
        assert _instant(timed["show_start_utc"]) == _instant("2026-11-14T23:00:00Z")
        assert timed["show_window_minutes"] == 150

        priced = validate_success(
            api.update_tour_stop_logistics(
                stop_id, {"pit_party_price_cents": 3900}, headers=promoter_headers
            ),
            200,
        )
        assert priced["pit_party_price_cents"] == 3900
        # The subset that was not named keeps what it had, and a field nobody has
        # ever written keeps the value it opened with.
        assert _instant(priced["doors_open_utc"]) == _instant("2026-11-14T22:00:00Z")
        assert _instant(priced["show_start_utc"]) == _instant("2026-11-14T23:00:00Z")
        assert priced["show_window_minutes"] == 150
        assert priced["pit_party_capacity"] == 0

    def test_show_timing_triple_is_bounded_and_rejections_leave_the_stop_intact(
        self, api: ApiClient, confirmed_booking: Dict[str, Any], promoter_headers
    ) -> None:
        """`doors_open_utc` must be strictly earlier than `show_start_utc`, the gap between them must be at least one hour, and `show_start_utc` must fall inside the booking's occupancy interval running from `load_in_start_utc` to `tear_down_end_utc`. Any of those three failing is rejected with `ERR_SHOW_TIMING_INVALID`. (§3.2)

        Design: Corner/endpoints/corner_endpoint_logistics_patch_is_partial_and_show_timing_is_bounded
        """
        stop_id = confirmed_booking["stop_id"]
        opening_version = confirmed_booking["stop"]["version"]

        # Exactly one hour of gap is admissible, and so is a patch that names one
        # unrelated field.
        validate_success(
            api.update_tour_stop_logistics(
                stop_id,
                {
                    "doors_open_utc": "2026-11-14T22:00:00Z",
                    "show_start_utc": "2026-11-14T23:00:00Z",
                    "show_window_minutes": 150,
                },
                headers=promoter_headers,
            ),
            200,
        )
        validate_success(
            api.update_tour_stop_logistics(
                stop_id, {"pit_party_price_cents": 3900}, headers=promoter_headers
            ),
            200,
        )

        # Doors level with the show start is not strictly earlier.
        validate_error(
            api.update_tour_stop_logistics(
                stop_id,
                {
                    "doors_open_utc": "2026-11-14T23:00:00Z",
                    "show_start_utc": "2026-11-14T23:00:00Z",
                },
                headers=promoter_headers,
            ),
            ApiErrorId.ERR_SHOW_TIMING_INVALID,
            422,
        )
        # Thirty minutes is short of the one-hour floor.
        validate_error(
            api.update_tour_stop_logistics(
                stop_id,
                {
                    "doors_open_utc": "2026-11-14T22:30:00Z",
                    "show_start_utc": "2026-11-14T23:00:00Z",
                },
                headers=promoter_headers,
            ),
            ApiErrorId.ERR_SHOW_TIMING_INVALID,
            422,
        )
        # An hour past tear-down is outside the booking's occupancy interval.
        validate_error(
            api.update_tour_stop_logistics(
                stop_id,
                {"show_start_utc": "2026-11-15T07:00:00Z"},
                headers=promoter_headers,
            ),
            ApiErrorId.ERR_SHOW_TIMING_INVALID,
            422,
        )

        after = fetch_stop(api, stop_id)
        assert _instant(after["doors_open_utc"]) == _instant("2026-11-14T22:00:00Z")
        assert _instant(after["show_start_utc"]) == _instant("2026-11-14T23:00:00Z")
        assert after["show_window_minutes"] == 150
        assert after["pit_party_price_cents"] == 3900
        # Only the two accepted patches mutated the row.
        assert after["version"] == opening_version + 2


# ---------------------------------------------------------------------------
# The sales actions
# ---------------------------------------------------------------------------


class TestSalesActionPreconditions:
    """The on-sale, close-sales and resume-sales actions and their declared states."""

    def test_close_sales_is_refused_from_sales_pending(
        self, api: ApiClient, stop_ready_for_sale: Dict[str, Any], ticketing_headers
    ) -> None:
        """Closing sales ahead of settlement is admissible from either `ON_SALE` or `SALES_HALTED`, with identical effects in both cases and no preconditions: `sales_state` becomes `SALES_CLOSED`, every `PENDING` order of the stop moves to `VOID` with `void_reason` set to `SALES_CLOSED` and its reserved seats released, and the stop's `version` increments. (§3.7)

        Design: Corner/endpoints/corner_endpoint_sales_action_preconditions_on_close_and_resume
        """
        stop_id = stop_ready_for_sale["stop_id"]
        assert stop_ready_for_sale["stop"]["sales_state"] == "SALES_PENDING"

        validate_error(
            api.close_tour_stop_sales(stop_id, headers=ticketing_headers),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        after = fetch_stop(api, stop_id)
        assert after["sales_state"] == "SALES_PENDING"

    def test_closed_sales_can_neither_be_resumed_nor_reopened(
        self, api: ApiClient, stop_ready_for_sale: Dict[str, Any], ticketing_headers
    ) -> None:
        """Resumption is an operator act: a `TicketingManager` moves the stop from `SALES_HALTED` back to `ON_SALE`, which requires the posture to be `OPEN` again and re-runs the same certification and readiness gates as going on sale, reporting `ERR_SAFETY_NOT_CERTIFIED` and `ERR_STOP_NOT_READY` on the same terms. (§3.7)

        Design: Corner/endpoints/corner_endpoint_sales_action_preconditions_on_close_and_resume
        """
        stop_id = stop_ready_for_sale["stop_id"]

        on_sale = validate_success(
            api.open_tour_stop_sales(stop_id, headers=ticketing_headers), 200
        )
        assert on_sale["sales_state"] == "ON_SALE"
        assert on_sale["readiness_posture"] == "OPEN"

        closed = validate_success(
            api.close_tour_stop_sales(stop_id, headers=ticketing_headers), 200
        )
        assert closed["sales_state"] == "SALES_CLOSED"

        # A closed window was never halted, so there is nothing to resume, and the
        # on-sale act is only declared out of SALES_PENDING.
        validate_error(
            api.resume_tour_stop_sales(stop_id, headers=ticketing_headers),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        validate_error(
            api.open_tour_stop_sales(stop_id, headers=ticketing_headers),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        after = fetch_stop(api, stop_id)
        assert after["sales_state"] == "SALES_CLOSED"
        assert after["safety_state"] == "SAFETY_CERTIFIED"
        assert after["readiness_posture"] == "OPEN"


# ---------------------------------------------------------------------------
# The by-market report
# ---------------------------------------------------------------------------


class TestSeasonMarketReport:
    """GET /seasons/{id}/market-report over a season of unequal markets."""

    def test_market_report_rows_are_filtered_and_ordered_by_net(
        self, api: ApiClient, finance_controller_headers
    ) -> None:
        """It groups the season's stops whose `sales_state` is `SETTLED` and whose settlement reached `APPROVED` by `market_code`, and emits one row per market containing that `market_code`, the `stop_count` of those stops in the market, the summed `collected_cash_cents`, the summed `net_to_promoter_cents`, and a `margin_pct` computed as the summed net divided by the summed collected cash, multiplied by 100 and rounded half up to two decimal places when the summed collected cash is greater than 0, and 0.00 otherwise. The rows are returned in `market_rows`, ordered by `net_to_promoter_cents` descending with `market_code` ascending as the tie-break. (§3.9)

        Design: Corner/endpoints/corner_endpoint_market_report_orders_and_filters_settled_markets
        """
        built = _two_settled_markets_and_one_untouched(api)

        payload = validate_success(
            api.get_season_market_report(
                built["season_id"], headers=finance_controller_headers
            ),
            200,
        )
        assert_market_report(payload)
        rows = payload["market_rows"]
        assert len(rows) == 2

        # Dallas keeps more of a larger gate, so it leads the report.
        assert rows[0]["market_code"] == SECOND_VENUE_MARKET_CODE
        assert rows[0]["stop_count"] == 1
        assert rows[0]["collected_cash_cents"] == 5200000
        assert rows[0]["net_to_promoter_cents"] == 1083000
        assert rows[0]["margin_pct"] == pytest.approx(20.83, abs=0.01)

        assert rows[1]["market_code"] == DEFAULT_VENUE_MARKET_CODE
        assert rows[1]["stop_count"] == 1
        assert rows[1]["collected_cash_cents"] == 5175000
        assert rows[1]["net_to_promoter_cents"] == 836000
        assert rows[1]["margin_pct"] == pytest.approx(16.15, abs=0.01)

        # The market nobody settled contributes no row at all.
        assert THIRD_VENUE_MARKET_CODE not in [row["market_code"] for row in rows]

    def test_market_report_envelope_counts_unsettled_stops_and_reads_purely(
        self, api: ApiClient, finance_controller_headers
    ) -> None:
        """Alongside them the report carries the `season_id`, a `total_net_cents` that sums the rows' net figures, a `settled_stop_count` counting the season's stops whose `sales_state` is `SETTLED`, and an `unsettled_stop_count` counting the season's stops whose `sales_state` is neither `SETTLED` nor `CANCELLED`. Cancelled stops, and stops whose settlement is still `PREPARED` or `DISPUTED`, contribute to `unsettled_stop_count` only and never to a market row. (§3.9)

        Design: Corner/endpoints/corner_endpoint_market_report_orders_and_filters_settled_markets
        """
        built = _two_settled_markets_and_one_untouched(api)
        season_id = built["season_id"]
        season_before = fetch_season(api, season_id)

        first = validate_success(
            api.get_season_market_report(season_id, headers=finance_controller_headers),
            200,
        )
        assert first["season_id"] == season_id
        assert first["settled_stop_count"] == 2
        assert first["unsettled_stop_count"] == 1
        assert first["total_net_cents"] == 1919000
        assert first["total_net_cents"] == season_before["season_net_cents"]

        # A third stop still outside SETTLED holds the season open.
        assert season_before["status"] == "PLANNING"
        assert fetch_stop(api, built["oma"]["stop_id"])["sales_state"] == "SALES_PENDING"

        second = validate_success(
            api.get_season_market_report(season_id, headers=finance_controller_headers),
            200,
        )
        for field in (
            "season_id",
            "market_rows",
            "total_net_cents",
            "settled_stop_count",
            "unsettled_stop_count",
        ):
            assert second[field] == first[field]
        assert fetch_season(api, season_id)["version"] == season_before["version"]


# ---------------------------------------------------------------------------
# The featured entry of a run-order segment
# ---------------------------------------------------------------------------


class TestFeaturedEntrySegmentLink:
    """POST /tour-stops/{id}/show-segments and the entry it may headline."""

    def _two_stops_with_one_entry_each(self, api: ApiClient) -> Dict[str, Any]:
        """Two timed stops of one season, each carrying one entry of the same team."""
        season_id = create_season(api)["season_id"]
        atl = stop_with_show_timing(api, season_id=season_id)
        dal = stop_with_show_timing(
            api,
            season_id=season_id,
            venue_name=SECOND_VENUE_NAME,
            market_code=SECOND_VENUE_MARKET_CODE,
            city=SECOND_VENUE_CITY,
            state_code=SECOND_VENUE_STATE_CODE,
            tour_date=SECOND_TOUR_DATE,
            load_in_start_utc=SECOND_LOAD_IN_START_UTC,
            tear_down_end_utc=SECOND_TEAR_DOWN_END_UTC,
            doors_open_utc=SECOND_DOORS_OPEN_UTC,
            show_start_utc=SECOND_SHOW_START_UTC,
        )
        atl.update(
            create_vehicle_entry(
                api,
                atl["stop_id"],
                vehicle_number="71",
                vehicle_weight_lbs=7000,
                entry_haul_distance_miles=100,
                scheduled_arrival_utc=DEFAULT_SCHEDULED_ARRIVAL_UTC,
            )
        )
        dal.update(
            create_vehicle_entry(
                api,
                dal["stop_id"],
                competitor_id=atl["competitor_id"],
                vehicle_number="71",
                vehicle_weight_lbs=7000,
                entry_haul_distance_miles=100,
                scheduled_arrival_utc="2026-12-05T16:00:00Z",
            )
        )
        return {"atl": atl, "dal": dal}

    def test_featured_entry_must_resolve_and_belong_to_the_same_stop(
        self, api: ApiClient, promoter_headers
    ) -> None:
        """A featured entry must belong to the same stop as the segment — pointing at an entry of another stop is rejected with `ERR_CHILD_STOP_MISMATCH` — and it must not be in `TECH_HELD`. (§3.4)

        Design: Corner/endpoints/corner_endpoint_segment_links_a_featured_entry_across_entities
        """
        built = self._two_stops_with_one_entry_each(api)
        atl, dal = built["atl"], built["dal"]

        # A body foreign key that resolves to nothing is the entity's own 404.
        validate_error(
            api.create_show_segment(
                atl["stop_id"],
                make_show_segment_payload(featured_vehicle_entry_id=NON_EXISTENT_UUID),
                headers=promoter_headers,
            ),
            ApiErrorId.ERR_VEHICLE_ENTRY_NOT_FOUND,
            404,
        )
        # An entry that exists but races at the other stop is a mismatch.
        validate_error(
            api.create_show_segment(
                atl["stop_id"],
                make_show_segment_payload(
                    featured_vehicle_entry_id=dal["entry_id"]
                ),
                headers=promoter_headers,
            ),
            ApiErrorId.ERR_CHILD_STOP_MISMATCH,
            422,
        )

        segment = validate_success(
            api.create_show_segment(
                atl["stop_id"],
                make_show_segment_payload(
                    featured_vehicle_entry_id=atl["entry_id"]
                ),
                headers=promoter_headers,
            ),
            201,
        )
        assert segment["featured_vehicle_entry_id"] == atl["entry_id"]
        assert segment["start_offset_minutes"] == 0
        assert segment["end_offset_minutes"] == 30
        assert segment["reset_gap_minutes"] == 0

        stop = fetch_stop(api, atl["stop_id"])
        assert stop["competition_segment_count"] == 1
        assert stop["run_order_end_offset_minutes"] == 30

        # Position 1 is taken, so a second segment cannot claim it.
        validate_error(
            api.create_show_segment(
                atl["stop_id"],
                make_show_segment_payload(
                    segment_type="INTERMISSION",
                    title="Intermission",
                    run_order_position=1,
                    duration_minutes=15,
                ),
                headers=promoter_headers,
            ),
            ApiErrorId.ERR_SEGMENT_TIMELINE_CONFLICT,
            409,
        )
        kept, _ = validate_paginated(
            api.list_show_segments(atl["stop_id"], headers=promoter_headers)
        )
        assert len(kept) == 1
        assert kept[0]["id"] == segment["id"]

    def test_featured_segment_is_navigable_from_the_entry(
        self, api: ApiClient, promoter_headers
    ) -> None:
        """A `COMPETITION` segment may headline one entry through `featured_vehicle_entry_id`; the field is null for a segment that features nobody. (§3.4) Every list response carries `limit`, `offset`, `total_count` and `has_more` in the envelope's `meta` object. (§2.3)

        Design: Corner/endpoints/corner_endpoint_segment_links_a_featured_entry_across_entities
        """
        built = self._two_stops_with_one_entry_each(api)
        atl, dal = built["atl"], built["dal"]

        segment = validate_success(
            api.create_show_segment(
                atl["stop_id"],
                make_show_segment_payload(
                    featured_vehicle_entry_id=atl["entry_id"]
                ),
                headers=promoter_headers,
            ),
            201,
        )

        headlined, headlined_meta = validate_paginated(
            api.list_featured_segments(atl["entry_id"], headers=promoter_headers)
        )
        assert headlined_meta["total_count"] == 1
        assert len(headlined) == 1
        assert headlined[0]["id"] == segment["id"]
        assert headlined[0]["featured_vehicle_entry_id"] == atl["entry_id"]

        # The other stop's entry headlines nothing, even though it is the same team
        # running the same vehicle number.
        empty, empty_meta = validate_paginated(
            api.list_featured_segments(dal["entry_id"], headers=promoter_headers)
        )
        assert empty == []
        assert empty_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Conditional activation
# ---------------------------------------------------------------------------


class TestConditionalSponsorshipActivation:
    """POST /sponsorship-activations/{id}/activate under exclusivity and seat holds."""

    def _three_proposals(self, api: ApiClient) -> Dict[str, Any]:
        """One stop, three sponsors and three proposed packages on one tier."""
        state = _hospitality_stop(api)
        stop_id, tier_id, entry_id = state["stop_id"], state["tier_id"], state["entry_id"]

        apex = create_sponsor(
            api,
            company_name="Apex Tire",
            sponsor_category="TIRE",
            contact_email="deals@apextire.example",
            exclusive_category=True,
        )
        rival = create_sponsor(
            api,
            company_name="Rival Tire",
            sponsor_category="TIRE",
            contact_email="deals@rivaltire.example",
            exclusive_category=False,
        )
        delta = create_sponsor(
            api,
            company_name="Delta Fuel",
            sponsor_category="FUEL",
            contact_email="deals@deltafuel.example",
            exclusive_category=False,
        )

        state["apex_id"] = _propose_activation(
            api,
            stop_id,
            sponsor_id=apex["sponsor_id"],
            tier_id=tier_id,
            entry_id=entry_id,
            fee_cents=900000,
            hospitality_seat_count=15,
        )
        state["rival_id"] = _propose_activation(
            api,
            stop_id,
            sponsor_id=rival["sponsor_id"],
            tier_id=tier_id,
            entry_id=entry_id,
            fee_cents=400000,
            hospitality_seat_count=2,
        )
        state["delta_big_id"] = _propose_activation(
            api,
            stop_id,
            sponsor_id=delta["sponsor_id"],
            tier_id=tier_id,
            entry_id=entry_id,
            fee_cents=500000,
            hospitality_seat_count=10,
        )
        state["delta_id"] = delta["sponsor_id"]
        return state

    def test_activation_is_refused_for_category_exclusivity_and_seat_shortfall(
        self, api: ApiClient, promoter_headers
    ) -> None:
        """And category exclusivity must hold: if another activation on the same stop sits in `ACTIVATED` or `FULFILLED` whose sponsor has the same `category` as this one, and either of the two sponsors has `exclusive_category` set to true, the request is rejected with `ERR_SPONSOR_CATEGORY_EXCLUSIVITY`. (§3.8)

        Design: Corner/endpoints/corner_endpoint_activation_is_conditional_on_category_and_seat_holds
        """
        state = self._three_proposals(api)

        live = validate_success(
            api.activate_sponsorship_activation(
                state["apex_id"], headers=promoter_headers
            ),
            200,
        )
        assert live["state"] == "ACTIVATED"

        tier = fetch_tier(api, state["tier_id"])
        assert tier["held_seat_count"] == 15
        assert tier["available_seat_count"] == 5
        assert fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 1
        assert fetch_stop(api, state["stop_id"])["sponsorship_committed_cents"] == 900000

        # A second tyre brand cannot go live behind an exclusive one.
        validate_error(
            api.activate_sponsorship_activation(
                state["rival_id"], headers=promoter_headers
            ),
            ApiErrorId.ERR_SPONSOR_CATEGORY_EXCLUSIVITY,
            409,
        )
        # Ten more seats do not fit behind the fifteen already held.
        validate_error(
            api.activate_sponsorship_activation(
                state["delta_big_id"], headers=promoter_headers
            ),
            ApiErrorId.ERR_HOSPITALITY_SEATS_EXCEEDED,
            409,
        )

        # Neither refusal moved money, seats or slots.
        tier_after = fetch_tier(api, state["tier_id"])
        assert tier_after["held_seat_count"] == 15
        assert tier_after["available_seat_count"] == 5
        assert fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 1
        stop_after = fetch_stop(api, state["stop_id"])
        assert stop_after["sponsorship_committed_cents"] == 900000
        assert stop_after["held_hospitality_seat_count"] == 15
        for activation_id in (state["rival_id"], state["delta_big_id"]):
            refused = validate_success(
                api.get_sponsorship_activation(
                    activation_id, headers=promoter_headers
                ),
                200,
            )
            assert refused["state"] == "PROPOSED"

    def test_activation_lands_at_exact_hospitality_seat_equality(
        self, api: ApiClient, promoter_headers
    ) -> None:
        """When `hospitality_seat_count` is greater than 0, `hospitality_tier_id` must be set, must belong to the same stop, and that tier's `available_seat_count` must be at least `hospitality_seat_count` — the same hospitality ceiling against the tier's `allotment` is re-checked here and reported as `ERR_HOSPITALITY_SEATS_EXCEEDED`. (§3.8) The `hospitality_seat_count` is added to the named tier's `held_seat_count`, that tier's `available_seat_count` is recomputed and its `version` increments by one — which is another reason a box-office client's `expected_ticket_tier_version` can go stale without any order being written. (§3.8)

        Design: Corner/endpoints/corner_endpoint_activation_is_conditional_on_category_and_seat_holds
        """
        state = self._three_proposals(api)
        validate_success(
            api.activate_sponsorship_activation(
                state["apex_id"], headers=promoter_headers
            ),
            200,
        )

        smaller_id = _propose_activation(
            api,
            state["stop_id"],
            sponsor_id=state["delta_id"],
            tier_id=state["tier_id"],
            entry_id=state["entry_id"],
            fee_cents=300000,
            hospitality_seat_count=5,
        )
        live = validate_success(
            api.activate_sponsorship_activation(smaller_id, headers=promoter_headers),
            200,
        )
        assert live["state"] == "ACTIVATED"

        # Five seats exactly exhaust the twenty-seat allotment.
        tier = fetch_tier(api, state["tier_id"])
        assert tier["held_seat_count"] == 20
        assert tier["available_seat_count"] == 0
        assert fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 2
        stop = fetch_stop(api, state["stop_id"])
        assert stop["sponsorship_committed_cents"] == 1200000
        assert stop["held_hospitality_seat_count"] == 20
