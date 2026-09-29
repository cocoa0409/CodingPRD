"""Two temporal windows with deliberately different interval semantics.

A building's occupancy window is symmetric: closed at both ends and widened by
``turnaround_hours`` on each side, so a candidate that merely touches the padded
window collides with it. The touring fleet's haul window is one-sided: it hangs
off the predecessor's tear-down only, and its length is derived from the road
distance rather than from the calendar.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    confirmed_booking,
    create_season,
    fetch_season,
    fetch_stop,
    make_venue_booking_payload,
    stop_with_show_timing,
    validate_error,
    validate_success,
)


def _candidate_terms(
    season_id: str, venue_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Second-season terms for the Atlanta building, varying only the occupancy."""
    fields: Dict[str, Any] = {
        "tour_date": "2026-11-16",
        "rental_base_cents": 2800000,
        "revenue_share_pct": 0.11,
        "per_ticket_facility_fee_cents": 300,
        "load_in_start_utc": "2026-11-15T18:00:00Z",
        "tear_down_end_utc": "2026-11-16T22:00:00Z",
    }
    fields.update(overrides)
    return make_venue_booking_payload(season_id, venue_id, **fields)


def _chain_patch(**fields: Any) -> Dict[str, Any]:
    """A logistics patch that carries nothing but the transport chain fields."""
    return dict(fields)


@pytest.fixture
def atlanta_blocked_by_a_confirmed_booking(api: ApiClient) -> Dict[str, Any]:
    """One confirmed occupancy at the Atlanta building, plus an unrelated season.

    The confirmed booking sits in season one and runs from 2026-11-13T14:00:00Z to
    2026-11-15T06:00:00Z. The building's ``turnaround_hours`` is 12, so the window
    it blocks runs from 2026-11-13T02:00:00Z to 2026-11-15T18:00:00Z. Every
    candidate in these tests belongs to season two, which holds no confirmed
    booking at all, so the season-scoped rotation rule can never contribute.
    """
    state: Dict[str, Any] = {}
    first = create_season(api)
    second = create_season(
        api,
        season_name="2026-27 Iron Giants Tour",
        total_marketing_budget_cents=20000000,
    )
    state["season1_id"] = first["season_id"]
    state["season2_id"] = second["season_id"]

    blocker = confirmed_booking(api, season_id=state["season1_id"])
    state["venue_id"] = blocker["venue_id"]
    state["venue"] = blocker["venue"]
    state["blocking_booking"] = blocker["booking"]
    return state


@pytest.fixture
def consecutive_stops_thirty_three_hours_apart(api: ApiClient) -> Dict[str, Any]:
    """Two stops of one season whose bookings leave exactly 33 hours of road time.

    The Atlanta stop tears down at 2026-11-15T06:00:00Z; the Dallas stop loads in
    at 2026-11-16T15:00:00Z. The Dallas stop's show timing is already set so that
    a chain patch cannot be rejected by the show-timing triple instead.
    """
    first = confirmed_booking(api)
    second = stop_with_show_timing(
        api,
        season_id=first["season_id"],
        venue_name="Dallas Coliseum",
        market_code="DAL",
        city="Dallas",
        state_code="TX",
        tour_date="2026-11-17",
        rental_base_cents=2900000,
        revenue_share_pct=0.11,
        per_ticket_facility_fee_cents=400,
        load_in_start_utc="2026-11-16T15:00:00Z",
        tear_down_end_utc="2026-11-18T02:00:00Z",
        doors_open_utc="2026-11-17T22:00:00Z",
        show_start_utc="2026-11-17T23:00:00Z",
        show_window_minutes=150,
    )
    return {
        "season_id": first["season_id"],
        "stop1_id": first["stop_id"],
        "booking1": first["booking"],
        "stop2_id": second["stop_id"],
        "booking2": second["booking"],
        "stop2": second["stop"],
    }


class TestVenueOccupancyPadCollidesOnAnExactTouch:
    """The padded occupancy window is closed, so touching it is colliding with it."""

    def test_a_candidate_starting_on_the_padded_end_instant_collides(
        self,
        api: ApiClient,
        atlanta_blocked_by_a_confirmed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.1: "Venue occupancy intervals are treated as closed at both ends and are additionally padded by the venue's own `turnaround_hours` on each side, so intervals that merely touch collide."

        PRD §3.1: "For each other booking at the same venue whose `state` is `CONFIRMED`, the server builds a blocked interval running from that booking's `load_in_start_utc` minus `turnaround_hours` to its `tear_down_end_utc` plus `turnaround_hours`."

        PRD §3.1: "If the candidate's start is at or before the blocked interval's end and the blocked interval's start is at or before the candidate's end, the two collide and the request is rejected with `ERR_VENUE_DATE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/venue_occupancy_is_closed_and_turnaround_padded_so_an_exact_touch_collides
        """
        state = atlanta_blocked_by_a_confirmed_booking
        assert state["venue"]["turnaround_hours"] == 12
        assert state["blocking_booking"]["state"] == "CONFIRMED"
        assert state["blocking_booking"]["tear_down_end_utc"].startswith(
            "2026-11-15T06:00:00"
        )

        # The blocked window ends at tear-down plus 12 hours, 2026-11-15T18:00:00Z,
        # which is exactly where this candidate's load-in begins.
        response = api.create_venue_booking(
            _candidate_terms(state["season2_id"], state["venue_id"]),
            headers=promoter_headers,
        )
        error = validate_error(response, ApiErrorId.ERR_VENUE_DATE_CONFLICT)

        # The blocker lives in the other season, so the season-scoped rotation rule
        # has nothing to compare against and cannot own this rejection.
        assert error["error_id"] != "ERR_MARKET_ROTATION_COOLDOWN"
        assert fetch_season(api, state["season2_id"])["booking_count"] == 0
        assert fetch_season(api, state["season1_id"])["booking_count"] == 1

    def test_one_second_clear_of_the_pad_is_admitted_and_survives_acceptance(
        self,
        api: ApiClient,
        atlanta_blocked_by_a_confirmed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.1: "A fresh booking opens in `state` `TERMS_PROPOSED` with `negotiation_round` at 1, `terms_source` at `PROMOTER`, and `last_counter_by_user_id`, `confirmed_at` and `withdraw_reason` all null; the season's `booking_count` rises by one."

        PRD §3.1: "Both the occupancy check and the rotation check run twice in a booking's life: once when the terms are first proposed, and again when they are accepted, because the set of confirmed bookings can change in between."

        PRD §3.1: "On success the booking moves to `CONFIRMED`, `confirmed_at` is stamped from the logical clock, and the booking's `version` increments."

        Design: Difficulty/resource_temporal_overlap/venue_occupancy_is_closed_and_turnaround_padded_so_an_exact_touch_collides
        """
        state = atlanta_blocked_by_a_confirmed_booking

        proposed = validate_success(
            api.create_venue_booking(
                _candidate_terms(
                    state["season2_id"],
                    state["venue_id"],
                    load_in_start_utc="2026-11-15T18:00:01Z",
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        assert proposed["state"] == "TERMS_PROPOSED"
        assert proposed["negotiation_round"] == 1
        assert proposed["terms_source"] == "PROMOTER"
        assert proposed["confirmed_at"] is None
        assert fetch_season(api, state["season2_id"])["booking_count"] == 1

        # The same occupancy comparison runs again at acceptance, against the same
        # single confirmed window, and still clears it by one second.
        confirmed = validate_success(
            api.accept_venue_booking(proposed["id"], headers=promoter_headers)
        )
        assert confirmed["state"] == "CONFIRMED"
        assert confirmed["confirmed_at"] is not None
        assert confirmed["version"] > proposed["version"]

    def test_an_inverted_occupancy_interval_is_refused_under_the_same_error(
        self,
        api: ApiClient,
        atlanta_blocked_by_a_confirmed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.1: "And `load_in_start_utc` must be strictly earlier than `tear_down_end_utc`; an inverted or zero-length interval is rejected with `ERR_VENUE_DATE_CONFLICT`."

        PRD §3.1: "Bookings in `TERMS_PROPOSED`, `COUNTERED` or `WITHDRAWN` never block anything."

        Design: Difficulty/resource_temporal_overlap/venue_occupancy_is_closed_and_turnaround_padded_so_an_exact_touch_collides
        """
        state = atlanta_blocked_by_a_confirmed_booking

        response = api.create_venue_booking(
            _candidate_terms(
                state["season2_id"],
                state["venue_id"],
                tour_date="2026-11-14",
                load_in_start_utc="2026-11-14T20:00:00Z",
                tear_down_end_utc="2026-11-14T10:00:00Z",
            ),
            headers=promoter_headers,
        )
        validate_error(response, ApiErrorId.ERR_VENUE_DATE_CONFLICT)
        assert fetch_season(api, state["season2_id"])["booking_count"] == 0


class TestHaulBufferIsOneSidedAndDistanceDerived:
    """The road window is anchored only on the predecessor's tear-down."""

    def test_a_leg_demanding_thirty_four_hours_is_refused_by_the_available_thirty_three(
        self,
        api: ApiClient,
        consecutive_stops_thirty_three_hours_apart: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.2: "The required haul time in hours is the stop's `haul_distance_miles` divided by 50 miles per hour and rounded up to a whole number of hours, plus a further 10 hours of mandatory crew rest."

        PRD §3.2: "The earliest permissible load-in is the preceding stop's booking `tear_down_end_utc` advanced by that many hours. If this stop's booking `load_in_start_utc` falls strictly before that instant, the update is rejected with `ERR_HAUL_BUFFER_VIOLATION`."

        PRD §3.2: "The stop's own `haul_distance_miles` records the road miles from the preceding stop's building to this one and may not be negative; it defaults to 0."

        Design: Difficulty/resource_temporal_overlap/haul_buffer_is_a_one_sided_distance_derived_window_between_consecutive_stops
        """
        state = consecutive_stops_thirty_three_hours_apart
        assert state["booking1"]["tear_down_end_utc"].startswith("2026-11-15T06:00:00")
        assert state["booking2"]["load_in_start_utc"].startswith("2026-11-16T15:00:00")

        # 1200 miles is 24 hours of driving plus 10 of crew rest: 34 demanded
        # against the 33 the calendar leaves.
        response = api.update_tour_stop_logistics(
            state["stop2_id"],
            _chain_patch(preceding_stop_id=state["stop1_id"], haul_distance_miles=1200),
            headers=promoter_headers,
        )
        validate_error(response, ApiErrorId.ERR_HAUL_BUFFER_VIOLATION)

        untouched = fetch_stop(api, state["stop2_id"])
        assert untouched["preceding_stop_id"] is None
        assert untouched["haul_distance_miles"] == 0

    def test_a_leg_demanding_exactly_thirty_three_hours_is_admitted(
        self,
        api: ApiClient,
        consecutive_stops_thirty_three_hours_apart: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.2: "Note that this buffer is anchored one-sidedly on the predecessor's tear-down, unlike the venue's symmetric turnaround pad."

        PRD §3.2: "The transport chain is expressed by `preceding_stop_id`, which points at the stop the transporters are coming from and is null for the first stop of a chain."

        PRD §4: "Every other successful operation, including state transitions, partial updates, releases and reads, returns `200 OK`."

        Design: Difficulty/resource_temporal_overlap/haul_buffer_is_a_one_sided_distance_derived_window_between_consecutive_stops
        """
        state = consecutive_stops_thirty_three_hours_apart

        # 1150 miles is 23 hours of driving plus 10 of crew rest: exactly the 33
        # available, and the comparison is strict, so equality is admitted.
        patched = validate_success(
            api.update_tour_stop_logistics(
                state["stop2_id"],
                _chain_patch(
                    preceding_stop_id=state["stop1_id"], haul_distance_miles=1150
                ),
                headers=promoter_headers,
            )
        )
        assert patched["preceding_stop_id"] == state["stop1_id"]
        assert patched["haul_distance_miles"] == 1150

        stored = fetch_stop(api, state["stop2_id"])
        assert stored["preceding_stop_id"] == state["stop1_id"]
        assert stored["haul_distance_miles"] == 1150
        # Nothing about the successor's tear-down or the predecessor's load-in is
        # consumed by the rule, so neither bound moved.
        assert state["booking2"]["tear_down_end_utc"].startswith("2026-11-18T02:00:00")
        assert state["booking1"]["load_in_start_utc"].startswith("2026-11-13T14:00:00")

    def test_a_self_referential_chain_link_is_rejected_and_leaves_the_link_intact(
        self,
        api: ApiClient,
        consecutive_stops_thirty_three_hours_apart: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.2: "Four conditions make a chain link invalid, and all four are rejected with `ERR_ROTATION_CHAIN_INVALID`: the named predecessor is the stop itself; the predecessor belongs to a different season; the predecessor's `event_date` is on or after this stop's `event_date`; or some other stop already points at that predecessor, since a stop may be the predecessor of at most one successor."

        Design: Difficulty/resource_temporal_overlap/haul_buffer_is_a_one_sided_distance_derived_window_between_consecutive_stops
        """
        state = consecutive_stops_thirty_three_hours_apart
        validate_success(
            api.update_tour_stop_logistics(
                state["stop2_id"],
                _chain_patch(
                    preceding_stop_id=state["stop1_id"], haul_distance_miles=1150
                ),
                headers=promoter_headers,
            )
        )

        response = api.update_tour_stop_logistics(
            state["stop2_id"],
            _chain_patch(preceding_stop_id=state["stop2_id"], haul_distance_miles=1150),
            headers=promoter_headers,
        )
        validate_error(response, ApiErrorId.ERR_ROTATION_CHAIN_INVALID)
        assert fetch_stop(api, state["stop2_id"])["preceding_stop_id"] == state["stop1_id"]
