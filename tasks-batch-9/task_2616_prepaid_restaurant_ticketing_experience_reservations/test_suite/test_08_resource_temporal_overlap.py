"""
The two independent interval constraints that guard a table assignment: the
table's own half-open turn occupancy, and the service kitchen line's closed
prep window whose loads aggregate whenever the windows merely touch.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import make_restaurant_headers

# The Saturday evening both resources are rationed on. Saturday carries the
# 12500 basis-point day-of-week factor.
SEATING_START = "2026-09-12T22:00:00Z"
SEATING_END = "2026-09-13T02:00:00Z"
SETUP_CLOCK = "2026-09-01T00:00:00Z"

# The first party's seating instant. With turn_time_minutes 150 and the table's
# own turn_buffer_minutes 15 the occupancy runs 165 minutes.
FIRST_SEAT_FROM = "2026-09-12T22:00:00Z"
# 22:00 plus 150 minutes: the turn is over but the buffer is not.
TURN_TIME_END = "2026-09-13T00:30:00Z"
# One minute short of the occupancy end.
ONE_MINUTE_INSIDE = "2026-09-13T00:44:00Z"
# 22:00 plus 165 minutes: the first instant outside the occupancy.
OCCUPANCY_END = "2026-09-13T00:45:00Z"

# The prep windows of the kitchen line, with prep_lead_minutes 45. R1 seated at
# 22:00 occupies [21:15, 22:00]; a 22:45 candidate occupies [22:00, 22:45] and
# touches it, a 22:46 candidate occupies [22:01, 22:46] and does not.
TOUCHING_SEAT_FROM = "2026-09-12T22:45:00Z"
SEPARATED_SEAT_FROM = "2026-09-12T22:46:00Z"


def _turn_world(api):
    """A published Saturday HIGH service, one table seating 2 to 4 with a
    15-minute turn buffer, and two CONFIRMED parties of 2 for different guests.
    The first party is already assigned to the table from 22:00; the second is
    unassigned and carries no dietary notes, so nothing but the turn interval
    can refuse its assignment.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    manager = make_restaurant_headers(restaurant["id"])
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    table = FX.create_table(
        api,
        restaurant["id"],
        table_code="A1",
        seats_min=2,
        seats_max=4,
        turn_buffer_minutes=15,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="HIGH",
        kitchen_prep_capacity_minutes=600,
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=20,
        min_party_size=1,
        max_party_size=8,
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest_one = FX.create_guest(api, display_name="Adj One")
    guest_two = FX.create_guest(api, display_name="Adj Two")

    first = FX.confirmed_reservation(
        api, ticket_class["id"], guest_one["id"], party_size=2
    )
    FX.assign_table(
        api, restaurant["id"], first["id"], table["id"], FIRST_SEAT_FROM
    )
    second = FX.confirmed_reservation(
        api, ticket_class["id"], guest_two["id"], party_size=2
    )
    return {
        "restaurant_id": restaurant["id"],
        "manager": manager,
        "table": table,
        "service": service,
        "first": first,
        "second": second,
    }


class TestTableOccupancyHalfOpenAdjacency:
    """One physical table, two parties, and the one minute that separates a
    refusal from an acceptance."""

    def test_a_start_one_minute_inside_the_occupancy_is_refused(self, api):
        """A 00:44 start still overlaps the occupancy that ends at 00:45.

        "Because both comparisons are strict, a party starting at exactly the
        instant another party's occupancy ends does not collide — a table freed
        at 00:45 may be re-seated at 00:45, but not at 00:44."

        Design: Difficulty/resource_temporal_overlap/table_occupancy_half_open_adjacency_allowed
        """
        world = _turn_world(api)
        manager = world["manager"]

        response = api.assign_table(
            world["second"]["id"],
            F.assign_table_payload(world["table"]["id"], ONE_MINUTE_INSIDE),
            manager,
        )
        validate_error(response, "ERR_TABLE_TURN_CONFLICT", 409)

        # The refused attempt wrote nothing on either reservation.
        second = FX.read_reservation(api, world["second"]["id"], manager)
        assert second["assigned_table_id"] is None
        assert second["seat_from_utc"] is None
        A.assert_fulfillment_status(second, "CONFIRMED")

        first = FX.read_reservation(api, world["first"]["id"], manager)
        assert first["assigned_table_id"] == world["table"]["id"]
        A.assert_instant_equals(first["seat_from_utc"], FIRST_SEAT_FROM, "seat_from_utc")
        A.assert_fulfillment_status(first, "CONFIRMED")

    def test_a_start_at_the_exact_occupancy_end_is_accepted(self, api):
        """The boundary instant belongs to the later party, so 00:45 is legal.

        "The candidate collides with an existing occupancy when the candidate's
        start falls strictly before that occupancy's end **and** that
        occupancy's start falls strictly before the candidate's end; any
        collision is refused with `ERR_TABLE_TURN_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/table_occupancy_half_open_adjacency_allowed
        """
        world = _turn_world(api)
        manager = world["manager"]

        assigned = get_success_data(
            api.assign_table(
                world["second"]["id"],
                F.assign_table_payload(world["table"]["id"], OCCUPANCY_END),
                manager,
            )
        )
        assert assigned["assigned_table_id"] == world["table"]["id"]
        A.assert_instant_equals(assigned["seat_from_utc"], OCCUPANCY_END, "seat_from_utc")
        # Neither party has been seated, so no turn end has been pinned yet.
        assert assigned["seat_to_utc"] is None
        A.assert_version_advanced_by(
            assigned["version"], world["second"]["version"]
        )

        # Both parties now sit on the same table with touching occupancies.
        first = FX.read_reservation(api, world["first"]["id"], manager)
        assert first["assigned_table_id"] == world["table"]["id"]
        A.assert_instant_equals(first["seat_from_utc"], FIRST_SEAT_FROM, "seat_from_utc")
        assert first["seat_to_utc"] is None
        A.assert_fulfillment_status(first, "CONFIRMED")
        A.assert_fulfillment_status(assigned, "CONFIRMED")

    def test_the_turn_buffer_is_part_of_the_occupancy(self, api):
        """A start at the end of the turn time alone still collides.

        "The candidate occupancy begins at the proposed `seat_from_utc` and ends
        at that instant plus the service's `turn_time_minutes` plus the table's
        own `turn_buffer_minutes`, and the end instant is **excluded** from the
        interval."

        Design: Difficulty/resource_temporal_overlap/table_occupancy_half_open_adjacency_allowed
        """
        world = _turn_world(api)
        manager = world["manager"]

        # 00:30 is 150 minutes after 22:00 — the turn is done, the 15-minute
        # buffer is not, so the occupancy has not ended.
        response = api.assign_table(
            world["second"]["id"],
            F.assign_table_payload(world["table"]["id"], TURN_TIME_END),
            manager,
        )
        validate_error(response, "ERR_TABLE_TURN_CONFLICT", 409)

        second = FX.read_reservation(api, world["second"]["id"], manager)
        assert second["assigned_table_id"] is None
        assert second["version"] == world["second"]["version"]

        # Fifteen minutes later, once the buffer has run out, the same table
        # takes the same party.
        accepted = get_success_data(
            api.assign_table(
                world["second"]["id"],
                F.assign_table_payload(world["table"]["id"], OCCUPANCY_END),
                manager,
            )
        )
        A.assert_instant_equals(accepted["seat_from_utc"], OCCUPANCY_END, "seat_from_utc")
        assert accepted["assigned_table_id"] == world["table"]["id"]


def _prep_world(api, *, kitchen_prep_capacity_minutes=40):
    """A published Saturday HIGH service with two free tables and a tight
    kitchen line. Two CONFIRMED parties of 2 each cost the line 24 prep minutes
    — a party of 2 at 12 minutes per cover, with no dietary notes and no add-on
    lines. The first is assigned to K1 from 22:00; the second is unassigned and
    will be offered the empty K2, so no table turn interval is ever in play.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=725,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    manager = make_restaurant_headers(restaurant["id"])
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    table_one = FX.create_table(
        api,
        restaurant["id"],
        table_code="K1",
        seats_min=2,
        seats_max=4,
        turn_buffer_minutes=15,
    )
    table_two = FX.create_table(
        api,
        restaurant["id"],
        table_code="K2",
        seats_min=2,
        seats_max=4,
        turn_buffer_minutes=15,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="HIGH",
        kitchen_prep_capacity_minutes=kitchen_prep_capacity_minutes,
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=20,
        min_party_size=1,
        max_party_size=8,
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest_one = FX.create_guest(api, display_name="Pass One")
    guest_two = FX.create_guest(api, display_name="Pass Two")

    first = FX.confirmed_reservation(
        api, ticket_class["id"], guest_one["id"], party_size=2
    )
    FX.assign_table(
        api, restaurant["id"], first["id"], table_one["id"], FIRST_SEAT_FROM
    )
    second = FX.confirmed_reservation(
        api, ticket_class["id"], guest_two["id"], party_size=2
    )
    return {
        "restaurant_id": restaurant["id"],
        "manager": manager,
        "table_one": table_one,
        "table_two": table_two,
        "service": service,
        "first": first,
        "second": second,
    }


class TestKitchenPrepWindowClosedIntervalAggregate:
    """The service's kitchen line is a different resource from the table, and
    its window includes both endpoints, so touching windows aggregate."""

    def test_touching_prep_windows_aggregate_and_oversubscribe_the_line(self, api):
        """A 22:45 start touches the 22:00 window end, so 24 plus 24 is charged.

        "The aggregate load starts as the candidate's own `prep_minutes_total`
        and then adds the `prep_minutes_total` of every other reservation **of
        the same service** that already holds a table assignment and whose
        seating dimension reads `CONFIRMED` or `SEATED`, provided that
        reservation's own closed prep window touches or overlaps the
        candidate's — that is, provided the candidate's window start is at or
        before the other's window end, and the other's window start is at or
        before the candidate's window end."

        Design: Difficulty/resource_temporal_overlap/kitchen_line_closed_interval_aggregate_overlap
        """
        world = _prep_world(api, kitchen_prep_capacity_minutes=40)
        manager = world["manager"]

        first = FX.read_reservation(api, world["first"]["id"], manager)
        second = FX.read_reservation(api, world["second"]["id"], manager)
        assert first["prep_minutes_total"] == 24
        assert second["prep_minutes_total"] == 24

        # K2 holds nobody at all, so the turn interval cannot refuse this.
        response = api.assign_table(
            world["second"]["id"],
            F.assign_table_payload(world["table_two"]["id"], TOUCHING_SEAT_FROM),
            manager,
        )
        validate_error(response, "ERR_KITCHEN_PREP_OVERSUBSCRIBED", 422)

        refused = FX.read_reservation(api, world["second"]["id"], manager)
        assert refused["assigned_table_id"] is None
        assert refused["seat_from_utc"] is None
        assert refused["version"] == second["version"]

    def test_windows_separated_by_one_minute_do_not_aggregate(self, api):
        """At 22:46 the two windows share no instant, so the load is 24 alone.

        "The candidate's prep window runs from the proposed `seat_from_utc` less
        the restaurant's `prep_lead_minutes` up to and including that
        `seat_from_utc`."

        Design: Difficulty/resource_temporal_overlap/kitchen_line_closed_interval_aggregate_overlap
        """
        world = _prep_world(api, kitchen_prep_capacity_minutes=40)
        manager = world["manager"]

        assigned = get_success_data(
            api.assign_table(
                world["second"]["id"],
                F.assign_table_payload(
                    world["table_two"]["id"], SEPARATED_SEAT_FROM
                ),
                manager,
            )
        )
        assert assigned["assigned_table_id"] == world["table_two"]["id"]
        A.assert_instant_equals(assigned["seat_from_utc"], SEPARATED_SEAT_FROM, "seat_from_utc")
        assert assigned["prep_minutes_total"] == 24
        assert assigned["seat_to_utc"] is None
        A.assert_fulfillment_status(assigned, "CONFIRMED")

        # The earlier party keeps its own table and its own window.
        first = FX.read_reservation(api, world["first"]["id"], manager)
        assert first["assigned_table_id"] == world["table_one"]["id"]
        A.assert_instant_equals(first["seat_from_utc"], FIRST_SEAT_FROM, "seat_from_utc")
        assert first["prep_minutes_total"] == 24

    def test_an_aggregate_exactly_equal_to_capacity_is_accepted(self, api):
        """48 minutes of touching load against a 48-minute line is legal.

        "If the resulting aggregate is **strictly greater** than the service's
        `kitchen_prep_capacity_minutes`, the assignment is refused with
        `ERR_KITCHEN_PREP_OVERSUBSCRIBED`; a load exactly equal to capacity is
        accepted."

        Design: Difficulty/resource_temporal_overlap/kitchen_line_closed_interval_aggregate_overlap
        """
        world = _prep_world(api, kitchen_prep_capacity_minutes=48)
        manager = world["manager"]
        assert world["service"]["kitchen_prep_capacity_minutes"] == 48

        assigned = get_success_data(
            api.assign_table(
                world["second"]["id"],
                F.assign_table_payload(
                    world["table_two"]["id"], TOUCHING_SEAT_FROM
                ),
                manager,
            )
        )
        assert assigned["assigned_table_id"] == world["table_two"]["id"]
        A.assert_instant_equals(assigned["seat_from_utc"], TOUCHING_SEAT_FROM, "seat_from_utc")
        assert assigned["prep_minutes_total"] == 24

        first = FX.read_reservation(api, world["first"]["id"], manager)
        assert first["prep_minutes_total"] == 24
        assert first["assigned_table_id"] == world["table_one"]["id"]
