"""Private rooms: zero-buffer half-open overlap against CONFIRMED bookings, the
quote/deposit calculation, out-of-service guard, and optimistic-concurrency versioning."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    create_room, create_hold, current_room_version,
)

MGR = TEST_USERS["manager_headers"]
STAFF = TEST_USERS["staff_headers"]


# ─── Difficulty/resource_temporal_overlap/room_booking_confirmed_overlap_no_buffer ─
def test_back_to_back_room_booking_accepted(api):
    """PRD §2.7: "Two windows that merely touch back-to-back — the existing booking ending
    at the instant the requested one begins — do not conflict and are accepted."

    Design: Difficulty/resource_temporal_overlap/room_booking_confirmed_overlap_no_buffer
    """
    room = create_room(api, name="Dragon Den", capacity=20, hourly_rate_cents=8000)
    pb1 = create_hold(api, room["id"], "2026-07-09T18:00:00Z", "2026-07-09T20:00:00Z",
                      current_room_version(api, room["id"]), headcount=8)
    validate_success(api.confirm_private_booking(pb1["id"], STAFF))
    pb2 = validate_success(api.create_private_booking(
        {"room_id": room["id"], "start_at": "2026-07-09T20:00:00Z",
         "end_at": "2026-07-09T21:00:00Z", "headcount": 8,
         "expected_room_version": current_room_version(api, room["id"])}, STAFF),
        expected_status=201)
    assert pb2["status"] == "HELD", "back-to-back 20:00-21:00 accepted against CONFIRMED 18:00-20:00"


def test_overlapping_room_booking_rejected(api):
    """PRD §2.7: "a requested window conflicts with an existing `CONFIRMED` booking on the
    same room when the requested `start_at` is earlier than the existing `end_at` and the
    requested `end_at` is later than the existing `start_at`. Two windows that merely touch
    back-to-back — the existing booking ending at the instant the requested one begins — do
    not conflict and are accepted. A violation is rejected with `ERR_ROOM_TIME_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_booking_confirmed_overlap_no_buffer
    """
    room = create_room(api, name="Dragon Den 2", capacity=20, hourly_rate_cents=8000)
    pb1 = create_hold(api, room["id"], "2026-07-09T18:00:00Z", "2026-07-09T20:00:00Z",
                      current_room_version(api, room["id"]), headcount=8)
    validate_success(api.confirm_private_booking(pb1["id"], STAFF))
    res = api.create_private_booking(
        {"room_id": room["id"], "start_at": "2026-07-09T19:30:00Z",
         "end_at": "2026-07-09T20:30:00Z", "headcount": 8,
         "expected_room_version": current_room_version(api, room["id"])}, STAFF)
    validate_error(res, "ERR_ROOM_TIME_CONFLICT")


# ─── Corner/calculations/private_booking_quote_and_deposit ─────────────────
def test_private_booking_quote_and_deposit(api):
    """PRD §3.7: "the room hours are the whole minutes of the window divided by 60 and
    rounded up to the next whole hour, and the room charge is those hours multiplied by the
    room's `hourly_rate_cents`. Catering is the `headcount` multiplied by 1500 cents per
    head. The service fee is 18 percent of the sum of the room charge and catering, rounded
    half up. The `quoted_total_cents` is the room charge plus catering plus the service fee.
    The `deposit_cents` is 25 percent of the `quoted_total_cents`, rounded half up."

    Design: Corner/calculations/private_booking_quote_and_deposit
    """
    room = create_room(api, name="Quote Room", capacity=20, hourly_rate_cents=8000)
    pb = create_hold(api, room["id"], "2026-07-09T18:00:00Z", "2026-07-09T20:00:00Z",
                     room["version"], headcount=8)
    # room 2*8000=16000 + catering 8*1500=12000 + service round(28000*0.18)=5040
    assert pb["quoted_total_cents"] == 33040
    assert pb["deposit_cents"] == 8260, "round_half_up(33040*0.25)"


# ─── Corner/validations/hold_out_of_service_room_returns_room_unavailable ──
def test_hold_out_of_service_room_returns_room_unavailable(api):
    """PRD §3.7: "A hold is only accepted when the room is `AVAILABLE`; a hold against an
    `OUT_OF_SERVICE` room is rejected with `ERR_ROOM_UNAVAILABLE`."

    Design: Corner/validations/hold_out_of_service_room_returns_room_unavailable
    """
    room = create_room(api, name="Closed Room", capacity=10, hourly_rate_cents=5000)
    validate_success(api.update_room(room["id"], {"status": "OUT_OF_SERVICE"}, MGR))
    res = api.create_private_booking(
        {"room_id": room["id"], "start_at": "2026-07-09T18:00:00Z",
         "end_at": "2026-07-09T20:00:00Z", "headcount": 4,
         "expected_room_version": current_room_version(api, room["id"])}, STAFF)
    validate_error(res, "ERR_ROOM_UNAVAILABLE")


# ─── Corner/cross_cutting_complexity_layers/private_booking_create_increments_room_version ─
def test_create_hold_increments_room_version(api):
    """PRD §3.7: "creating a new hold moves any prior `HELD` booking on the same room to the
    `SUPERSEDED` state, released without charge, and increments the room's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/private_booking_create_increments_room_version
    """
    room = create_room(api, name="Ver Room", capacity=10, hourly_rate_cents=4000)
    assert room["version"] == 1
    pb = create_hold(api, room["id"], "2026-07-09T18:00:00Z", "2026-07-09T19:00:00Z",
                     room["version"], headcount=4)
    assert pb["status"] == "HELD"
    assert current_room_version(api, room["id"]) == 2, "version incremented from 1 to 2"


# ─── Corner/cross_cutting_complexity_layers/private_booking_stale_room_version_returns_stale ─
def test_create_hold_with_stale_version_rejected(api):
    """PRD §2.6: "When `expected_room_version` does not equal the room's current `version`,
    the hold is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite
    a state it has not observed."

    Design: Corner/cross_cutting_complexity_layers/private_booking_stale_room_version_returns_stale
    """
    room = create_room(api, name="Stale Room", capacity=10, hourly_rate_cents=4000)
    # First hold with version 1 succeeds and bumps the room to version 2.
    create_hold(api, room["id"], "2026-07-09T18:00:00Z", "2026-07-09T19:00:00Z",
                room["version"], headcount=4)
    # Second create still carries the now-stale original version 1.
    res = api.create_private_booking(
        {"room_id": room["id"], "start_at": "2026-07-09T20:00:00Z",
         "end_at": "2026-07-09T21:00:00Z", "headcount": 4,
         "expected_room_version": room["version"]}, STAFF)
    validate_error(res, "ERR_STALE_VERSION")
