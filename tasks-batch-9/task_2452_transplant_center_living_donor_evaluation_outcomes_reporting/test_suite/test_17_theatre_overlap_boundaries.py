"""Two resources on the same timeline with deliberately opposite interval semantics."""
from test_helpers import (
    add_operating_room,
    add_surgeon,
    add_segment,
    book_theatre,
    create_active_recipient,
    create_chain,
    create_donor,
    get_room_listing,
    setup_program_with_staff,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId

DAY = "2026-08-09"


def _room(env, room_code):
    matches = [row for row in get_room_listing(env) if row["room_code"] == room_code]
    assert matches, f"expected room {room_code} in the program's room listing"
    return matches[0]


def _booking_attempt(env, room_id, segment_id, surgeon_id, start_at, end_at):
    return api_client.create_procedure_booking(
        {
            "operating_room_id": room_id,
            "chain_segment_id": segment_id,
            "surgeon_staff_id": surgeon_id,
            "booking_role": "RECIPIENT_IMPLANT",
            "start_at": start_at,
            "end_at": end_at,
        },
        env["coordinator_headers"],
    )


def _bookings_in_room(env, room_id):
    rows, _meta = validate_paginated(
        api_client.list_procedure_bookings(
            env["coordinator_headers"], params={"operating_room_id": room_id}
        )
    )
    return rows


def _setup_theatre_with_a_morning_recovery():
    """Two buffered rooms, two surgeons, and one 06:00-10:00 recovery in OR-1."""
    env = setup_program_with_staff()
    env["surgeon_two"] = add_surgeon(env)
    env["room_one"] = add_operating_room(env, "OR-1", turnover_buffer_minutes=45)
    env["room_two"] = add_operating_room(env, "OR-2", turnover_buffer_minutes=45)
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(env, mrn="D-001", abo_blood_type="O", age_years=41)
    chain = create_chain(env, "PAIRED_LOOP")
    env["chain"] = chain
    env["segment_one"] = add_segment(
        env, chain["id"], 1, donor["id"], recipient["id"]
    )
    env["recovery"] = book_theatre(
        env,
        env["room_one"]["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        f"{DAY}T06:00:00Z",
        f"{DAY}T10:00:00Z",
    )
    return env


def test_a_room_booking_inside_the_turnover_buffer_is_refused():
    """PRD §3.6: "**Room occupancy** is evaluated against that room's `ACTIVE`
    bookings only, and each side of the comparison is padded by the room's
    `turnover_buffer_minutes`: the new booking is rejected when its `start_at` is
    earlier than an existing booking's `end_at` plus the buffer *and* its `end_at`
    plus the buffer is later than that existing booking's `start_at`."
    PRD §3.6: "The booking starts in `ACTIVE`, its `duration_minutes` is the whole
    minutes between `start_at` and `end_at`, its `cancel_reason_code` is null, and the
    room's `reserved_minutes_total` is incremented by that duration."

    Design: Difficulty/resource_temporal_overlap/operating_room_buffered_half_open_turnover_boundary
    """
    env = _setup_theatre_with_a_morning_recovery()
    assert env["recovery"]["status"] == "ACTIVE"
    assert env["recovery"]["duration_minutes"] == 240
    assert env["recovery"]["cancel_reason_code"] is None
    assert _room(env, "OR-1")["reserved_minutes_total"] == 240

    response = _booking_attempt(
        env,
        env["room_one"]["id"],
        env["segment_one"]["id"],
        env["surgeon_two"]["id"],
        f"{DAY}T10:30:00Z",
        f"{DAY}T12:00:00Z",
    )
    validate_error(response, ApiErrorId.ERR_OR_SLOT_CONFLICT.value)

    assert len(_bookings_in_room(env, env["room_one"]["id"])) == 1, (
        "the refused attempt creates no ProcedureBooking row"
    )
    assert _room(env, "OR-1")["reserved_minutes_total"] == 240, (
        "10:30 is earlier than 10:00 plus the 45-minute buffer, so nothing is reserved"
    )
    assert _room(env, "OR-2")["reserved_minutes_total"] == 0, (
        "the conflict was room-scoped, never program-scoped"
    )


def test_a_room_booking_exactly_one_buffer_after_the_previous_end_is_accepted():
    """PRD §3.6: "The windows are half-open, so a booking that starts exactly the
    buffer's worth of minutes after another ends is accepted."
    PRD §3.6: "The booking starts in `ACTIVE`, its `duration_minutes` is the whole
    minutes between `start_at` and `end_at`, its `cancel_reason_code` is null, and the
    room's `reserved_minutes_total` is incremented by that duration."

    Design: Difficulty/resource_temporal_overlap/operating_room_buffered_half_open_turnover_boundary
    """
    env = _setup_theatre_with_a_morning_recovery()
    validate_error(
        _booking_attempt(
            env,
            env["room_one"]["id"],
            env["segment_one"]["id"],
            env["surgeon_two"]["id"],
            f"{DAY}T10:30:00Z",
            f"{DAY}T12:00:00Z",
        ),
        ApiErrorId.ERR_OR_SLOT_CONFLICT.value,
    )

    accepted = validate_success(
        _booking_attempt(
            env,
            env["room_one"]["id"],
            env["segment_one"]["id"],
            env["surgeon_two"]["id"],
            f"{DAY}T10:45:00Z",
            f"{DAY}T12:00:00Z",
        ),
        expected_status=201,
    )

    assert accepted["status"] == "ACTIVE", "10:45 is exactly end_at plus the buffer"
    assert accepted["duration_minutes"] == 75
    assert _room(env, "OR-1")["reserved_minutes_total"] == 315, (
        "240 plus 75, incremented exactly once"
    )
    assert _room(env, "OR-2")["reserved_minutes_total"] == 0

    untouched = validate_success(
        api_client.get_procedure_booking(
            env["recovery"]["id"], env["coordinator_headers"]
        )
    )
    assert untouched["status"] == "ACTIVE"
    assert untouched["duration_minutes"] == 240


def test_a_surgeon_booking_touching_the_previous_end_collides_across_rooms():
    """PRD §3.6: "**Surgeon availability** is evaluated against that surgeon's
    `ACTIVE` bookings in any room, with no buffer at all and with closed intervals:
    the new booking is rejected when its `start_at` is at or before an existing
    booking's `end_at` *and* its `end_at` is at or after that existing booking's
    `start_at`."
    PRD §3.6: "Touching endpoints therefore collide for a surgeon where they would
    not for a room."

    Design: Difficulty/resource_temporal_overlap/surgeon_closed_interval_touching_endpoint_collision
    """
    env = _setup_theatre_with_a_morning_recovery()
    assert _room(env, "OR-2")["reserved_minutes_total"] == 0, (
        "OR-2 has no bookings at all, so the room rule cannot fire for it"
    )

    response = _booking_attempt(
        env,
        env["room_two"]["id"],
        env["segment_one"]["id"],
        env["surgeon"]["id"],
        f"{DAY}T10:00:00Z",
        f"{DAY}T12:00:00Z",
    )
    validate_error(response, ApiErrorId.ERR_SURGEON_DOUBLE_BOOKED.value)

    assert _bookings_in_room(env, env["room_two"]["id"]) == []
    assert _room(env, "OR-2")["reserved_minutes_total"] == 0
    assert _room(env, "OR-1")["reserved_minutes_total"] == 240


def test_a_surgeon_booking_one_minute_after_the_previous_end_is_accepted():
    """PRD §3.6: "**Surgeon availability** is evaluated against that surgeon's
    `ACTIVE` bookings in any room, with no buffer at all and with closed intervals:
    the new booking is rejected when its `start_at` is at or before an existing
    booking's `end_at` *and* its `end_at` is at or after that existing booking's
    `start_at`."
    PRD §3.6: "The booking starts in `ACTIVE`, its `duration_minutes` is the whole
    minutes between `start_at` and `end_at`, its `cancel_reason_code` is null, and the
    room's `reserved_minutes_total` is incremented by that duration."

    Design: Difficulty/resource_temporal_overlap/surgeon_closed_interval_touching_endpoint_collision
    """
    env = _setup_theatre_with_a_morning_recovery()
    validate_error(
        _booking_attempt(
            env,
            env["room_two"]["id"],
            env["segment_one"]["id"],
            env["surgeon"]["id"],
            f"{DAY}T10:00:00Z",
            f"{DAY}T12:00:00Z",
        ),
        ApiErrorId.ERR_SURGEON_DOUBLE_BOOKED.value,
    )

    accepted = validate_success(
        _booking_attempt(
            env,
            env["room_two"]["id"],
            env["segment_one"]["id"],
            env["surgeon"]["id"],
            f"{DAY}T10:01:00Z",
            f"{DAY}T12:00:00Z",
        ),
        expected_status=201,
    )

    assert accepted["status"] == "ACTIVE"
    assert accepted["duration_minutes"] == 119
    assert _room(env, "OR-2")["reserved_minutes_total"] == 119
    assert _room(env, "OR-1")["reserved_minutes_total"] == 240, "unchanged"

    held_by_surgeon, _meta = validate_paginated(
        api_client.list_procedure_bookings(
            env["coordinator_headers"],
            params={"surgeon_staff_id": env["surgeon"]["id"], "status": "ACTIVE"},
        )
    )
    assert len(held_by_surgeon) == 2, (
        "the surgeon legally holds two active bookings in two rooms once they no "
        "longer touch"
    )
