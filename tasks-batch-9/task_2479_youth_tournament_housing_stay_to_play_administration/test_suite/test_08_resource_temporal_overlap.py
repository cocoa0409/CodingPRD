"""Two date-interval tests with deliberately opposite endpoint semantics.

A team's stays are compared as closed intervals, so touching days collide. A
property's blocks are compared over half-open windows, so touching days do not.
Each pair here sits on the shared day, then one day later.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    ApiErrorId,
    NegotiationAction,
    RoomType,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_hotel_rep_headers,
    validate_error,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _execute(api, contract_id: str, hotel_headers) -> dict:
    """Submit a contract and have its own hotel countersign it."""
    get_success_data(
        api.negotiate_contract(
            contract_id, f.negotiation_payload(NegotiationAction.SUBMIT.value), HM
        )
    )
    return get_success_data(
        api.negotiate_contract(
            contract_id,
            f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
            hotel_headers,
        )
    )


def _two_properties_one_team_env(api) -> fx.Env:
    """Two hotels on one event, each with an executed contract and a wide block,
    and one team already holding a stay at the first property."""
    env = fx.draft_contract_env(api)
    block_a = fx.add_block(
        env, arrival_date="2026-09-08", departure_date="2026-09-15"
    )
    env.contract = _execute(api, env.contract_id, env.hotel_headers)

    hotel_b = fx.create_hotel(
        api, name="Riverfront Suites", distance_miles_from_venue=6.0
    )
    hotel_b_headers = make_hotel_rep_headers(hotel_b["id"])
    contract_b = get_success_data(
        api.create_hotel_contract(
            f.hotel_contract_payload(
                env.tournament_id, hotel_b["id"], negotiated_nightly_rate_cents=15900
            ),
            HM,
        )
    )
    block_b = get_success_data(
        api.create_room_block(
            f.room_block_payload(
                contract_b["id"],
                room_type=RoomType.KING.value,
                arrival_date="2026-09-08",
                departure_date="2026-09-15",
            ),
            HM,
        )
    )
    contract_b = _execute(api, contract_b["id"], hotel_b_headers)

    fx.add_team(env)
    fx.add_registration(env)
    env.booking = fx.add_booking(
        env,
        block=block_a,
        rooms_requested=1,
        check_in_date="2026-09-10",
        check_out_date="2026-09-12",
    )
    env.block = block_a
    env.other_block = block_b
    env.other_contract = contract_b
    return env


def _tiny_property_with_one_block_env(api) -> fx.Env:
    """A ten-room property already holding a six-room block over the nights of
    2026-09-10, 09-11 and 09-12."""
    env = fx.draft_contract_env(
        api,
        hotel_overrides={
            "name": "Tiny Host Lodge",
            "total_rooms": 10,
            "distance_miles_from_venue": 4.0,
        },
    )
    fx.add_block(env, block_size_rooms=6)
    return env


class TestTeamStayClosedIntervalAdjacentDayCollision:
    """A team's stays are closed at both ends, so an endpoint day is a collision."""

    def test_a_second_property_stay_starting_on_the_checkout_day_is_refused(self, api):
        """The held stay runs 2026-09-10 through 2026-09-12 inclusive, so a new
        stay at the other property starting on 2026-09-12 intersects it.

        PRD §3.4: "The system looks for any other booking whose registration
        belongs to the same team, whose `room_block_id` differs from the one being
        booked, whose `booking_status` is `DRAFT`, `ROOMING_LIST_SUBMITTED`,
        `CONFIRMED` or `CHECKED_OUT`, and whose stay interval — treated as
        **closed** at both ends, from `check_in_date` through `check_out_date`
        inclusive — intersects the new stay's equally closed interval."

        PRD §3.4: "Because both endpoints are inclusive, adjacency is
        **forbidden**: an existing stay ending on 2026-09-12 collides with a new
        stay starting on 2026-09-12."

        PRD §2.11: "The booking team has no live stay at another block whose dates
        touch the requested stay — otherwise `ERR_TEAM_STAY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/team_stay_closed_interval_adjacent_day_collision
        """
        env = _two_properties_one_team_env(api)
        assert env.booking["booking_status"] == "DRAFT"
        assert env.booking["projected_room_nights"] == 2
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"],
                env.other_block["id"],
                registration["version"],
                rooms_requested=1,
                check_in_date="2026-09-12",
                check_out_date="2026-09-14",
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_TEAM_STAY_OVERLAP.value, expected_status=409
        )

    def test_moving_the_arrival_one_day_clear_of_the_held_stay_is_accepted(self, api):
        """Arriving 2026-09-13 leaves the two closed intervals disjoint, so the
        same team may hold a room at the second property.

        PRD §3.4: "A team may not be checked in at two different properties on the
        same calendar day."

        PRD §3.4: "The server computes `nights` as the whole days from
        `check_in_date` up to but not including `check_out_date`, and
        `projected_room_nights` as `rooms_requested` multiplied by `nights` — the
        pre-stay estimate that cancellation penalties are assessed against."

        Design: Difficulty/resource_temporal_overlap/team_stay_closed_interval_adjacent_day_collision
        """
        env = _two_properties_one_team_env(api)
        registration = env.refresh_registration()

        booking = validate_success(
            api.create_booking(
                f.booking_payload(
                    registration["id"],
                    env.other_block["id"],
                    registration["version"],
                    rooms_requested=1,
                    check_in_date="2026-09-13",
                    check_out_date="2026-09-14",
                ),
                HM,
            ),
            expected_status=201,
        )

        assert booking["booking_status"] == "DRAFT"
        assert booking["check_in_date"] == "2026-09-13"
        assert booking["projected_room_nights"] == 1
        assert booking["room_block_id"] == env.other_block["id"]


class TestHotelAggregateNightCapacityHalfOpenAdjacencyAllowed:
    """A property's blocks are compared over half-open windows and summed."""

    def test_a_second_block_sharing_a_night_cannot_exceed_the_property_inventory(
        self, api
    ):
        """Six held rooms plus five more on the night of 2026-09-12 is eleven
        against a ten-room property, so the second block is refused.

        PRD §3.2: "For each night in the new block's half-open window, the system
        sums `block_size_rooms` over all existing room blocks whose contract points
        at the same hotel and whose own `status` is `OPEN` or `RESTRICTED` and
        whose own half-open window covers that night; if that sum plus the new
        `block_size_rooms` would exceed the hotel's `total_rooms` on any single
        night, the request is rejected with `ERR_HOTEL_NIGHT_CAPACITY_EXCEEDED`."

        PRD §3.2: "Note that this is a per-night **sum** against a ceiling, not an
        exclusive-occupation test — several blocks may cover the same night as long
        as their combined size fits the property."

        Design: Difficulty/resource_temporal_overlap/hotel_aggregate_night_capacity_half_open_adjacency_allowed
        """
        env = _tiny_property_with_one_block_env(api)
        assert env.block["block_size_rooms"] == 6
        assert env.block["status"] == "OPEN"

        response = api.create_room_block(
            f.room_block_payload(
                env.contract_id,
                room_type=RoomType.KING.value,
                block_size_rooms=5,
                arrival_date="2026-09-12",
                departure_date="2026-09-15",
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_HOTEL_NIGHT_CAPACITY_EXCEEDED.value,
            expected_status=409,
        )
        assert env.refresh_block()["block_size_rooms"] == 6

    def test_a_block_arriving_on_the_day_the_first_departs_shares_no_night(self, api):
        """Arriving 2026-09-13, the day the six-room block departs, the five extra
        rooms overlap no night at all and are held.

        PRD §3.2: "Because the interval is half-open, adjacency is permitted: a
        block departing on the 13th and a block arriving on the 13th share no night
        and never collide."

        PRD §3.2: "A new block starts at `status` `OPEN` with `rooms_committed` at
        0, `rooms_available` equal to `block_size_rooms`, `rooms_released_unsold`
        at 0, `utilization_pct` at 0 and `actualized_room_nights` at 0."

        Design: Difficulty/resource_temporal_overlap/hotel_aggregate_night_capacity_half_open_adjacency_allowed
        """
        env = _tiny_property_with_one_block_env(api)
        first_block = env.block

        block = validate_success(
            api.create_room_block(
                f.room_block_payload(
                    env.contract_id,
                    room_type=RoomType.KING.value,
                    block_size_rooms=5,
                    arrival_date="2026-09-13",
                    departure_date="2026-09-15",
                ),
                HM,
            ),
            expected_status=201,
        )

        assert block["block_size_rooms"] == 5
        assert block["arrival_date"] == "2026-09-13"
        assert block["departure_date"] == "2026-09-15"
        assert block["status"] == "OPEN"
        assert block["rooms_available"] == 5
        assert env.refresh_block(first_block)["block_size_rooms"] == 6
