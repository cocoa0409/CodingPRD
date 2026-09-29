"""
Requests that break two rules of the rejection order at once, and the control
requests that isolate the losing rule on its own.

Each pair below stages one request whose body and headers are held constant
while exactly one of the two live violations is cleared. The first request must
answer with the earlier-numbered rejection; the identical follow-up, with the
earlier rule satisfied and nothing else touched, must answer with the later one.
That is what distinguishes a genuinely ordered evaluation from a coincidence.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import (
    ERR_DIETARY_ACK_REQUIRED,
    ERR_INSUFFICIENT_SEATS,
    ERR_TABLE_PARTY_SIZE_MISMATCH,
    ERR_TABLE_TURN_CONFLICT,
    ERR_TICKET_CLASS_NOT_SELLABLE,
)
from test_helpers.test_users import (
    make_guest_headers,
    make_kitchen_headers,
    make_restaurant_headers,
)

# The Saturday every scenario below trades on. Saturday carries the 12500
# basis-point day-of-week factor and the HIGH tier carries 12000, so a
# 12000-cent cover prices at 18000 cents before any scarcity step.
SETUP_CLOCK = "2026-09-01T00:00:00Z"
SEATING_START = "2026-09-12T22:00:00Z"
SEATING_END = "2026-09-13T02:00:00Z"
TURN_TIME_MINUTES = 150
TURN_BUFFER_MINUTES = 15

# A party seated at 22:00 occupies the table for turn_time_minutes plus the
# table's own turn_buffer_minutes, so the occupancy runs [22:00, 00:45).
OCCUPANCY_END = "2026-09-13T00:45:00Z"
# Inside that occupancy.
OVERLAPPING_START = "2026-09-12T23:00:00Z"


def _request_reservation(api, ticket_class_id, guest_id, party_size, name):
    """POST one reservation, echoing the class version read a moment earlier.

    The version is re-read immediately before the create so that the stale-view
    rejection can never be what answers the request.
    """
    headers = make_guest_headers(guest_id)
    version = FX.ticket_class_version(api, ticket_class_id, headers)
    payload = F.reservation_payload(
        ticket_class_id,
        guest_id,
        version,
        party_size=party_size,
        primary_guest_name=name,
    )
    return api.create_reservation(payload, headers)


def _reservations_of(api, guest_id, headers):
    """Every reservation the given guest holds, through the guest_id filter."""
    rows, _meta = validate_paginated(
        api.list_reservations(headers, {"guest_id": guest_id, "limit": 100})
    )
    return rows


def _paused_short_pool_world(api):
    """A PAUSED 3-seat class holding exactly 1 unsold seat, plus a guest who
    wants 2 of them.

    One confirmed party of 2 takes the class to seats_sold 2 and
    seats_available 1; the manager then pauses it, which moves no seat. A
    request for 2 seats therefore breaks the sellable-status rule and the
    drawing-pool rule at the same time.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725, prep_lead_minutes=45)
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
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=TURN_TIME_MINUTES,
        seats_capacity=3,
        demand_tier="HIGH",
        waitlist_policy="YIELD_WEIGHTED",
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=3,
        min_party_size=1,
        max_party_size=3,
    )
    FX.publish_service(api, restaurant["id"], service["id"])

    holder = FX.create_guest(api, display_name="Pause Holder")
    requester = FX.create_guest(api, display_name="Pause Requester")
    holder_reservation = FX.confirmed_reservation(
        api, ticket_class["id"], holder["id"], party_size=2
    )
    paused = get_success_data(api.pause_ticket_class(ticket_class["id"], manager))
    return {
        "manager": manager,
        "ticket_class_id": ticket_class["id"],
        "holder": holder,
        "holder_reservation": holder_reservation,
        "requester": requester,
        "paused_class": paused,
    }


class TestNotSellableStateBeatsInsufficientSeats:
    """A paused class and a short seat pool on one reservation create."""

    def test_paused_class_is_refused_before_the_seat_pool_is_consulted(self, api):
        """Both rules are live, and the sellable-status rule answers the request.

        "The ticket class is sellable: `OPEN` or `RELEASED` for a direct
        reservation, and `OPEN`, `RELEASED` or `SOLD_OUT` for a waitlist claim,
        with `PAUSED` and `CLOSED` always failing — on reservation creation and
        waitlist claim — otherwise `ERR_TICKET_CLASS_NOT_SELLABLE`."

        Design: Difficulty/priority_pair_validation_conflict/not_sellable_state_beats_insufficient_seats_constraint
        """
        world = _paused_short_pool_world(api)
        requester_headers = make_guest_headers(world["requester"]["id"])

        # Both conditions stand before the attempt: the class is PAUSED, and it
        # holds one unsold seat against a request for two.
        before = FX.read_ticket_class(
            api, world["ticket_class_id"], world["manager"]
        )
        A.assert_seat_pool(
            before, sold=2, held=0, released=0, available=1, status="PAUSED"
        )

        response = _request_reservation(
            api,
            world["ticket_class_id"],
            world["requester"]["id"],
            2,
            "Pause Requester",
        )
        validate_error(response, ERR_TICKET_CLASS_NOT_SELLABLE, 409)

        # A rejected create commits nothing at all.
        assert _reservations_of(api, world["requester"]["id"], requester_headers) == []
        after = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(
            after, sold=2, held=0, released=0, available=1, status="PAUSED"
        )

    def test_resuming_the_class_surfaces_the_short_drawing_pool(self, api):
        """With the status rule satisfied the pool rule answers the same request.

        "Resuming writes no seat counter of its own; it simply lets the ladder
        run again, and the class lands on exactly one of three states according
        to the pools as they stand at that moment."

        Design: Difficulty/priority_pair_validation_conflict/not_sellable_state_beats_insufficient_seats_constraint
        """
        world = _paused_short_pool_world(api)
        requester_headers = make_guest_headers(world["requester"]["id"])

        resumed = get_success_data(
            api.resume_ticket_class(world["ticket_class_id"], world["manager"])
        )
        # The resume moved the status and nothing else: one unsold seat still.
        A.assert_seat_pool(
            resumed, sold=2, held=0, released=0, available=1, status="OPEN"
        )

        response = _request_reservation(
            api,
            world["ticket_class_id"],
            world["requester"]["id"],
            2,
            "Pause Requester",
        )
        validate_error(response, ERR_INSUFFICIENT_SEATS, 409)

        assert _reservations_of(api, world["requester"]["id"], requester_headers) == []
        after = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(
            after, sold=2, held=0, released=0, available=1, status="OPEN"
        )

    def test_one_seat_sells_from_the_resumed_class_the_two_seat_request_lost(
        self, api
    ):
        """The pool rule was about the party, not about the class being unsellable.

        "The drawing pool holds at least `party_size` seats — `seats_available`
        for a list-priced sale, `seats_released` for a release-priced promotion
        — on reservation creation and on waitlist promotion — otherwise
        `ERR_INSUFFICIENT_SEATS`."

        Design: Difficulty/priority_pair_validation_conflict/not_sellable_state_beats_insufficient_seats_constraint
        """
        world = _paused_short_pool_world(api)
        requester_headers = make_guest_headers(world["requester"]["id"])

        # While the class is PAUSED even a party the pool can seat is refused on
        # the status rule.
        paused_single = _request_reservation(
            api,
            world["ticket_class_id"],
            world["requester"]["id"],
            1,
            "Pause Requester",
        )
        validate_error(paused_single, ERR_TICKET_CLASS_NOT_SELLABLE, 409)

        get_success_data(
            api.resume_ticket_class(world["ticket_class_id"], world["manager"])
        )
        resumed_single = _request_reservation(
            api,
            world["ticket_class_id"],
            world["requester"]["id"],
            1,
            "Pause Requester",
        )
        held = get_success_data(resumed_single, 201)
        A.assert_fulfillment_status(held, "PENDING")
        A.assert_payment_status(held, "UNPAID")
        assert held["party_size"] == 1

        after = FX.read_ticket_class(api, world["ticket_class_id"], world["manager"])
        A.assert_seat_pool(
            after, sold=2, held=1, released=0, available=0, status="SOLD_OUT"
        )
        assert len(
            _reservations_of(api, world["requester"]["id"], requester_headers)
        ) == 1


def _pending_anaphylaxis_on_a_busy_table_world(api):
    """A table already occupied [22:00, 00:45) and a second confirmed party
    carrying one still-`PENDING` ANAPHYLAXIS note.

    Assigning that second party inside the occupancy breaks the acknowledgement
    gate and the turn interval at the same time.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725, prep_lead_minutes=45)
    manager = make_restaurant_headers(restaurant["id"])
    kitchen = make_kitchen_headers(restaurant["id"])
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
        seats_min=2,
        seats_max=4,
        turn_buffer_minutes=TURN_BUFFER_MINUTES,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=TURN_TIME_MINUTES,
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

    guest_one = FX.create_guest(api, display_name="Safety One")
    guest_two = FX.create_guest(api, display_name="Safety Two")
    seated_party = FX.confirmed_reservation(
        api, ticket_class["id"], guest_one["id"], party_size=2
    )
    seated_party = FX.assign_table(
        api, restaurant["id"], seated_party["id"], table["id"], SEATING_START
    )
    candidate = FX.confirmed_reservation(
        api, ticket_class["id"], guest_two["id"], party_size=2
    )
    note = FX.add_dietary_note(
        api,
        candidate["id"],
        guest_two["id"],
        guest_index=2,
        severity="ANAPHYLAXIS",
        restriction_code="SHELLFISH",
        note_text="no shared fryer",
    )
    return {
        "manager": manager,
        "kitchen": kitchen,
        "restaurant_id": restaurant["id"],
        "table": table,
        "occupant": seated_party,
        "candidate": candidate,
        "guest_two": guest_two,
        "note": note,
    }


def _assign(api, world, seat_from_utc):
    """Attempt the assignment under test, holding the payload constant."""
    return api.assign_table(
        world["candidate"]["id"],
        F.assign_table_payload(world["table"]["id"], seat_from_utc),
        world["manager"],
    )


class TestDietaryAckSafetyBeatsTableTurnTemporal:
    """An unacknowledged anaphylaxis note and an occupied turn on one assignment."""

    def test_unacked_anaphylaxis_note_is_refused_before_the_turn_is_tested(self, api):
        """Both rules are live, and the acknowledgement gate answers the request.

        "Before any of that, four checks fire in the order fixed by §2.11: the
        safety gates of §3.4 come first, then the table turn interval, then the
        table's provenance and seat band, then the kitchen's aggregate load."

        Design: Difficulty/priority_pair_validation_conflict/dietary_ack_safety_beats_table_turn_temporal
        """
        world = _pending_anaphylaxis_on_a_busy_table_world(api)
        guest_headers = make_guest_headers(world["guest_two"]["id"])

        # The occupancy the candidate is about to collide with.
        assert world["occupant"]["assigned_table_id"] == world["table"]["id"]
        A.assert_instant_equals(world["occupant"]["seat_from_utc"], SEATING_START, "seat_from_utc")
        # And the note that outranks it.
        assert world["note"]["severity"] == "ANAPHYLAXIS"
        assert world["note"]["ack_status"] == "PENDING"

        response = _assign(api, world, OVERLAPPING_START)
        validate_error(response, ERR_DIETARY_ACK_REQUIRED, 422)

        # A refused assignment writes neither field.
        candidate = FX.read_reservation(api, world["candidate"]["id"], guest_headers)
        assert candidate["assigned_table_id"] is None
        assert candidate["seat_from_utc"] is None
        # A baseline of 2 covers at 12 minutes each plus one 15-minute
        # anaphylaxis note, counted regardless of ack_status.
        assert candidate["prep_minutes_total"] == 39

    def test_acknowledging_the_note_surfaces_the_turn_conflict(self, api):
        """With the note ACKED the same assignment answers on the turn interval.

        "The candidate collides with an existing occupancy when the candidate's
        start falls strictly before that occupancy's end **and** that
        occupancy's start falls strictly before the candidate's end; any
        collision is refused with `ERR_TABLE_TURN_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/dietary_ack_safety_beats_table_turn_temporal
        """
        world = _pending_anaphylaxis_on_a_busy_table_world(api)
        guest_headers = make_guest_headers(world["guest_two"]["id"])

        acked = FX.ack_note(api, world["restaurant_id"], world["note"]["id"])
        assert acked["ack_status"] == "ACKED"

        response = _assign(api, world, OVERLAPPING_START)
        validate_error(response, ERR_TABLE_TURN_CONFLICT, 409)

        candidate = FX.read_reservation(api, world["candidate"]["id"], guest_headers)
        assert candidate["assigned_table_id"] is None
        assert candidate["seat_from_utc"] is None
        assert candidate["prep_minutes_total"] == 39

    def test_the_note_blocks_a_turn_the_table_would_otherwise_accept(self, api):
        """The safety gate also refuses an assignment with no turn conflict at all.

        "Every dietary note on the reservation whose `severity` is `ANAPHYLAXIS`
        has `ack_status` `ACKED`, on table assignment **and** on seating —
        otherwise `ERR_DIETARY_ACK_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/dietary_ack_safety_beats_table_turn_temporal
        """
        world = _pending_anaphylaxis_on_a_busy_table_world(api)
        guest_headers = make_guest_headers(world["guest_two"]["id"])

        # A start at the exact instant the existing occupancy ends collides with
        # nothing, yet the still-pending note refuses it anyway.
        blocked = _assign(api, world, OCCUPANCY_END)
        validate_error(blocked, ERR_DIETARY_ACK_REQUIRED, 422)

        FX.ack_note(api, world["restaurant_id"], world["note"]["id"])
        assigned = get_success_data(_assign(api, world, OCCUPANCY_END), 200)
        assert assigned["assigned_table_id"] == world["table"]["id"]
        A.assert_instant_equals(assigned["seat_from_utc"], OCCUPANCY_END, "seat_from_utc")
        # Until the party is seated the end of its turn is still unpinned.
        assert assigned["seat_to_utc"] is None

        candidate = FX.read_reservation(api, world["candidate"]["id"], guest_headers)
        assert candidate["assigned_table_id"] == world["table"]["id"]


def _attempt_assign(api, manager, reservation_id, table_id, seat_from_utc):
    """Attempt one table assignment and hand back the raw response."""
    return api.assign_table(
        reservation_id,
        F.assign_table_payload(table_id, seat_from_utc),
        manager,
    )


def _busy_two_seat_table_world(api):
    """A table that seats exactly 2 and is already occupied [22:00, 00:45),
    plus a confirmed party of 3 and a confirmed party of 2 with no table.

    Assigning the party of 3 inside the occupancy breaks the turn interval and
    the table's seat band at the same time; the party of 2 breaks the turn
    interval alone.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725, prep_lead_minutes=45)
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
        seats_min=2,
        seats_max=2,
        turn_buffer_minutes=TURN_BUFFER_MINUTES,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=TURN_TIME_MINUTES,
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

    guest_one = FX.create_guest(api, display_name="Table One")
    guest_two = FX.create_guest(api, display_name="Table Two")
    guest_three = FX.create_guest(api, display_name="Table Three")
    occupant = FX.confirmed_reservation(
        api, ticket_class["id"], guest_one["id"], party_size=2
    )
    occupant = FX.assign_table(
        api, restaurant["id"], occupant["id"], table["id"], SEATING_START
    )
    oversized = FX.confirmed_reservation(
        api, ticket_class["id"], guest_two["id"], party_size=3
    )
    in_band = FX.confirmed_reservation(
        api, ticket_class["id"], guest_three["id"], party_size=2
    )
    return {
        "manager": manager,
        "table": table,
        "occupant": occupant,
        "oversized": oversized,
        "guest_two": guest_two,
        "in_band": in_band,
        "guest_three": guest_three,
    }


class TestTableTurnTemporalBeatsPartySizeReferential:
    """An occupied turn and a party the table cannot seat on one assignment."""

    def test_occupied_turn_is_refused_before_the_seat_band_is_tested(self, api):
        """Both rules are live, and the turn interval answers the request.

        "The candidate table occupancy does not overlap an existing occupancy on
        that table, on table assignment — otherwise `ERR_TABLE_TURN_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/table_turn_temporal_beats_party_size_referential
        """
        world = _busy_two_seat_table_world(api)
        guest_headers = make_guest_headers(world["guest_two"]["id"])

        # The seat band is breached by the party of 3 on every attempt below.
        assert world["oversized"]["party_size"] == 3
        assert world["table"]["seats_min"] == 2
        assert world["table"]["seats_max"] == 2
        # A Saturday HIGH cover at 18000 cents, three covers, 7.25 percent on
        # the ticket line, and thirty percent of the total down.
        A.assert_money_breakdown(
            world["oversized"],
            ticket_subtotal=54000,
            service_charge=3915,
            grand_total=57915,
            deposit_due=17375,
        )

        response = _attempt_assign(
            api,
            world["manager"],
            world["oversized"]["id"],
            world["table"]["id"],
            OVERLAPPING_START,
        )
        validate_error(response, ERR_TABLE_TURN_CONFLICT, 409)

        candidate = FX.read_reservation(api, world["oversized"]["id"], guest_headers)
        assert candidate["assigned_table_id"] is None
        assert candidate["seat_from_utc"] is None

    def test_adjacent_start_clears_the_turn_and_leaves_the_seat_band(self, api):
        """Moving the start to the occupancy's end exposes the seat-band rule.

        "The party size sits inside the table's seat band, on table assignment —
        otherwise `ERR_TABLE_PARTY_SIZE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/table_turn_temporal_beats_party_size_referential
        """
        world = _busy_two_seat_table_world(api)
        guest_headers = make_guest_headers(world["guest_two"]["id"])

        response = _attempt_assign(
            api,
            world["manager"],
            world["oversized"]["id"],
            world["table"]["id"],
            OCCUPANCY_END,
        )
        validate_error(response, ERR_TABLE_PARTY_SIZE_MISMATCH, 422)

        candidate = FX.read_reservation(api, world["oversized"]["id"], guest_headers)
        assert candidate["assigned_table_id"] is None
        assert candidate["seat_from_utc"] is None
        A.assert_fulfillment_status(candidate, "CONFIRMED")

    def test_an_in_band_party_is_refused_on_the_turn_and_accepted_when_adjacent(
        self, api
    ):
        """The turn interval refuses a party the seat band welcomes.

        "Because both comparisons are strict, a party starting at exactly the
        instant another party's occupancy ends does not collide — a table freed
        at 00:45 may be re-seated at 00:45, but not at 00:44."

        Design: Difficulty/priority_pair_validation_conflict/table_turn_temporal_beats_party_size_referential
        """
        world = _busy_two_seat_table_world(api)
        guest_headers = make_guest_headers(world["guest_three"]["id"])

        assert world["in_band"]["party_size"] == 2
        overlapping = _attempt_assign(
            api,
            world["manager"],
            world["in_band"]["id"],
            world["table"]["id"],
            OVERLAPPING_START,
        )
        validate_error(overlapping, ERR_TABLE_TURN_CONFLICT, 409)

        adjacent = get_success_data(
            _attempt_assign(
                api,
                world["manager"],
                world["in_band"]["id"],
                world["table"]["id"],
                OCCUPANCY_END,
            ),
            200,
        )
        assert adjacent["assigned_table_id"] == world["table"]["id"]
        A.assert_instant_equals(adjacent["seat_from_utc"], OCCUPANCY_END, "seat_from_utc")

        candidate = FX.read_reservation(api, world["in_band"]["id"], guest_headers)
        assert candidate["assigned_table_id"] == world["table"]["id"]
        # The occupant it sits next to is untouched by the successful assignment.
        A.assert_instant_equals(world["occupant"]["seat_from_utc"], SEATING_START, "seat_from_utc")
