"""Cancellation refunds and gift-certificate value flow: tier boundaries, the
depth-3 cancel -> refund -> gift-restore -> cert-flip cascade, the cash-first
waterfall, the refund quote, and the gift/occupancy conservation invariants.

Covers queue-A boundary_precision_check (14-day tier), transitive_cascade (cancel
depth-3), compensating_invariant, and queue-B calculation corners.
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    create_inn_payload,
    create_room_payload,
    create_guest_payload,
    create_booking_payload,
    create_gift_certificate_payload,
    TEST_USERS,
    make_guest_headers,
    set_clock,
    setup_inn_room_guest,
    create_booking,
    cover_deposit_via_gift,
    confirm_booking,
)
from test_helpers import api_client

INNKEEPER = TEST_USERS["innkeeper_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _confirmed_via_gift(api, inn_id, room_id, guest_id, checkin, checkout, gift_amount=10000, face=None):
    """Create a DIRECT booking, fully cover deposit by redeeming a gift, confirm.
    Returns (booking_confirmed, gift)."""
    bk = create_booking(inn_id, room_id, guest_id, checkin, checkout)
    gift = cover_deposit_via_gift(inn_id, bk["id"], gift_amount, gift_face_cents=face)
    confirmed = confirm_booking(inn_id, room_id, bk["id"])
    return confirmed, gift


# ─── boundary_precision_check: 14-day cancellation tier ──────────────────────
def test_cancel_exactly_14_days_before_full_refund(api):
    """PRD §3.5: "When `days_before` is 14 or more the refund is 100% of
    `deposit_paid_cents`; when it is at least 7 but fewer than 14 the refund is
    50%; when it is at least 1 but fewer than 7 the refund is 10%; and when it is
    0 (same day) the refund is nothing."

    Design: Difficulty/boundary_precision_check/cancellation_tier_14_day_boundary_inclusive
    """
    set_clock("2026-05-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Glen Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Heath", "base_rate_cents": 10000})
    confirmed, _gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-06-15", "2026-06-17")
    # Exactly 14 days before 06-15 is 06-01 -> full refund.
    set_clock("2026-06-01T09:00:00Z")
    bk = validate_success(api.cancel_booking(inn["id"], confirmed["id"], INNKEEPER), 200)
    assert bk["refund_cents"] == 10000


def test_cancel_13_days_before_half_refund(api):
    """PRD §3.5: "When `days_before` is 14 or more the refund is 100% of
    `deposit_paid_cents`; when it is at least 7 but fewer than 14 the refund is
    50%; when it is at least 1 but fewer than 7 the refund is 10%; and when it is
    0 (same day) the refund is nothing."

    Design: Difficulty/boundary_precision_check/cancellation_tier_14_day_boundary_inclusive
    """
    set_clock("2026-05-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Glen Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Moor", "base_rate_cents": 10000})
    confirmed, _gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-06-15", "2026-06-17")
    # 13 days before 06-15 is 06-02 -> half refund.
    set_clock("2026-06-02T09:00:00Z")
    bk = validate_success(api.cancel_booking(inn["id"], confirmed["id"], INNKEEPER), 200)
    assert bk["refund_cents"] == 5000


# ─── queue B: token tier (1 day) and zero-day boundary ───────────────────────
def test_cancel_one_day_before_token_tier(api):
    """PRD §3.5: "When `days_before` is 14 or more the refund is 100% of
    `deposit_paid_cents`; when it is at least 7 but fewer than 14 the refund is
    50%; when it is at least 1 but fewer than 7 the refund is 10%; and when it is
    0 (same day) the refund is nothing."

    Design: Corner/calculations/cancellation_token_tier_and_zero_day_boundary
    """
    set_clock("2026-07-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "U Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Ga", "base_rate_cents": 10000})
    confirmed, _gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-07-15", "2026-07-17")
    # 1 day before 07-15 is 07-14 -> 10% token tier.
    set_clock("2026-07-14T09:00:00Z")
    bk = validate_success(api.cancel_booking(inn["id"], confirmed["id"], INNKEEPER), 200)
    assert bk["refund_cents"] == 1000


def test_cancel_same_day_zero_refund(api):
    """PRD §3.5: "When `days_before` is 14 or more the refund is 100% of
    `deposit_paid_cents`; when it is at least 7 but fewer than 14 the refund is
    50%; when it is at least 1 but fewer than 7 the refund is 10%; and when it is
    0 (same day) the refund is nothing."

    Design: Corner/calculations/cancellation_token_tier_and_zero_day_boundary
    """
    set_clock("2026-07-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "U Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Gb", "base_rate_cents": 10000})
    confirmed, _gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-07-15", "2026-07-17")
    # Same day (07-15) -> 0%.
    set_clock("2026-07-15T09:00:00Z")
    bk = validate_success(api.cancel_booking(inn["id"], confirmed["id"], INNKEEPER), 200)
    assert bk["refund_cents"] == 0


# ─── transitive_cascade: cancel -> refund -> gift restore -> cert flip ───────
def test_cancel_full_refund_restores_gift_balance(api):
    """PRD §3.5: "That gift remainder is added back to the certificate's
    `remaining_cents`, and if the certificate had been sitting in `DEPLETED`, the
    restoration of a positive balance returns it to `ACTIVE` — provided its
    `expires_on` is still in the future relative to the logical clock."

    Design: Difficulty/transitive_cascade/cancel_refund_restores_gift_flips_cert_status_depth3
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Sage Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Dahlia", "base_rate_cents": 10000})
    confirmed, gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-03-15", "2026-03-17")
    bk = validate_success(api.cancel_booking(inn["id"], confirmed["id"], INNKEEPER), 200)
    assert bk["refund_cents"] == 10000, "20+ days before -> full tier"
    assert bk["payment_status"] == "REFUNDED"
    final = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert final["remaining_cents"] == 10000


def test_cancel_flips_depleted_cert_back_to_active(api):
    """PRD §3.5: "if the certificate had been sitting in `DEPLETED`, the
    restoration of a positive balance returns it to `ACTIVE` — provided its
    `expires_on` is still in the future relative to the logical clock."

    Design: Difficulty/transitive_cascade/cancel_refund_restores_gift_flips_cert_status_depth3
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Sage Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Dahlia2", "base_rate_cents": 10000})
    confirmed, gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-03-15", "2026-03-17")
    depleted = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert depleted["status"] == "DEPLETED"
    get_success_data(api.cancel_booking(inn["id"], confirmed["id"], INNKEEPER))
    final = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert final["status"] == "ACTIVE"


# ─── queue B: cash-first waterfall ───────────────────────────────────────────
def test_refund_waterfall_fills_cash_before_gift(api):
    """PRD §3.5: "The system looks at the booking's ledger and computes the cash
    deposit total and the redeemed gift total; the `refund_cents` is allocated to
    the cash bucket first, up to the amount of cash actually deposited, and only
    the remainder spills into the gift bucket."

    Design: Corner/calculations/refund_waterfall_cash_first_then_gift
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Nn2 Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-03-15", "2026-03-18")
    # deposit_due is 10000 (first-night floor). Pay 4000 cash + 6000 gift.
    get_success_data(api.pay_deposit(inn["id"], bk["id"], {"amount_cents": 4000}, INNKEEPER))
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 6000), FINANCE))
    get_success_data(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 6000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER))
    confirm_booking(inn["id"], room["id"], bk["id"])
    cancelled = validate_success(api.cancel_booking(inn["id"], bk["id"], INNKEEPER), 200)
    assert cancelled["refund_cents"] == 10000, "full refund of deposit_paid 10000"
    final = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert final["remaining_cents"] == 6000, "gift bucket (6000) fully restored after cash"
    assert final["status"] == "ACTIVE"


# ─── queue B: refund quote is non-mutating ───────────────────────────────────
def test_refund_quote_does_not_mutate_booking(api):
    """PRD §3.5: "The quote is purely advisory: it returns a booking snapshot
    whose `refund_cents` reflects the provisional figure but mutates nothing — no
    state change, no ledger entry, no gift restoration."

    Design: Corner/calculations/refund_quote_provisional_does_not_mutate_booking
    """
    set_clock("2026-07-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "V Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"base_rate_cents": 10000})
    confirmed, _gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-07-25", "2026-07-27")
    # 24 days before -> full tier provisional 10000.
    quote = get_success_data(api.refund_quote(
        inn["id"], confirmed["id"], make_guest_headers(guest["id"])))
    assert quote["refund_cents"] == 10000
    after = get_success_data(api.get_booking(inn["id"], confirmed["id"], INNKEEPER))
    assert after["reservation_status"] == "CONFIRMED", "quote must not change state"


# ─── compensating_invariant: gift money conserved ────────────────────────────
def test_gift_value_conserved_redeem_then_full_refund_cancel(api):
    """PRD §3.3: "if the debit drives `remaining_cents` to exactly 0 — moves the
    certificate to `DEPLETED`."
    PRD §3.5: "That gift remainder is added back to the certificate's
    `remaining_cents`, and if the certificate had been sitting in `DEPLETED`, the
    restoration of a positive balance returns it to `ACTIVE` — provided its
    `expires_on` is still in the future relative to the logical clock."

    Design: Difficulty/compensating_invariant/gift_value_conserved_across_redeem_and_cancel_restore
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Loch Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Quill", "base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-03-15", "2026-03-17")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 10000), FINANCE))
    get_success_data(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 10000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER))
    redeemed = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert redeemed["remaining_cents"] == 0
    confirm_booking(inn["id"], room["id"], bk["id"])
    get_success_data(api.cancel_booking(inn["id"], bk["id"], INNKEEPER))
    final = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert final["remaining_cents"] == final["face_value_cents"], "gift money conserved"
    assert final["remaining_cents"] == 10000


def test_gift_remaining_returns_to_face_after_full_cycle(api):
    """PRD §3.8: "an initial `remaining_cents` equal to the face value."
    PRD §3.5: "That gift remainder is added back to the certificate's
    `remaining_cents`, and if the certificate had been sitting in `DEPLETED`, the
    restoration of a positive balance returns it to `ACTIVE` — provided its
    `expires_on` is still in the future relative to the logical clock."

    Design: Difficulty/compensating_invariant/gift_value_conserved_across_redeem_and_cancel_restore
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Loch Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Quill2", "base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-03-15", "2026-03-17")
    gift = get_success_data(api.create_gift_certificate(
        inn["id"], create_gift_certificate_payload(inn["id"], 10000), FINANCE))
    face = gift["face_value_cents"]
    get_success_data(api.redeem_gift(
        inn["id"], bk["id"],
        {"gift_certificate_id": gift["id"], "amount_cents": 10000,
         "expected_gift_certificate_version": gift["version"]}, INNKEEPER))
    confirm_booking(inn["id"], room["id"], bk["id"])
    get_success_data(api.cancel_booking(inn["id"], bk["id"], INNKEEPER))
    final = get_success_data(api.get_gift_certificate(inn["id"], gift["id"], FINANCE))
    assert final["remaining_cents"] == face


# ─── compensating_invariant: room-night occupancy conserved ──────────────────
def test_confirm_then_cancel_releases_interval_for_rebooking(api):
    """PRD §3.5: "In either case the room's `version` is incremented by 1 as the
    night interval is released and the room becomes re-bookable, and any
    breakfast plan still in `REQUESTED` or `CONFIRMED` for that booking cascades
    to `CANCELLED`."

    Design: Difficulty/compensating_invariant/room_night_occupancy_conserved_across_confirm_and_cancel
    """
    set_clock("2026-11-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Frost Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Snow", "base_rate_cents": 10000})
    confirmed, _gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-12-10", "2026-12-12")
    get_success_data(api.cancel_booking(inn["id"], confirmed["id"], INNKEEPER))
    cancelled = get_success_data(api.get_booking(inn["id"], confirmed["id"], INNKEEPER))
    assert cancelled["reservation_status"] == "CANCELLED"
    # Second booking on exactly the released nights confirms successfully.
    bk2, _g2 = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-12-10", "2026-12-12")
    assert bk2["reservation_status"] == "CONFIRMED"


def test_second_booking_on_released_nights_confirms(api):
    """PRD §3.4: "The overlap check (priority 70) looks at the half-open night
    interval running from `checkin_date` up to `checkout_date` and rejects the
    confirm with `ERR_ROOM_DOUBLE_BOOKED` if any other `CONFIRMED` or
    `CHECKED_IN` booking on the same room overlaps it; because the interval is
    half-open, a booking that ends exactly on the night another begins does not
    overlap, so same-day back-to-back turnover is permitted at the date level."

    Design: Difficulty/compensating_invariant/room_night_occupancy_conserved_across_confirm_and_cancel
    """
    set_clock("2026-11-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Frost2 Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Snow2", "base_rate_cents": 10000})
    confirmed, _gift = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-12-10", "2026-12-12")
    get_success_data(api.cancel_booking(inn["id"], confirmed["id"], INNKEEPER))
    # Re-booking the released interval must succeed (CONFIRMED, no double-book).
    bk2, _g2 = _confirmed_via_gift(
        api, inn["id"], room["id"], guest["id"], "2026-12-10", "2026-12-12")
    assert bk2["reservation_status"] == "CONFIRMED"
