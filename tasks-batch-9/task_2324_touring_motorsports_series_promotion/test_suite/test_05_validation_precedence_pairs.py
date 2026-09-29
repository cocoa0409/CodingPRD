"""Validation precedence when a single request breaks two rules at once.

The rejection ladder is a fixed order, so a request that trips two rules gets
exactly one answer: the earlier rule's error id. Each pair below is exercised
three ways — the collision itself, then the later rule firing on its own, so the
ordering claim is not confounded with a rule that simply never fires.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_seat_pool_conserved,
    assert_venue_booking,
    make_series_promoter_headers,
    make_ticket_order_payload,
    make_ticketing_manager_headers,
    make_venue_booking_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as helpers


# ---------------------------------------------------------------------------
# Module-local scenario builders
# ---------------------------------------------------------------------------


def _sold_out_stop(api: ApiClient) -> Dict[str, Any]:
    """An on-sale stop whose only tier has been bought out down to zero seats.

    The tier is deliberately tiny — five seats — and one paid order takes all
    five, so ``available_seat_count`` is zero while the stop is still ``ON_SALE``.
    The safety provisioning is scaled to that five-seat expected attendance so the
    plan certifies and the stop can be taken on sale in the first place.
    """
    state = helpers.stop_on_sale(
        api,
        include_second_tier=False,
        tier_code="SRO",
        price_cents=4750,
        allotment=5,
        barrier_linear_feet=1200,
        catch_fence_height_ft=6,
        medical_als_staff_count=1,
        medical_bls_staff_count=2,
        ambulance_count=1,
        emergency_access_lanes=1,
        channel="RADIO",
        amount_cents=500000,
    )
    state.update(
        helpers.place_paid_ticket_order(
            api,
            state["stop_id"],
            state["tier_id"],
            qty=5,
            purchaser_name="Full House",
            purchaser_email="full@example.com",
        )
    )
    return state


def _order_walkup(api: ApiClient, stop_id: str, tier_id: str, qty: int = 3):
    """Try to buy ``qty`` more seats, reading the tier's version immediately first."""
    return api.create_ticket_order(
        make_ticket_order_payload(
            stop_id,
            tier_id,
            helpers.fetch_tier_version(api, tier_id),
            qty=qty,
            purchaser_name="Late Walkup",
            purchaser_email="walkup@example.com",
        ),
        headers=make_ticketing_manager_headers(),
    )


_ATLANTA_ARENA = {
    "venue_name": "Atlanta Arena",
    "market_code": "ATL",
    "city": "Atlanta",
    "state_code": "GA",
    "seat_capacity": 7000,
    "floor_type": "CONCRETE",
    "catch_fence_max_height_ft": 12,
    "medical_bay_count": 1,
    "load_in_hours_required": 8,
    "staging_bay_count": 3,
    "turnaround_hours": 12,
}


def _one_market_two_buildings(api: ApiClient) -> Dict[str, Any]:
    """A confirmed November 14 booking at the Dome, plus a second building in ATL.

    Both buildings carry ``market_code`` ``ATL``, so any further booking in the
    same season is inside the rotation cooldown of the confirmed one; only a
    second booking at the Dome itself can also collide with its occupancy.
    """
    state = helpers.confirmed_booking(api, market_rotation_cooldown_days=21)
    arena = helpers.create_venue(api, **_ATLANTA_ARENA)
    state["arena"] = arena["venue"]
    state["arena_id"] = arena["venue_id"]
    return state


def _propose_booking(api: ApiClient, season_id: str, venue_id: str, **overrides: Any):
    """Propose rental terms for a date at a building, as the promoter."""
    return api.create_venue_booking(
        make_venue_booking_payload(season_id, venue_id, **overrides),
        headers=make_series_promoter_headers(),
    )


def _booking_dates(api: ApiClient, season_id: str):
    """Every booking date the season currently holds, in list order."""
    rows, meta = validate_paginated(
        api.list_venue_bookings(
            {"season_id": season_id}, headers=make_series_promoter_headers()
        )
    )
    return [row["tour_date"] for row in rows], meta


# ---------------------------------------------------------------------------
# Sales state outranks the seat ledger
# ---------------------------------------------------------------------------


class TestSalesNotOpenOutranksTierSoldOut:
    """One order against a closed stop whose tier is also out of seats."""

    def test_closed_sales_beat_the_empty_seat_pool_on_one_order(
        self, api: ApiClient
    ) -> None:
        """PRD §2.10: "Where several rules could reject the same request, they are
        evaluated in a fixed order and the first failure determines the response.
        Cheap envelope checks come first, then identity and concurrency, then
        lifecycle state, then life-safety gates, then referential companions, then
        calendar feasibility, then structural constraints, and money and inventory
        ledgers last."
        PRD §3.7: "The stop's `sales_state` must be exactly `ON_SALE` —
        `SALES_PENDING`, `SALES_HALTED` and `SALES_CLOSED` all yield
        `ERR_SALES_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/sales_not_open_outranks_tier_sold_out_on_the_same_order
        """
        state = _sold_out_stop(api)
        stop_id = state["stop_id"]
        tier_id = state["tier_id"]

        closed = validate_success(
            api.close_tour_stop_sales(
                stop_id, headers=make_ticketing_manager_headers()
            ),
            expected_status=200,
        )
        assert closed["sales_state"] == "SALES_CLOSED", (
            "closing the window is what puts the lifecycle rule in play"
        )

        response = _order_walkup(api, stop_id, tier_id, qty=3)
        error = validate_error(
            response, ApiErrorId.ERR_SALES_NOT_OPEN, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_TIER_SOLD_OUT.value, (
            "the lifecycle gate sits above the inventory ledger on the rejection "
            "ladder, so the sold-out tier must not be the reported failure"
        )

        orders, meta = validate_paginated(
            api.list_ticket_orders(
                {"tour_stop_id": stop_id}, headers=make_ticketing_manager_headers()
            )
        )
        assert meta["total_count"] == 1, "the rejected order must leave no trace"
        assert [row["id"] for row in orders] == [state["order_id"]], (
            "only the original paid order survives"
        )

    def test_the_empty_seat_pool_alone_rejects_while_the_stop_is_on_sale(
        self, api: ApiClient
    ) -> None:
        """PRD §3.7: "Last of all, the tier's `available_seat_count` must be at
        least `qty`, or the order is rejected with `ERR_TIER_SOLD_OUT`."

        Design: Difficulty/priority_pair_validation_conflict/sales_not_open_outranks_tier_sold_out_on_the_same_order
        """
        state = _sold_out_stop(api)
        stop_id = state["stop_id"]
        tier_id = state["tier_id"]

        assert state["stop"]["sales_state"] == "ON_SALE", (
            "the lifecycle gate must be satisfied so only the ledger can fail"
        )
        tier_before = helpers.fetch_tier(api, tier_id)
        assert tier_before["available_seat_count"] == 0
        assert tier_before["sold_seat_count"] == 5
        assert_seat_pool_conserved(tier_before)

        response = _order_walkup(api, stop_id, tier_id, qty=3)
        error = validate_error(
            response, ApiErrorId.ERR_TIER_SOLD_OUT, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_SALES_NOT_OPEN.value, (
            "an open window cannot be the reported failure"
        )

        tier_after = helpers.fetch_tier(api, tier_id)
        assert tier_after["available_seat_count"] == 0
        assert tier_after["version"] == tier_before["version"], (
            "a rejected order does not touch the tier"
        )
        _, meta = validate_paginated(
            api.list_ticket_orders(
                {"tour_stop_id": stop_id}, headers=make_ticketing_manager_headers()
            )
        )
        assert meta["total_count"] == 1, "the rejected order must leave no trace"


# ---------------------------------------------------------------------------
# Building occupancy outranks market rotation
# ---------------------------------------------------------------------------


class TestVenueDateConflictOutranksMarketRotationCooldown:
    """One proposal that both re-enters a padded occupancy and crowds a market."""

    def test_the_occupancy_collision_beats_the_rotation_cooldown_on_one_proposal(
        self, api: ApiClient
    ) -> None:
        """PRD §2.10: "Where several rules could reject the same request, they are
        evaluated in a fixed order and the first failure determines the response."
        PRD §3.1: "If the candidate's start is at or before the blocked interval's
        end and the blocked interval's start is at or before the candidate's end,
        the two collide and the request is rejected with `ERR_VENUE_DATE_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/venue_date_conflict_outranks_market_rotation_cooldown_on_one_booking
        """
        state = _one_market_two_buildings(api)
        season_id = state["season_id"]

        response = _propose_booking(
            api,
            season_id,
            state["venue_id"],
            tour_date="2026-11-15",
            rental_base_cents=3100000,
            revenue_share_pct=0.12,
            per_ticket_facility_fee_cents=350,
            load_in_start_utc="2026-11-15T10:00:00Z",
            tear_down_end_utc="2026-11-16T02:00:00Z",
        )
        error = validate_error(
            response, ApiErrorId.ERR_VENUE_DATE_CONFLICT, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_MARKET_ROTATION_COOLDOWN.value, (
            "calendar feasibility at the building is checked before the market "
            "rotation rule, so the one-day market gap must not be the reported "
            "failure"
        )

        dates, meta = _booking_dates(api, season_id)
        assert meta["total_count"] == 1, "the rejected proposal must leave no trace"
        assert dates == ["2026-11-14"], "only the confirmed booking survives"

        incumbent = validate_success(
            api.get_venue_booking(
                state["booking_id"], headers=make_series_promoter_headers()
            )
        )
        assert_venue_booking(incumbent)
        assert incumbent["state"] == "CONFIRMED", (
            "the booking that owns the occupancy is untouched"
        )

    def test_the_rotation_cooldown_alone_rejects_a_second_building_in_the_market(
        self, api: ApiClient
    ) -> None:
        """PRD §3.1: "For each other booking of the same season whose `state` is
        `CONFIRMED` and whose venue shares the candidate venue's `market_code`, the
        server takes the absolute difference in whole days between the two
        `tour_date` values. If that gap is strictly smaller than the season's
        `market_rotation_cooldown_days`, the request is rejected with
        `ERR_MARKET_ROTATION_COOLDOWN`."

        Design: Difficulty/priority_pair_validation_conflict/venue_date_conflict_outranks_market_rotation_cooldown_on_one_booking
        """
        state = _one_market_two_buildings(api)
        season_id = state["season_id"]

        response = _propose_booking(
            api,
            season_id,
            state["arena_id"],
            tour_date="2026-11-30",
            rental_base_cents=2600000,
            revenue_share_pct=0.10,
            per_ticket_facility_fee_cents=300,
            load_in_start_utc="2026-11-29T14:00:00Z",
            tear_down_end_utc="2026-12-01T06:00:00Z",
        )
        error = validate_error(
            response, ApiErrorId.ERR_MARKET_ROTATION_COOLDOWN, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_VENUE_DATE_CONFLICT.value, (
            "a different building cannot collide with the Dome's occupancy, so "
            "only the sixteen-day market gap is left to fail"
        )

        dates, meta = _booking_dates(api, season_id)
        assert meta["total_count"] == 1, "the rejected proposal must leave no trace"
        assert dates == ["2026-11-14"]

    def test_a_market_gap_exactly_equal_to_the_cooldown_is_admitted(
        self, api: ApiClient
    ) -> None:
        """PRD §3.1: "A gap exactly equal to the cooldown is allowed."
        PRD §3.1: "A fresh booking opens in `state` `TERMS_PROPOSED` with
        `negotiation_round` at 1, `terms_source` at `PROMOTER`, and
        `last_counter_by_user_id`, `confirmed_at` and `withdraw_reason` all null;
        the season's `booking_count` rises by one."

        Design: Difficulty/priority_pair_validation_conflict/venue_date_conflict_outranks_market_rotation_cooldown_on_one_booking
        """
        state = _one_market_two_buildings(api)
        season_id = state["season_id"]

        booking = validate_success(
            _propose_booking(
                api,
                season_id,
                state["arena_id"],
                tour_date="2026-12-05",
                rental_base_cents=2600000,
                revenue_share_pct=0.10,
                per_ticket_facility_fee_cents=300,
                load_in_start_utc="2026-12-04T14:00:00Z",
                tear_down_end_utc="2026-12-06T06:00:00Z",
            ),
            expected_status=201,
        )
        assert_venue_booking(booking)
        assert booking["tour_date"] == "2026-12-05", (
            "twenty-one whole days after November 14 is exactly the cooldown"
        )
        assert booking["state"] == "TERMS_PROPOSED"
        assert booking["negotiation_round"] == 1
        assert booking["terms_source"] == "PROMOTER"

        season = helpers.fetch_season(api, season_id)
        assert season["booking_count"] == 2, (
            "the admitted proposal is counted alongside the confirmed booking"
        )
