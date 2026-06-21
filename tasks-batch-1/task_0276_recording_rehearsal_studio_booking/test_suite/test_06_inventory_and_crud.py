"""CRUD, defaults, computed fields, listing, and not-found corners (Corner: entities, endpoints).

Translates the breadth-coverage entity and endpoint corner instances.
"""
import pytest

from test_helpers import (
    setup_studio,
    setup_room,
    setup_client,
    setup_gear_item,
    setup_studio_room_client,
    create_booking,
    pay_deposit,
    assign_engineer,
    setup_engineer,
    confirm,
    set_clock,
    check_in,
    check_out,
    api_client,
    TEST_USERS,
    make_client_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_room,
    create_room_payload,
    create_booking_payload,
    create_payment_payload,
)

SM = TEST_USERS["studio_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Corner: entities ─────────────────────────────────
def test_create_room_returns_201_with_system_fields():
    """PRD §2.4: "`id`: a unique, server-minted identifier formatted as a UUID."
    PRD §3.1: "Every room also carries a computed `status` that is `OPEN` while the room is freely
    bookable and `LOCKED` while a lockout contract holds it; rooms start `OPEN`."

    Design: Corner/entities/create_room_returns_201_with_system_fields
    """
    studio = setup_studio()
    res = api_client.create_room(create_room_payload(studio["id"]), SM)
    room = validate_success(res, 201)
    assert_room(room)
    assert room["version"] == 1, room["version"]
    assert room["status"] == "OPEN", room["status"]
    assert room["block_hours"] == 8, room["block_hours"]
    assert room["turnaround_minutes"] == 30, room["turnaround_minutes"]


def test_get_booking_not_found_returns_404():
    """PRD §2.5: "the first identifier that does not resolve to an existing resource yields
    ERR_NOT_FOUND."

    Design: Corner/entities/get_booking_not_found_returns_404
    """
    setup_studio()
    res = api_client.get_booking("00000000-0000-4000-8000-000000000000", SM)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_booking_missing_required_field_returns_invalid_request():
    """PRD §2.12: "a payload that omits a required body field, carries a value of the wrong type,
    supplies an unrecognized enum value, or sends a negative amount where a positive magnitude is
    required is rejected outright with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_booking_missing_required_field_returns_invalid_request
    """
    studio, room, client = setup_studio_room_client(clock=None)
    payload = create_booking_payload(studio["id"], room["id"], client["id"])
    del payload["end_at"]
    res = api_client.create_booking(payload, make_client_headers(client["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_studio_applies_defaults_when_optional_omitted():
    """PRD §3.1: "deposit_pct (the fraction of a booking's room charge demanded as a deposit at
    confirmation, defaulting to 0.30 and constrained to be greater than 0 and at most 1),
    overtime_multiplier (the surcharge factor applied to the room rate for overtime minutes,
    defaulting to 1.5 and required to be at least 1), overtime_grace_minutes (minutes a session
    may run past its scheduled end before overtime billing begins, defaulting to 10 and required
    to be zero or greater), cancellation_tier_hours (the hours-before-start cutoff separating the
    full-refund tier from the partial-refund tier, defaulting to 48 and required to be zero or
    greater), and late_cancel_fee_pct (the fraction of the room charge the studio retains as a fee
    when a client cancels inside the partial tier, defaulting to 0.50 and constrained to be
    between 0 and 1 inclusive)."

    Design: Corner/entities/create_studio_applies_defaults_when_optional_omitted
    """
    res = api_client.create_studio({"name": "Echo Labs"}, SM)
    studio = validate_success(res, 201)
    assert studio["deposit_pct"] == 0.30, studio["deposit_pct"]
    assert studio["overtime_multiplier"] == 1.5, studio["overtime_multiplier"]
    assert studio["overtime_grace_minutes"] == 10, studio["overtime_grace_minutes"]
    assert studio["cancellation_tier_hours"] == 48, studio["cancellation_tier_hours"]
    assert studio["late_cancel_fee_pct"] == 0.50, studio["late_cancel_fee_pct"]


def test_booking_computed_base_charge_ignores_client_input():
    """PRD §3.2: "For a BLOCK or LOCKOUT booking, divide the duration in hours by the room's
    block_hours, round that quotient up to the next whole block (a session that straddles a block
    boundary buys another entire block, so a nine-hour booking against an eight-hour block costs
    two blocks), and multiply the whole-block count by the room's block_rate_cents."
    PRD §3.2: "The deposit, deposit_due_cents, is the room charge scaled by the studio's deposit
    fraction: multiply base_charge_cents by the studio's deposit_pct and round the product half up
    to a whole cent."

    Design: Corner/entities/booking_computed_base_charge_ignores_client_input
    """
    studio, room, client = setup_studio_room_client(room_overrides={
        "hourly_rate_cents": 6000, "block_rate_cents": 40000, "block_hours": 8})
    booking = create_booking(studio, room, client, booking_kind="BLOCK",
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T18:00:00Z")
    # 9h / 8 block_hours -> ceil 2 blocks * 40000 == 80000
    assert booking["base_charge_cents"] == 80000, booking["base_charge_cents"]
    # deposit default 0.30 -> round_half_up(80000 * 0.30) == 24000
    assert booking["deposit_due_cents"] == 24000, booking["deposit_due_cents"]


def test_create_booking_invalid_enum_kind_returns_invalid_request():
    """PRD §2.12: "a payload that omits a required body field, carries a value of the wrong type,
    supplies an unrecognized enum value, or sends a negative amount where a positive magnitude is
    required is rejected outright with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_booking_invalid_enum_kind_returns_invalid_request
    """
    studio, room, client = setup_studio_room_client(clock=None)
    payload = create_booking_payload(studio["id"], room["id"], client["id"], booking_kind="MONTHLY")
    res = api_client.create_booking(payload, make_client_headers(client["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_booking_invalid_time_range_returns_422():
    """PRD §3.2: "The end_at must be strictly later than start_at; a window where the end does not
    strictly follow the start is rejected with ERR_INVALID_TIME_RANGE."

    Design: Corner/entities/create_booking_invalid_time_range_returns_422
    """
    studio, room, client = setup_studio_room_client(clock=None)
    payload = create_booking_payload(studio["id"], room["id"], client["id"],
                                     start_at="2026-07-10T12:30:00Z", end_at="2026-07-10T09:00:00Z")
    res = api_client.create_booking(payload, make_client_headers(client["id"]))
    validate_error(res, "ERR_INVALID_TIME_RANGE", expected_status=422)


def test_list_bookings_pagination_envelope():
    """PRD §2.3: "Every list-based response includes the following fields in the `meta` object of
    the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_bookings_pagination_envelope
    """
    studio, room, client = setup_studio_room_client()
    create_booking(studio, room, client,
                   start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    create_booking(studio, room, client,
                   start_at="2026-07-11T09:00:00Z", end_at="2026-07-11T12:30:00Z")
    res = api_client.list_bookings(SM, params={"client_id": client["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert len(data) == 1, len(data)


def test_create_room_with_nonexistent_studio_returns_404():
    """PRD §2.5: "any foreign keys carried in the request body are validated in turn; a body that
    references a non-existent studio, room, engineer, gear item, client, booking, or contract is
    likewise rejected with ERR_NOT_FOUND."

    Design: Corner/entities/create_room_with_nonexistent_studio_returns_404
    """
    payload = create_room_payload("00000000-0000-4000-8000-000000000000")
    res = api_client.create_room(payload, SM)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_overtime_record_immutable_no_version_field():
    """PRD §2.4: "An OvertimeRecord and the Clock carry only id and created_at; they do not
    expose updated_at or version, because an overtime record is written once at check-out and
    never mutated".

    Design: Corner/entities/overtime_record_immutable_no_version_field
    """
    studio, room, client = setup_studio_room_client(
        studio_overrides={"deposit_pct": 0.60, "overtime_grace_minutes": 10,
                          "overtime_multiplier": 1.5},
        room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
    )
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    pay_deposit(booking, client, 14400)
    confirm(booking)
    set_clock("2026-07-10T09:05:00Z")
    check_in(booking)
    check_out(booking, "2026-07-10T12:55:00Z")  # 15 billable overtime min
    data, _ = validate_paginated(api_client.list_booking_overtime_records(booking["id"], SM))
    assert len(data) == 1, data
    rec = data[0]
    assert rec["overage_minutes"] == 15, rec["overage_minutes"]
    assert "version" not in rec, "OvertimeRecord must not expose a version field"


# ─── Corner: endpoints ────────────────────────────────
def test_list_payments_ledger_for_booking():
    """PRD §3.10: "Payments can be listed and filtered by client_id and booking_id, supporting
    reverse lookup from a client or a booking to the payments that reference it."

    Design: Corner/endpoints/list_payments_ledger_for_booking
    """
    studio, room, client = setup_studio_room_client(studio_overrides={"deposit_pct": 0.60})
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    pay_deposit(booking, client, 14400)
    data, _ = validate_paginated(
        api_client.list_booking_payments(booking["id"], make_client_headers(client["id"])))
    deposits = [p for p in data if p["kind"] == "DEPOSIT" and p["amount_cents"] == 14400]
    assert len(deposits) == 1, data


def test_delete_engineer_assignment_releases_it():
    """PRD §3.5: "A StudioManager may release an assignment, moving it from ASSIGNED to RELEASED,
    but only while the parent booking has not advanced into IN_SESSION or COMPLETED".

    Design: Corner/endpoints/delete_engineer_assignment_releases_it
    """
    studio, room, client = setup_studio_room_client()
    engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF", hourly_rate_cents=8000)
    booking = create_booking(studio, room, client,
                             start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
    assign = assign_engineer(booking, engineer)
    res = api_client.release_engineer_assignment(booking["id"], assign["id"], SM)
    released = validate_success(res, 200)
    assert released["status"] == "RELEASED", released["status"]
