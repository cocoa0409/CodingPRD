"""Agritourism add-on bookings, slot pools, redemption, availability read."""
from test_helpers import (
    TEST_USERS,
    admit_online_session,
    book_addon,
    create_addon_booking_payload,
    create_addon_product,
    set_clock,
    setup_operating_day,
    sign_waiver,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["farm_manager_headers"]
GATE = TEST_USERS["gate_staff_headers"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]


def _addon_world(api):
    """Two CHECKED_IN sessions and a wagon product with slot_capacity 20."""
    world = setup_operating_day()
    wagon = create_addon_product(world["season_id"], kind="WAGON_RIDE",
                                 name="Orchard Wagon", price_cents=900,
                                 slot_capacity=20)
    world["wagon_id"] = wagon["id"]
    session_a = admit_online_session(world)
    world["session_a_id"] = session_a["id"]
    wv_b = sign_waiver(world["season_id"], ["Bob"], signer_name="Bob",
                       signer_email="bob@x.com")
    session_b = admit_online_session(world, waiver_id=wv_b["id"])
    world["session_b_id"] = session_b["id"]
    return world


class TestAddonSlotPool:
    def test_slot_pool_exact_fill_succeeds(self, api):
        """PRD §3.6: "the sum of `qty` over bookings sharing the same
        `addon_product_id`, `booking_date`, and `slot_time` in `BOOKED` or
        `REDEEMED` status, plus the new `qty`, must not exceed the product's
        `slot_capacity` — equality exactly fills the slot and succeeds"
        PRD §3.6: "A new booking is `BOOKED` with `booked_value_cents` pinned
        at creation as the product's `price_cents` multiplied by `qty`."

        Design: Difficulty/resource_temporal_overlap/addon_slot_aggregate_capacity_pool
        """
        world = _addon_world(api)
        first = book_addon(world["session_a_id"], world["wagon_id"],
                           slot_time="11:00", qty=12)
        assert first["booked_value_cents"] == 10800, "12 * 900"
        second = book_addon(world["session_b_id"], world["wagon_id"],
                            slot_time="11:00", qty=8)
        assert second["booked_value_cents"] == 7200, "8 * 900; pool at 20 == 20"

    def test_slot_pool_overflow_and_independent_slot_time(self, api):
        """PRD §3.6: "equality exactly fills the slot and succeeds, and
        overflow is `ERR_ADDON_SLOT_FULL` (422)."

        Design: Difficulty/resource_temporal_overlap/addon_slot_aggregate_capacity_pool
        """
        world = _addon_world(api)
        book_addon(world["session_a_id"], world["wagon_id"],
                   slot_time="11:00", qty=12)
        book_addon(world["session_b_id"], world["wagon_id"],
                   slot_time="11:00", qty=8)

        resp = api.create_addon_booking(
            create_addon_booking_payload(world["session_a_id"],
                                         world["wagon_id"], slot_time="11:00",
                                         qty=1),
            GATE)
        validate_error(resp, "ERR_ADDON_SLOT_FULL", 422)  # 20 + 1 > 20

        other_slot = book_addon(world["session_a_id"], world["wagon_id"],
                                slot_time="12:00", qty=1)
        assert other_slot["status"] == "BOOKED", (
            "slot_time defines an independent pool")


class TestRedemption:
    def test_redeem_on_wrong_date_rejected(self, api):
        """PRD §3.6: "a `BOOKED` booking becomes `REDEEMED` only while its
        session's `visit_status` is `CHECKED_IN` or `FIELD_ACTIVE` and the
        logical clock's date equals the booking's `booking_date`; either
        failure is `ERR_BOOKING_NOT_REDEEMABLE` (409)."

        Design: Corner/state_machines/redeem_on_wrong_date_rejected
        """
        world = setup_operating_day()
        wagon = create_addon_product(world["season_id"])
        session = admit_online_session(world)
        booking = book_addon(session["id"], wagon["id"], slot_time="11:00")

        set_clock("2026-08-05T10:00:00Z")  # the day after the booking
        resp = api.redeem_addon_booking(booking["id"], FIELD_STAFF)
        validate_error(resp, "ERR_BOOKING_NOT_REDEEMABLE", 409)


class TestAvailabilityCalendar:
    def test_availability_calendar_computed_read(self, api):
        """PRD §3.3: "the availability calendar reads every non-`CANCELLED`
        window between `from_date` and `to_date` inclusive — optionally
        narrowed by a `field_id` filter — and returns an object whose `rows`
        array carries one entry per window: `date`, `window_id`, `field_id`,
        `field_name`, `field_status`, `window_status`, `open_time`,
        `close_time`, `picking_capacity_slots`, `booked_slots`, and
        `projected_remaining_oz`."

        Design: Corner/endpoints/availability_calendar_computed_read
        """
        world = setup_operating_day(waiver_names=("Ann", "Bob"))
        admit_online_session(world, party_size=2)

        data = validate_success(api.get_availability_calendar(
            GATE, params={"from_date": "2026-08-04", "to_date": "2026-08-04"}))
        rows = data["rows"]
        assert len(rows) == 1, "the range covers exactly one window"
        row = rows[0]
        assert row["window_id"] == world["window_id"]
        assert row["window_status"] == "OPEN"
        assert row["field_status"] == "OPEN"
        assert row["booked_slots"] == 2, "the party-2 session"
        assert row["projected_remaining_oz"] == 1000, "no harvest lines yet"
