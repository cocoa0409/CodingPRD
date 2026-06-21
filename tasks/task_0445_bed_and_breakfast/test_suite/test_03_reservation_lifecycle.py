"""Reservation lifecycle: the parallel reservation_status / payment_status axes,
the checkout -> turnover-task cascade, no-show forfeiture, terminal lockdown, and
the housekeeping and gift-certificate branching machines.

Covers queue-A non_linear_state_machine + transitive_cascade (checkout) and
queue-B state_machines corners.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_housekeeping_task,
    create_inn_payload,
    create_room_payload,
    create_guest_payload,
    create_booking_payload,
    create_gift_certificate_payload,
    create_breakfast_plan_payload,
    TEST_USERS,
    make_guest_headers,
    set_clock,
    setup_confirmed_booking,
    setup_checked_out_booking,
    setup_inn_room_guest,
    create_booking,
    cover_deposit_via_gift,
    confirm_booking,
    get_turnover_task,
)
from test_helpers import api_client

INNKEEPER = TEST_USERS["innkeeper_headers"]
HOUSEKEEPER = TEST_USERS["housekeeper_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ─── non_linear_state_machine: parallel axes ────────────────────────────────
def test_confirm_drives_payment_axis_to_deposit_held(api):
    """PRD §3.4: "A successful confirm, which also carries `expected_room_version`
    and is rejected with `ERR_STALE_ROOM_VERSION` if that value no longer matches
    the room's `version` (§2.7), drives the money axis from `UNPAID` to
    `DEPOSIT_HELD` and increments the room's `version` by 1, committing the
    interval."

    Design: Difficulty/non_linear_state_machine/booking_parallel_reservation_and_payment_axes
    """
    _inn, _room, _guest, confirmed, _gift = setup_confirmed_booking(
        inn_overrides={"name": "Aspen Inn", "lodging_tax_rate_bps": 1000},
        room_overrides={"name": "Iris", "base_rate_cents": 10000},
        checkin_date="2026-06-10", checkout_date="2026-06-12",
        clock="2026-06-01T00:00:00Z",
    )
    assert confirmed["reservation_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "DEPOSIT_HELD"


def test_checkout_settles_payment_axis(api):
    """PRD §3.4: "Checking out advances a `CHECKED_IN` booking to `CHECKED_OUT`.
    This single operation settles and cleans: the money axis moves from
    `DEPOSIT_HELD` to `SETTLED` (the balance is considered collected), a new
    housekeeping task is created in `PENDING` for the room with its `ready_after`
    set to the checkout instant plus the inn's `turnover_minutes`, and the room's
    `version` is incremented by 1."

    Design: Difficulty/non_linear_state_machine/booking_parallel_reservation_and_payment_axes
    """
    _inn, _room, _guest, checked_out = setup_checked_out_booking(
        inn_overrides={"name": "Aspen Inn", "lodging_tax_rate_bps": 1000},
        room_overrides={"name": "Iris", "base_rate_cents": 10000},
    )
    assert checked_out["reservation_status"] == "CHECKED_OUT"
    assert checked_out["payment_status"] == "SETTLED"


# ─── non_linear_state_machine: gift deplete-then-restore cycle ───────────────
def test_gift_certificate_depletes_on_full_redemption(api):
    """PRD §3.3: "A valid redemption appends a positive `REDEMPTION` ledger entry
    that records the drawing certificate in its `gift_certificate_id`, debits the
    certificate's `remaining_cents` by the redeemed amount, increments the
    certificate's `version`, recomputes `deposit_paid_cents`, and — if the debit
    drives `remaining_cents` to exactly 0 — moves the certificate to `DEPLETED`."

    Design: Difficulty/non_linear_state_machine/gift_certificate_deplete_then_restore_cycle
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Willow Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Lily", "base_rate_cents": 10000},
    )
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-03-20", "2026-03-22")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 10000), FINANCE))
    get_success_data(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 10000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER))
    after = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert after["status"] == "DEPLETED"
    assert after["remaining_cents"] == 0


def test_gift_certificate_restores_to_active_on_cancel(api):
    """PRD §3.5: "That gift remainder is added back to the certificate's
    `remaining_cents`, and if the certificate had been sitting in `DEPLETED`, the
    restoration of a positive balance returns it to `ACTIVE` — provided its
    `expires_on` is still in the future relative to the logical clock."

    Design: Difficulty/non_linear_state_machine/gift_certificate_deplete_then_restore_cycle
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Willow Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Lily", "base_rate_cents": 10000},
    )
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-03-20", "2026-03-22")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 10000), FINANCE))
    get_success_data(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 10000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER))
    confirm_booking(inn["id"], room["id"], bk["id"])
    # Cancel 14+ days before checkin -> full refund restores gift to 10000 -> ACTIVE.
    get_success_data(api.cancel_booking(inn["id"], bk["id"], INNKEEPER))
    final = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert final["status"] == "ACTIVE"
    assert final["remaining_cents"] == 10000


# ─── transitive_cascade: checkout spawns turnover + bumps room ───────────────
def test_checkout_spawns_pending_turnover_task(api):
    """PRD §3.4: "a new housekeeping task is created in `PENDING` for the room
    with its `ready_after` set to the checkout instant plus the inn's
    `turnover_minutes`, and the room's `version` is incremented by 1."
    PRD §3.7: "A task is born `PENDING`, copies the originating `booking_id` and
    the `room_id` from the booking, and carries a `ready_after` instant equal to
    the checkout instant plus the inn's `turnover_minutes` buffer — the earliest
    moment the room may receive a new arrival."

    Design: Difficulty/transitive_cascade/checkout_spawns_turnover_and_bumps_room_depth2
    """
    inn, room, _guest, checked_out = setup_checked_out_booking(
        inn_overrides={"name": "Cove Inn", "lodging_tax_rate_bps": 0, "turnover_minutes": 180},
        room_overrides={"name": "Marsh", "base_rate_cents": 10000},
        checkin_date="2026-07-10", checkout_date="2026-07-12",
        open_clock="2026-07-01T00:00:00Z",
        checkin_clock="2026-07-10T16:00:00Z",
        checkout_clock="2026-07-12T11:00:00Z",
    )
    task = get_turnover_task(inn["id"], checked_out["id"])
    assert task is not None, "checkout must spawn exactly one turnover task"
    assert task["status"] == "PENDING"
    assert task["room_id"] == room["id"]
    assert_housekeeping_task(task)


def test_checkout_increments_room_version(api):
    """PRD §3.4: "a new housekeeping task is created in `PENDING` for the room
    with its `ready_after` set to the checkout instant plus the inn's
    `turnover_minutes`, and the room's `version` is incremented by 1."

    Design: Difficulty/transitive_cascade/checkout_spawns_turnover_and_bumps_room_depth2
    """
    # Build to CHECKED_IN, observe room version, then check out and re-read.
    set_clock("2026-07-01T00:00:00Z")
    inn, room, guest, confirmed, _gift = setup_confirmed_booking(
        inn_overrides={"name": "Cove Inn", "lodging_tax_rate_bps": 0, "turnover_minutes": 180},
        room_overrides={"name": "Marsh", "base_rate_cents": 10000},
        checkin_date="2026-07-10", checkout_date="2026-07-12",
        clock="2026-07-01T00:00:00Z",
    )
    set_clock("2026-07-10T16:00:00Z")
    get_success_data(api.check_in(inn["id"], confirmed["id"], INNKEEPER))
    before = get_success_data(api.get_room(inn["id"], room["id"], INNKEEPER))["version"]
    set_clock("2026-07-12T11:00:00Z")
    get_success_data(api.check_out(inn["id"], confirmed["id"], INNKEEPER))
    after = get_success_data(api.get_room(inn["id"], room["id"], INNKEEPER))["version"]
    assert after == before + 1


# ─── queue B: no-show side effects ───────────────────────────────────────────
def test_no_show_forfeits_deposit(api):
    """PRD §3.5: "A no-show forfeits the entire deposit with no refund —
    `payment_status` moves to `FORFEITED`, a zero-amount `FORFEIT` ledger entry
    is appended, the room's `version` is incremented by 1 as the interval is
    released, and any `REQUESTED` or `CONFIRMED` breakfast plan cascades to
    `CANCELLED`."

    Design: Corner/state_machines/no_show_forfeits_deposit_side_effect
    """
    inn, room, guest, confirmed, _gift = setup_confirmed_booking(
        inn_overrides={"name": "N Inn", "lodging_tax_rate_bps": 0},
        checkin_date="2026-06-20", checkout_date="2026-06-22",
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2026-06-21T12:00:00Z")  # arrival night has passed
    res = api.mark_no_show(inn["id"], confirmed["id"], INNKEEPER)
    bk = validate_success(res, 200)
    assert bk["reservation_status"] == "NO_SHOW"
    assert bk["payment_status"] == "FORFEITED"
    assert bk["refund_cents"] == 0


def test_no_show_before_arrival_night_rejected(api):
    """PRD §3.5: "It advances a `CONFIRMED` booking to `NO_SHOW`, but only after
    the arrival night has fully passed: the logical clock date must be strictly
    greater than `checkin_date`, and an attempt made before that point is
    rejected with `ERR_INVALID_STATE` as not yet no-show-eligible."

    Design: Corner/state_machines/no_show_before_checkin_passes_returns_invalid_state
    """
    inn, room, guest, confirmed, _gift = setup_confirmed_booking(
        inn_overrides={"name": "M Inn", "lodging_tax_rate_bps": 0},
        checkin_date="2026-06-20", checkout_date="2026-06-22",
        clock="2026-06-01T00:00:00Z",
    )
    # Clock still before checkin_date.
    res = api.mark_no_show(inn["id"], confirmed["id"], INNKEEPER)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_booking(inn["id"], confirmed["id"], INNKEEPER))
    assert after["reservation_status"] == "CONFIRMED"


# ─── queue B: terminal lockdown + invalid transitions ────────────────────────
def test_checked_out_booking_cannot_be_cancelled(api):
    """PRD §3.5: "A guest or innkeeper may cancel a booking while it is `PENDING`
    or `CONFIRMED`; a cancel from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_checked_out_blocks_further_transitions
    """
    inn, room, _guest, checked_out = setup_checked_out_booking(
        inn_overrides={"name": "L Inn", "lodging_tax_rate_bps": 0},
        checkin_date="2026-06-10", checkout_date="2026-06-12",
        open_clock="2026-06-01T00:00:00Z",
    )
    res = api.cancel_booking(inn["id"], checked_out["id"], INNKEEPER)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_booking(inn["id"], checked_out["id"], INNKEEPER))
    assert after["reservation_status"] == "CHECKED_OUT"


def test_cancel_already_cancelled_rejected(api):
    """PRD §3.5: "A guest or innkeeper may cancel a booking while it is `PENDING`
    or `CONFIRMED`; a cancel from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "K Inn", "lodging_tax_rate_bps": 0})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    get_success_data(api.cancel_booking(inn["id"], bk["id"], INNKEEPER))
    res = api.cancel_booking(inn["id"], bk["id"], INNKEEPER)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_booking(inn["id"], bk["id"], INNKEEPER))
    assert after["reservation_status"] == "CANCELLED"


# ─── queue B: cancel cascades breakfast plan ─────────────────────────────────
def test_cancel_cascades_breakfast_plan_to_cancelled(api):
    """PRD §3.5: "In either case the room's `version` is incremented by 1 as the
    night interval is released and the room becomes re-bookable, and any
    breakfast plan still in `REQUESTED` or `CONFIRMED` for that booking cascades
    to `CANCELLED`."

    Design: Corner/state_machines/cancel_cascades_breakfast_plan_to_cancelled
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "O Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"max_occupancy": 3})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12",
                        guest_count=2)
    plan = get_success_data(api.create_breakfast_plan(
        inn["id"], create_breakfast_plan_payload(bk["id"], 2, dietary_flags=["VEGAN"]),
        make_guest_headers(guest["id"])))
    get_success_data(api.cancel_booking(inn["id"], bk["id"], INNKEEPER))
    after = get_success_data(api.get_breakfast_plan(inn["id"], plan["id"], INNKEEPER))
    assert after["status"] == "CANCELLED"


# ─── queue B: housekeeping branches ──────────────────────────────────────────
def test_housekeeping_skip_from_pending(api):
    """PRD §3.7: "Alternatively the innkeeper may skip turnover, advancing it
    directly from `PENDING` to `SKIPPED` to waive cleaning."

    Design: Corner/state_machines/housekeeping_skip_from_pending
    """
    inn, room, _guest, checked_out = setup_checked_out_booking(
        inn_overrides={"name": "P Inn", "lodging_tax_rate_bps": 0, "turnover_minutes": 60},
        checkin_date="2026-06-10", checkout_date="2026-06-12",
        open_clock="2026-06-01T00:00:00Z",
    )
    task = get_turnover_task(inn["id"], checked_out["id"])
    res = api.skip_housekeeping_task(inn["id"], task["id"], INNKEEPER)
    skipped = validate_success(res, 200)
    assert skipped["status"] == "SKIPPED"


def test_housekeeping_complete_from_pending_rejected(api):
    """PRD §3.7: "Starting turnover advances it from `PENDING` to `IN_PROGRESS`,
    and completing it advances it from `IN_PROGRESS` to `DONE`; either action
    taken out of its required starting state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/housekeeping_complete_from_pending_returns_invalid_state
    """
    inn, room, _guest, checked_out = setup_checked_out_booking(
        inn_overrides={"name": "Q Inn", "lodging_tax_rate_bps": 0, "turnover_minutes": 60},
        checkin_date="2026-06-10", checkout_date="2026-06-12",
        open_clock="2026-06-01T00:00:00Z",
    )
    task = get_turnover_task(inn["id"], checked_out["id"])
    res = api.complete_housekeeping_task(inn["id"], task["id"], HOUSEKEEPER)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_housekeeping_task(inn["id"], task["id"], HOUSEKEEPER))
    assert after["status"] == "PENDING"


# ─── queue B: gift void precondition ─────────────────────────────────────────
def test_gift_void_with_redemption_rejected(api):
    """PRD §3.8: "A `FinanceManager` may void a certificate, moving it from
    `ACTIVE` to `VOID`, but only when it has never been redeemed (no `REDEMPTION`
    ledger entry references it, equivalently its `remaining_cents` still equals
    its `face_value_cents`); a void attempt on a partially redeemed certificate
    fails the state guard with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/gift_void_with_redemption_returns_invalid_state
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "R Inn", "lodging_tax_rate_bps": 0})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 20000), FINANCE))
    get_success_data(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 5000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER))
    cur = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    res = api.void_gift_certificate(
        inn["id"], gift["id"], {"expected_gift_certificate_version": cur["version"]}, FINANCE)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert after["status"] == "ACTIVE"
