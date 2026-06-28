"""Transition preconditions and timing gates: tank retirement guard, orientation completion
timing, couples-tank kind mismatch, and the reschedule cutoff."""
from test_helpers import (
    validate_success, validate_error,
    setup_member_and_tank, setup_scheduled_orientation,
    setup_confirmed_cash_booking_for_reschedule_cutoff,
    create_booking, create_booking_payload,
    api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Retire guard (retire_tank_with_active_booking_rejected) ──────────────
def test_retire_tank_with_reserved_booking_rejected(api):
    """PRD §3.4: "retirement is refused while any booking on that tank is still live — that is,
    in `RESERVED`, `CONFIRMED`, `RESCHEDULED`, or `CHECKED_IN` — and such an attempt is
    rejected with `ERR_TANK_HAS_BOOKINGS`."

    Design: Corner/state_machines/retire_tank_with_active_booking_rejected
    """
    ctx = setup_member_and_tank()
    member, tank = ctx["member"], ctx["tank"]
    create_booking(member["id"], tank["id"], 60, "2026-02-01T10:00:00Z", "CASH")
    res = api.tank_retire(tank["id"], ADMIN)
    validate_error(res, "ERR_TANK_HAS_BOOKINGS", expected_status=409)
    after = validate_success(api.get_tank(tank["id"], ADMIN), 200)
    assert after["operational_status"] == "IN_SERVICE"


# ─── Orientation timing (orientation_complete_before_start_returns_timing) ──
def test_complete_orientation_before_start_rejected(api):
    """PRD §3.2: "Completing an orientation moves it from `SCHEDULED` to `COMPLETED` and may
    only happen once the current time has reached the orientation's `start_utc` (the current
    time is at or after `start_utc`); an attempt before then is an illegal transition."

    Design: Corner/state_machines/orientation_complete_before_start_returns_timing
    """
    # Clock at 08:00, orientation start 09:00 (before start).
    ctx = setup_scheduled_orientation("2026-03-01T09:00:00Z", base_clock="2026-03-01T08:00:00Z")
    res = api.complete_orientation(ctx["orientation"]["id"], FRONTDESK)
    # PRD §3.2: "an attempt before then is an illegal transition" -> ERR_INVALID_STATE (§2.7).
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_orientation(ctx["orientation"]["id"], FRONTDESK), 200)
    assert after["status"] == "SCHEDULED"


# ─── Kind mismatch (couples_booking_on_single_tank_returns_kind_mismatch) ──
def test_couples_booking_on_single_tank_rejected(api):
    """PRD §3.5: "A couples booking (`is_couples` true) must be placed on a `DUAL` tank; a
    `GIFT_CARD` payment must supply a `gift_card_id`; and a `CREDIT` payment must supply a
    `membership_id`. Any of these combinations being violated is rejected with
    `ERR_TANK_KIND_MISMATCH`."

    Design: Corner/validations/couples_booking_on_single_tank_returns_kind_mismatch
    """
    ctx = setup_member_and_tank()  # SINGLE tank
    member, tank = ctx["member"], ctx["tank"]
    res = api.create_booking(create_booking_payload(
        member["id"], tank["id"], 60, "2026-02-01T10:00:00Z", "CASH", is_couples=True),
        FRONTDESK)
    validate_error(res, "ERR_TANK_KIND_MISMATCH", expected_status=422)


# ─── Reschedule cutoff (reschedule_after_cutoff_returns_timing) ───────────
def test_reschedule_inside_cutoff_rejected(api):
    """PRD §3.6: "Rescheduling is allowed only while there is enough lead time: the current
    time must be at or before the booking's `start_utc` minus the reschedule cutoff of twelve
    hours. Past that cutoff the reschedule is refused with `ERR_TIMING_NOT_ALLOWED`."

    Design: Corner/validations/reschedule_after_cutoff_returns_timing
    """
    # Booking start 2026-05-10T10:00Z; clock 10h before (inside the 12h cutoff).
    ctx = setup_confirmed_cash_booking_for_reschedule_cutoff()
    bk = ctx["booking"]
    res = api.reschedule_booking(bk["id"], {"new_start_utc": "2026-05-12T10:00:00Z"}, FRONTDESK)
    validate_error(res, "ERR_TIMING_NOT_ALLOWED", expected_status=409)
    after = validate_success(api.get_booking(bk["id"], FRONTDESK), 200)
    assert after["status"] == "CONFIRMED"
