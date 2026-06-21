"""Validation errors, the one PRD-stated confirm precedence (state before
deposit), the breakfast-plan cross-entity dependency, and optimistic concurrency.

Covers queue-A cross_entity_state_dependency (breakfast), priority_pair
(invalid_state beats deposit — PRD-stated), and queue-B validation + OCC corners.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_inn_payload,
    create_room_payload,
    create_rate_period_payload,
    create_guest_payload,
    create_booking_payload,
    create_breakfast_plan_payload,
    create_gift_certificate_payload,
    create_tax_remittance_payload,
    TEST_USERS,
    make_guest_headers,
    set_clock,
    setup_inn_room_guest,
    create_booking,
    cover_deposit_via_gift,
    confirm_booking,
    current_room_version,
    setup_pending_booking_with_breakfast,
)
from test_helpers import api_client

INNKEEPER = TEST_USERS["innkeeper_headers"]
HOUSEKEEPER = TEST_USERS["housekeeper_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ─── priority_pair: invalid_state precedes deposit on confirm ────────────────
def test_confirm_cancelled_booking_reports_invalid_state_not_deposit(api):
    """PRD §3.4: "If the deposit is short the confirm is rejected with
    `ERR_DEPOSIT_NOT_MET`; the deposit-coverage check (priority 80) is evaluated
    after the double-booking check, and both presuppose the booking is actually
    `PENDING` — a confirm on a booking in any other state fails the state guard
    with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_deposit_on_confirm
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Dune Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Coral", "base_rate_cents": 10000})
    # PENDING booking, deposit never paid, then cancelled -> CANCELLED + unmet deposit.
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-04-20", "2026-04-22")
    get_success_data(api.cancel_booking(inn["id"], bk["id"], INNKEEPER))
    rv = current_room_version(inn["id"], room["id"])
    res = api.confirm_booking(inn["id"], bk["id"], {"expected_room_version": rv}, INNKEEPER)
    validate_error(res, "ERR_INVALID_STATE")


def test_confirm_cancelled_booking_does_not_advance_state(api):
    """PRD §3.4: "a confirm on a booking in any other state fails the state guard
    with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_deposit_on_confirm
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Dune2 Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Coral2", "base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-04-20", "2026-04-22")
    get_success_data(api.cancel_booking(inn["id"], bk["id"], INNKEEPER))
    rv = current_room_version(inn["id"], room["id"])
    api.confirm_booking(inn["id"], bk["id"], {"expected_room_version": rv}, INNKEEPER)
    after = get_success_data(api.get_booking(inn["id"], bk["id"], INNKEEPER))
    assert after["reservation_status"] == "CANCELLED"


# ─── cross_entity_state_dependency: breakfast confirm needs live booking ─────
def test_breakfast_confirm_on_pending_booking_rejected(api):
    """PRD §3.6: "Confirmation is allowed only while the plan is `REQUESTED` and
    the parent booking is `CONFIRMED` or `CHECKED_IN` — the kitchen will not
    commit covers for a stay that is not live — and a confirm in any other
    situation is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/breakfast_confirm_requires_booking_confirmed_or_checked_in
    """
    inn, room, guest, booking, plan = setup_pending_booking_with_breakfast(
        party_size=2, dietary_flags=["VEGETARIAN"], max_occupancy=3)
    res = api.confirm_breakfast_plan(inn["id"], plan["id"], INNKEEPER)
    validate_error(res, "ERR_INVALID_STATE")


def test_breakfast_confirm_on_pending_booking_leaves_requested(api):
    """PRD §3.6: "Confirmation is allowed only while the plan is `REQUESTED` and
    the parent booking is `CONFIRMED` or `CHECKED_IN` — the kitchen will not
    commit covers for a stay that is not live — and a confirm in any other
    situation is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/breakfast_confirm_requires_booking_confirmed_or_checked_in
    """
    inn, room, guest, booking, plan = setup_pending_booking_with_breakfast(
        party_size=2, dietary_flags=["VEGETARIAN"], max_occupancy=3)
    api.confirm_breakfast_plan(inn["id"], plan["id"], INNKEEPER)
    after = get_success_data(api.get_breakfast_plan(inn["id"], plan["id"], INNKEEPER))
    assert after["status"] == "REQUESTED"


# ─── queue B: single-failure validations ─────────────────────────────────────
def test_occupancy_exceeded_rejected(api):
    """PRD §3.2: "The `guest_count` must be at least 1 and must not exceed the
    room's `max_occupancy`, or the request is rejected with
    `ERR_OCCUPANCY_EXCEEDED`."

    Design: Corner/validations/occupancy_exceeded_rejected
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "X Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"max_occupancy": 2})
    res = api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest["id"], "2026-05-10",
                               "2026-05-12", channel="DIRECT", guest_count=4),
        INNKEEPER)
    validate_error(res, "ERR_OCCUPANCY_EXCEEDED")


def test_invalid_date_range_rate_period_rejected(api):
    """PRD §3.1: "A rate period created with an `end_date` earlier than its
    `start_date` is rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/invalid_date_range_rejected
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Cc Inn", lodging_tax_rate_bps=0), INNKEEPER))
    res = api.create_rate_period(
        inn["id"],
        create_rate_period_payload(inn["id"], "2026-08-31", "2026-08-01", label="Bad",
                                   rate_multiplier_bps=15000),
        INNKEEPER)
    validate_error(res, "ERR_INVALID_DATE_RANGE")


def test_deposit_not_met_blocks_confirm(api):
    """PRD §3.4: "If the deposit is short the confirm is rejected with
    `ERR_DEPOSIT_NOT_MET`; the deposit-coverage check (priority 80) is evaluated
    after the double-booking check, and both presuppose the booking is actually
    `PENDING` — a confirm on a booking in any other state fails the state guard
    with `ERR_INVALID_STATE`."

    Design: Corner/validations/deposit_not_met_blocks_confirm
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Y Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    rv = current_room_version(inn["id"], room["id"])
    res = api.confirm_booking(inn["id"], bk["id"], {"expected_room_version": rv}, INNKEEPER)
    validate_error(res, "ERR_DEPOSIT_NOT_MET")
    after = get_success_data(api.get_booking(inn["id"], bk["id"], INNKEEPER))
    assert after["reservation_status"] == "PENDING"


def test_pay_deposit_overpay_rejected(api):
    """PRD §3.3: "A cash deposit is recorded by a guest or innkeeper supplying an
    `amount_cents`; the amount must be at least 1 and must not exceed the
    outstanding balance — the `total_cents` minus the current `deposit_paid_cents`
    — or the payment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/pay_deposit_overpay_rejected
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Oo Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    # total 20000; attempt to pay 25000.
    res = api.pay_deposit(inn["id"], bk["id"], {"amount_cents": 25000}, INNKEEPER)
    validate_error(res, "ERR_PAYMENT_EXCEEDS_BALANCE")
    after = get_success_data(api.get_booking(inn["id"], bk["id"], INNKEEPER))
    assert after["deposit_paid_cents"] == 0


def test_breakfast_party_over_count_rejected(api):
    """PRD §3.6: "The `party_size` must not exceed the parent booking's
    `guest_count`; an over-large party is rejected with `ERR_BREAKFAST_OVER_PARTY`."

    Design: Corner/validations/breakfast_party_over_count_rejected
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Z Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"max_occupancy": 4})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12",
                        guest_count=2)
    res = api.create_breakfast_plan(
        inn["id"], create_breakfast_plan_payload(bk["id"], 3), make_guest_headers(guest["id"]))
    validate_error(res, "ERR_BREAKFAST_OVER_PARTY")


def test_gift_redeem_overdraw_rejected(api):
    """PRD §3.3: "The redemption amount must be at least 1 and no greater than the
    lesser of the certificate's `remaining_cents` and the booking's outstanding
    owed balance (`total_cents` minus `deposit_paid_cents`); the certificate must
    be `ACTIVE` and not yet expired, meaning the logical clock date is strictly
    before its `expires_on`. A redemption that breaks any of these conditions is
    rejected with `ERR_GIFT_INSUFFICIENT`."

    Design: Corner/validations/gift_insufficient_overdraw_rejected
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Aa Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 3000), FINANCE))
    res = api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 9000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER)
    validate_error(res, "ERR_GIFT_INSUFFICIENT")
    after = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert after["remaining_cents"] == 3000, "untouched"


# ─── queue B: optimistic concurrency ─────────────────────────────────────────
def test_confirm_with_stale_room_version_rejected(api):
    """PRD §2.7: "If the room's `version` has advanced since the client read it —
    for instance because another booking on the same room was confirmed in the
    interim and now occupies an adjacent or overlapping interval — the confirm is
    rejected with `ERR_STALE_ROOM_VERSION` at HTTP 412, so the client never
    confirms against committed intervals it has not seen."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_room_version_on_confirm
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Ii Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    # bk1 (non-overlapping nights) + bk2, both deposit-met via gift.
    bk1 = create_booking(inn["id"], room["id"], guest["id"], "2026-04-01", "2026-04-03")
    cover_deposit_via_gift(inn["id"], bk1["id"], 10000, gift_face_cents=20000)
    bk2 = create_booking(inn["id"], room["id"], guest["id"], "2026-04-20", "2026-04-22")
    cover_deposit_via_gift(inn["id"], bk2["id"], 10000, gift_face_cents=20000)
    stale_rv = current_room_version(inn["id"], room["id"])
    # Confirm bk1 -> room.version advances, making stale_rv stale for bk2.
    get_success_data(api.confirm_booking(
        inn["id"], bk1["id"], {"expected_room_version": stale_rv}, INNKEEPER))
    res = api.confirm_booking(inn["id"], bk2["id"], {"expected_room_version": stale_rv}, INNKEEPER)
    validate_error(res, "ERR_STALE_ROOM_VERSION")
    after = get_success_data(api.get_booking(inn["id"], bk2["id"], INNKEEPER))
    assert after["reservation_status"] == "PENDING"


def test_confirm_with_current_room_version_succeeds_and_bumps(api):
    """PRD §2.7: "The confirm request must therefore carry `expected_room_version`,
    the room `version` the client last observed."
    PRD §3.4: "A successful confirm, which also carries `expected_room_version`
    and is rejected with `ERR_STALE_ROOM_VERSION` if that value no longer matches
    the room's `version` (§2.7), drives the money axis from `UNPAID` to
    `DEPOSIT_HELD` and increments the room's `version` by 1, committing the
    interval."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_room_version_confirm_succeeds
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Jj Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    cover_deposit_via_gift(inn["id"], bk["id"], 10000, gift_face_cents=20000)
    rv = current_room_version(inn["id"], room["id"])
    confirmed = validate_success(
        api.confirm_booking(inn["id"], bk["id"], {"expected_room_version": rv}, INNKEEPER), 200)
    assert confirmed["reservation_status"] == "CONFIRMED"
    after_rv = current_room_version(inn["id"], room["id"])
    assert after_rv == rv + 1


def test_redeem_gift_with_stale_cert_version_rejected(api):
    """PRD §2.7: "If that `version` no longer matches the certificate's current
    `version` — because another booking already drew down part of the balance —
    the redemption is rejected with `ERR_STALE_GIFT_VERSION` at HTTP 412 rather
    than overdrawing the certificate."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_gift_version_on_redeem
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Kk Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk_a = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    bk_b = create_booking(inn["id"], room["id"], guest["id"], "2026-06-10", "2026-06-12")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 30000), FINANCE))
    stale_v = gift["version"]
    # First redemption against bk_a advances the cert version.
    get_success_data(api.redeem_gift(
        inn["id"], bk_a["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 5000,
         "expected_gift_certificate_version": stale_v}, INNKEEPER))
    res = api.redeem_gift(
        inn["id"], bk_b["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 5000,
         "expected_gift_certificate_version": stale_v}, INNKEEPER)
    validate_error(res, "ERR_STALE_GIFT_VERSION")


def test_deposit_paid_reconciles_after_two_redemptions(api):
    """PRD §3.3: "The `deposit_paid_cents` figure is the sum of `DEPOSIT` and
    `REDEMPTION` entry amounts (money in, including gift redemptions) net of any
    `REFUND` entries."

    Design: Corner/cross_cutting_complexity_layers/derived_deposit_paid_reconciles_after_redemption
    """
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Ll Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 20000), FINANCE))
    get_success_data(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 4000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER))
    cur = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    bk_after = validate_success(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 3000,
         "expected_gift_certificate_version": cur["version"]}, INNKEEPER), 200)
    assert bk_after["deposit_paid_cents"] == 7000, "4000 + 3000"
