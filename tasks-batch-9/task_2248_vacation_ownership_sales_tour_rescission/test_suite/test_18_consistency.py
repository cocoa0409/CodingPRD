"""Declared consistency: cascades land inside the request that triggered them."""

from test_helpers import (
    TEST_USERS,
    assert_instant_equals,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]


def test_a_check_in_returns_its_own_cascade_without_a_second_read():
    """The response body already carries the rotation winner and the copied gift value.

    The PRD states: "Cascades are always applied immediately and synchronously within
    the triggering request; there is no deferred reconciliation anywhere in this
    system."

    The PRD states: "On success the booking moves `SCHEDULED → CHECKED_IN`,
    `assigned_rep_id` is set to the winner, `checked_in_at` is stamped from the logical
    clock, and the winner moves `ACTIVE → ON_TOUR` with `last_assigned_at` stamped."

    The PRD states: "When `issue_incentive_gift` is true, `gift_issued` is set to true,
    `gift_value_cents` is copied from the channel's `incentive_gift_value_cents` as of
    that instant, and the channel's `gift_liability_cents` is recomputed."

    The PRD states: "The gallery's `available_rep_count` does not change, because an
    `ON_TOUR` representative still counts as available inventory."

    The PRD states: "A gallery's `booked_slot_count` is recomputed as the number of
    bookings at that gallery whose `status` is `SCHEDULED`, `RESCHEDULE_PENDING`,
    `CHECKED_IN` or `TOURED`; bookings in `NO_SHOW` and `CANCELLED` are excluded."

    The PRD states: "A successful booking increments the channel's `booked_count` by
    one — a lifetime counter that is never decremented, not even when the booking is
    later cancelled — and recomputes the gallery's `booked_slot_count`."

    Design: Corner/consistency_model/derived_and_cascaded_fields_are_visible_in_the_same_response
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=CHECK_IN_UTC
    )

    fx.pin_clock(CHECK_IN_UTC)
    checked_in = validate_success(
        api.check_in_tour_booking(booking["id"], fac.check_in_payload(True), GALLERY)
    )
    assert checked_in["status"] == "CHECKED_IN"
    assert checked_in["assigned_rep_id"] == representative["id"]
    assert checked_in["gift_issued"] is True
    assert checked_in["gift_value_cents"] == 12500
    assert checked_in["checked_in_at"] == "2026-08-14T07:00:00.000Z"

    bound = fx.read_representative(representative["id"])
    assert bound["status"] == "ON_TOUR"
    assert_instant_equals(
        bound["last_assigned_at"], CHECK_IN_UTC, "last_assigned_at"
    )

    posture = fx.read_gallery(gallery["id"])
    assert posture["booked_slot_count"] == 1
    assert posture["available_rep_count"] == 1

    summary = validate_success(
        api.get_channel_no_show_summary(channel["id"], MARKETING)
    )
    assert summary["gift_liability_cents"] == 12500
    assert summary["booked_count"] == 1
