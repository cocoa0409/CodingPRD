"""Service surfaces: catering prep-station overlap, tasting-room buffer & seats, host
eligibility, tasting-event cancel state, and the subscription pause/resume cycle."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer, create_prep_station, create_order, create_tasting_room,
    create_tasting_event_payload, setup_scheduled_tasting_event, setup_active_subscription,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
CS = TEST_USERS["counter_staff_headers"]


def _catering_payload(customer_id, station_id, start, end):
    return {"order_type": "CATERING", "customer_id": customer_id, "prep_station_id": station_id,
            "prep_window_start": start, "prep_window_end": end, "event_date": "2026-08-01T18:00:00Z"}


# ─── resource_temporal_overlap / prep_station_window_overlap ───────────────
class TestPrepStationOverlap:
    def _live_station(self, api):
        customer = create_customer(name="Event Host")
        station = create_prep_station(name="Station 1")
        api.create_order(_catering_payload(customer["id"], station["id"],
                                           "2026-08-01T09:00:00Z", "2026-08-01T12:00:00Z"), CS)
        return customer, station

    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "a catering order's half-open prep window `[prep_window_start,
        prep_window_end)` must not overlap the prep window of any other live catering order —
        one whose `fulfillment_status` is `DRAFT`, `SUBMITTED`, or `FULFILLED` — on the same
        prep station."

        Design: Difficulty/resource_temporal_overlap/prep_station_window_overlap
        """
        customer, station = self._live_station(api)
        res = api.create_order(_catering_payload(customer["id"], station["id"],
                                                 "2026-08-01T11:00:00Z", "2026-08-01T13:00:00Z"), CS)
        validate_error(res, "ERR_PREP_STATION_CONFLICT")

    def test_touching_endpoint_window_allowed(self, api):
        """PRD §3.5: "A prep station admits a single occupant at a time; two windows that merely
        touch at an endpoint (one window's end equal to the other's start) do not overlap and
        are permitted."

        Design: Difficulty/resource_temporal_overlap/prep_station_window_overlap
        """
        customer, station = self._live_station(api)
        res = api.create_order(_catering_payload(customer["id"], station["id"],
                                                 "2026-08-01T12:00:00Z", "2026-08-01T14:00:00Z"), CS)
        validate_success(res, 201)


# ─── resource_temporal_overlap / tasting_room_buffer_gap ───────────────────
class TestTastingRoomBuffer:
    def test_gap_below_buffer_rejected(self, api):
        """PRD §3.9: "the room's buffer must be respected: for any other `SCHEDULED` event in
        the same room whose time interval does **not** overlap this one, the gap between the two
        must be at least `buffer_minutes`; a nearer non-overlapping neighbor is rejected with
        `ERR_TASTING_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tasting_room_buffer_gap
        """
        sc = setup_scheduled_tasting_event(seats=5, buffer_minutes=30, seat_capacity=20,
                                           start_at="2026-07-05T10:00:00Z",
                                           end_at="2026-07-05T11:00:00Z")
        res = api.create_tasting_event(create_tasting_event_payload(
            sc["room"]["id"], sc["customer"]["id"],
            "2026-07-05T11:15:00Z", "2026-07-05T12:00:00Z", 5), CS)   # 15-min gap < 30
        validate_error(res, "ERR_TASTING_ROOM_CONFLICT")

    def test_gap_exactly_buffer_allowed(self, api):
        """PRD §3.9: "the room's buffer must be respected: for any other `SCHEDULED` event in
        the same room whose time interval does **not** overlap this one, the gap between the two
        must be at least `buffer_minutes`; a nearer non-overlapping neighbor is rejected with
        `ERR_TASTING_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tasting_room_buffer_gap
        """
        sc = setup_scheduled_tasting_event(seats=5, buffer_minutes=30, seat_capacity=20,
                                           start_at="2026-07-05T10:00:00Z",
                                           end_at="2026-07-05T11:00:00Z")
        res = api.create_tasting_event(create_tasting_event_payload(
            sc["room"]["id"], sc["customer"]["id"],
            "2026-07-05T11:30:00Z", "2026-07-05T12:00:00Z", 5), CS)   # exactly 30-min gap
        validate_success(res, 201)


# ─── cross_entity_state_dependency / tasting_requires_customer_active ──────
class TestTastingRequiresCustomerActive:
    def _room_and_customer(self, api, status):
        customer = create_customer(name="Retail G")
        api.set_customer_status(customer["id"], {"status": status}, SM)
        room = create_tasting_room(name="Room A", seat_capacity=20, buffer_minutes=30)
        return customer, room

    def test_delinquent_host_cannot_book(self, api):
        """PRD §3.9: "the hosting customer must be `ACTIVE`; a `DELINQUENT` or `CLOSED` host
        cannot book, and the attempt is rejected with `ERR_CUSTOMER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/tasting_requires_customer_active
        """
        customer, room = self._room_and_customer(api, "DELINQUENT")
        res = api.create_tasting_event(create_tasting_event_payload(
            room["id"], customer["id"], "2026-07-05T10:00:00Z", "2026-07-05T11:00:00Z", 5), CS)
        validate_error(res, "ERR_CUSTOMER_NOT_ACTIVE")

    def test_closed_host_cannot_book(self, api):
        """PRD §3.9: "the hosting customer must be `ACTIVE`; a `DELINQUENT` or `CLOSED` host
        cannot book, and the attempt is rejected with `ERR_CUSTOMER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/tasting_requires_customer_active
        """
        customer, room = self._room_and_customer(api, "CLOSED")
        res = api.create_tasting_event(create_tasting_event_payload(
            room["id"], customer["id"], "2026-07-05T10:00:00Z", "2026-07-05T11:00:00Z", 5), CS)
        validate_error(res, "ERR_CUSTOMER_NOT_ACTIVE")


# ─── non_linear_state_machine / subscription_pause_resume_cycle ────────────
class TestSubscriptionPauseResumeCycle:
    def test_revisits_paused_after_full_cycle(self, api):
        """PRD §3.8: "The owner may **pause** an `ACTIVE` subscription, moving it
        `ACTIVE → PAUSED`; pausing carries no side effect on the ship date. The owner may
        **resume** a `PAUSED` subscription, moving it `PAUSED → ACTIVE` and advancing
        `next_ship_date` by another `cadence_days`. Pause and resume may alternate any number
        of times."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        sc = setup_active_subscription()
        wc = sc["wc_headers"]
        sub_id = sc["subscription"]["id"]
        api.pause_subscription(sub_id, wc)
        api.resume_subscription(sub_id, wc)
        final = validate_success(api.pause_subscription(sub_id, wc), 200)
        assert final["status"] == "PAUSED"

    def test_resume_returns_to_active_mid_cycle(self, api):
        """PRD §3.8: "The owner may **resume** a `PAUSED` subscription, moving it
        `PAUSED → ACTIVE` and advancing `next_ship_date` by another `cadence_days`."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        sc = setup_active_subscription()
        wc = sc["wc_headers"]
        sub_id = sc["subscription"]["id"]
        api.pause_subscription(sub_id, wc)
        resumed = validate_success(api.resume_subscription(sub_id, wc), 200)
        assert resumed["status"] == "ACTIVE"


# ─── Corner: validations / corner_tasting_seats_exceeded ───────────────────
def test_tasting_seats_exceeded(api):
    """PRD §3.9: "aggregate seating must fit: across the set of `SCHEDULED` events in the same
    room whose `[start_at, end_at)` intervals overlap this one, the sum of their `seats` plus
    this event's `seats` must not exceed the room's `seat_capacity`; an overflow is rejected
    with `ERR_TASTING_SEATS_EXCEEDED`."

    Design: Corner/validations/corner_tasting_seats_exceeded
    """
    sc = setup_scheduled_tasting_event(seats=12, buffer_minutes=30, seat_capacity=20,
                                       start_at="2026-07-07T10:00:00Z",
                                       end_at="2026-07-07T11:00:00Z")
    res = api.create_tasting_event(create_tasting_event_payload(
        sc["room"]["id"], sc["customer"]["id"],
        "2026-07-07T10:30:00Z", "2026-07-07T11:30:00Z", 12), CS)   # 12+12=24 > 20
    validate_error(res, "ERR_TASTING_SEATS_EXCEEDED")


# ─── Corner: state_machines / corner_tasting_cancel_from_cancelled_invalid_state ──
def test_cancel_already_cancelled_tasting_event(api):
    """PRD §3.9: "A `CounterStaff` may **cancel** a `SCHEDULED` event, moving it
    `SCHEDULED → CANCELLED`, which frees the event's seats and buffer so they no longer
    constrain later bookings; cancelling anything not `SCHEDULED` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_tasting_cancel_from_cancelled_invalid_state
    """
    sc = setup_scheduled_tasting_event(seats=4, start_at="2026-07-06T10:00:00Z",
                                       end_at="2026-07-06T11:00:00Z")
    api.cancel_tasting_event(sc["event"]["id"], CS)
    res = api.cancel_tasting_event(sc["event"]["id"], CS)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: state_machines / corner_resume_active_subscription_invalid_state ──
def test_resume_active_subscription_rejected(api):
    """PRD §3.8: "Any of these three actions attempted from an incompatible state is rejected
    with `ERR_SUBSCRIPTION_INVALID_STATE`."

    Design: Corner/state_machines/corner_resume_active_subscription_invalid_state
    """
    sc = setup_active_subscription()
    res = api.resume_subscription(sc["subscription"]["id"], sc["wc_headers"])
    validate_error(res, "ERR_SUBSCRIPTION_INVALID_STATE")


# ─── Corner: state_machines / corner_cancel_terminal_subscription_invalid_state ──
def test_cancel_already_cancelled_subscription(api):
    """PRD §3.8: "The owner may **cancel** from either `ACTIVE` or `PAUSED`, moving the
    subscription to the terminal `CANCELLED` state. Any of these three actions attempted from
    an incompatible state is rejected with `ERR_SUBSCRIPTION_INVALID_STATE`."

    Design: Corner/state_machines/corner_cancel_terminal_subscription_invalid_state
    """
    sc = setup_active_subscription(tier="PREMIUM", monthly_price_cents=9000)
    api.cancel_subscription(sc["subscription"]["id"], sc["wc_headers"])
    res = api.cancel_subscription(sc["subscription"]["id"], sc["wc_headers"])
    validate_error(res, "ERR_SUBSCRIPTION_INVALID_STATE")
