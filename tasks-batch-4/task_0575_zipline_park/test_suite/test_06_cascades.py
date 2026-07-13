"""Transitive cascades: weather close and group cancel propagate three levels (PRD §3.6, §3.7, §3.8)."""
from test_helpers import (
    TEST_USERS,
    setup_open_slot, setup_course_slot_guide, create_participant, create_booking,
    create_group, create_gear_item, checkout_gear, get_booking, get_gear_checkout,
    get_gear_item, get_time_slot,
)

OP = TEST_USERS["operator_headers"]


def _open_slot_booking_with_gear(api):
    """OPEN slot + CONFIRMED booking + one HARNESS checked out to it (item CHECKED_OUT)."""
    course, ts, guide = setup_open_slot(api)
    p = create_participant(api)
    booking = create_booking(api, ts["id"], p["id"])
    gear = create_gear_item(api, gear_type="HARNESS", size="M")
    checkout = checkout_gear(api, gear["id"], booking["id"])
    return ts, booking, gear, checkout


def test_weather_close_cascades_booking_gear_item(api):
    """PRD §3.6: "every booking on the slot in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` is
    driven to `RAINCHECKED`".
    PRD §3.6: "each of those bookings' gear checkouts that are still outstanding are
    returned (their `returned_at` set to the current clock and status `RETURNED`). At the
    third level, each gear item whose last outstanding checkout was just returned reverts
    to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/weather_close_cascade_slot_booking_gearcheckout_gearitem_depth3
    """
    ts, booking, gear, checkout = _open_slot_booking_with_gear(api)
    api.close_time_slot(ts["id"], OP, reason="storm")
    assert get_booking(api, booking["id"])["status"] == "RAINCHECKED"
    assert get_gear_checkout(api, checkout["id"])["status"] == "RETURNED"
    assert get_gear_item(api, gear["id"])["status"] == "AVAILABLE"


def test_weather_close_credits_full_and_releases_seat(api):
    """PRD §3.6: "each such booking is stamped with a full weather credit: its
    `raincheck_credit_cents` is set equal to its `price_cents`, unconditionally".
    PRD §3.6: "As the bookings leave their active states, their seats are released —
    `booked_count` and `remaining_capacity` recompute".

    Design: Difficulty/transitive_cascade/weather_close_cascade_slot_booking_gearcheckout_gearitem_depth3
    """
    ts, booking, gear, checkout = _open_slot_booking_with_gear(api)
    api.close_time_slot(ts["id"], OP, reason="storm")
    assert get_booking(api, booking["id"])["raincheck_credit_cents"] == 5000
    assert get_time_slot(api, ts["id"])["remaining_capacity"] == 4


def _group_two_members_with_gear(api):
    """Group G2 on a slot with two CONFIRMED member bookings; a HARNESS on member b_a."""
    course, ts, guide = setup_course_slot_guide(api)
    g2 = create_group(api, ts["id"], expected_size=2, name="Team2")
    p_a = create_participant(api, full_name="P A")
    p_b = create_participant(api, full_name="P B")
    b_a = create_booking(api, ts["id"], p_a["id"], group_id=g2["id"])
    b_b = create_booking(api, ts["id"], p_b["id"], group_id=g2["id"])
    gear = create_gear_item(api, gear_type="HARNESS", size="M")
    checkout = checkout_gear(api, gear["id"], b_a["id"])
    return g2, b_a, b_b, gear, checkout


def test_group_cancel_cancels_all_members(api):
    """PRD §3.7: "Every member booking in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` is
    cancelled; each cancelled booking's outstanding gear checkouts are returned; and each
    freed gear item reverts to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/group_cancel_cascade_booking_gearcheckout_gearitem
    """
    g2, b_a, b_b, gear, checkout = _group_two_members_with_gear(api)
    cancelled = api.cancel_group(g2["id"], OP)
    assert cancelled.json()["data"]["status"] == "CANCELLED"
    assert get_booking(api, b_a["id"])["status"] == "CANCELLED"
    assert get_booking(api, b_b["id"])["status"] == "CANCELLED"


def test_group_cancel_returns_gear_and_frees_item(api):
    """PRD §3.7: "each cancelled booking's outstanding gear checkouts are returned; and
    each freed gear item reverts to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/group_cancel_cascade_booking_gearcheckout_gearitem
    """
    g2, b_a, b_b, gear, checkout = _group_two_members_with_gear(api)
    api.cancel_group(g2["id"], OP)
    assert get_gear_checkout(api, checkout["id"])["status"] == "RETURNED"
    assert get_gear_item(api, gear["id"])["status"] == "AVAILABLE"
