"""Booking creation, deposit/total/corkage pricing, and the validation guards on POST /bookings
and POST /bookings/{id}/pay-deposit.

Each test translates exactly one design-index instance; docstrings end with the Design tag.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    provision_open_event, provision_scheduled_event, provision_pending_booking,
    provision_confirmed_booking, create_guest, book_seats, pay_deposit, get_event,
    set_clock, make_guest_headers, create_booking_payload,
    api_client,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Difficulty: dual_variant_calc / deposit vs total on one booking ───

def test_deposit_due_is_provisional_fraction(api):
    """PRD §3.5: "For each seat in seat_ids, take that seat's base price, multiply it by the
    event's deposit_pct, and round the result to whole cents using round half up. The per-seat
    rounded deposits are then summed to yield deposit_due_cents."

    Design: Difficulty/dual_variant_calc/deposit_provisional_vs_total_final_on_booking
    """
    _ctx, _guest, booking = provision_pending_booking(
        seat_count=2, seat_price_cents=10000, deposit_pct=0.25, table_mode="PRIVATE")
    assert booking["deposit_due_cents"] == 5000, booking["deposit_due_cents"]


def test_total_price_is_full_settlement_and_differs_from_deposit(api):
    """PRD §3.5: "The total_price_cents is then the subtotal minus the group discount plus the
    corkage."

    Design: Difficulty/dual_variant_calc/deposit_provisional_vs_total_final_on_booking
    """
    _ctx, _guest, booking = provision_pending_booking(
        seat_count=2, seat_price_cents=10000, deposit_pct=0.25, table_mode="PRIVATE")
    assert booking["total_price_cents"] == 20000, booking["total_price_cents"]
    assert booking["deposit_due_cents"] != booking["total_price_cents"]


# ─── Difficulty: combinatorial_formula / group discount + deposit rounding ─

def test_group_discount_tiered_total(api):
    """PRD §3.5: "A group discount applies only when the event's table_mode is PRIVATE and
    party_size is at least 6; otherwise the discount is 0. When it applies, the discount rate is
    0.15 if party_size is at least 10, and 0.10 otherwise; the raw discount is that rate
    multiplied by the subtotal, rounded to whole cents using round half up, and then capped so
    that it never exceeds 15000 cents (the discount is the smaller of the rounded figure and that
    cap)."

    Design: Difficulty/combinatorial_formula/group_discount_tiered_nonlinear_total
    """
    _ctx, _guest, booking = provision_pending_booking(
        seat_count=6, seat_price_cents=10000, deposit_pct=0.25, table_mode="PRIVATE")
    # subtotal 60000, party 6 -> rate 0.10 -> discount 6000 (< cap) -> total 54000.
    assert booking["total_price_cents"] == 54000, booking["total_price_cents"]


def test_group_discount_booking_deposit_rounds_per_seat(api):
    """PRD §3.5: "The per-seat rounded deposits are then summed to yield deposit_due_cents. The
    rounding order is pinned: round each seat individually first, then sum — never sum first and
    round once."

    Design: Difficulty/combinatorial_formula/group_discount_tiered_nonlinear_total
    """
    _ctx, _guest, booking = provision_pending_booking(
        seat_count=6, seat_price_cents=10000, deposit_pct=0.25, table_mode="PRIVATE")
    # per-seat round_half_up(10000*0.25)=2500, summed over 6 = 15000.
    assert booking["deposit_due_cents"] == 15000, booking["deposit_due_cents"]


def test_deposit_rounds_each_seat_then_sums(api):
    """PRD §3.5: "The per-seat rounded deposits are then summed to yield deposit_due_cents. The
    rounding order is pinned: round each seat individually first, then sum — never sum first and
    round once."

    Design: Difficulty/combinatorial_formula/deposit_round_per_seat_then_sum
    """
    _ctx, _guest, booking = provision_pending_booking(
        seat_count=2, seat_price_cents=4990, deposit_pct=0.25, table_mode="COMMUNAL")
    # per-seat round_half_up(4990*0.25 = 1247.5) = 1248; summed over 2 = 2496.
    assert booking["deposit_due_cents"] == 2496, booking["deposit_due_cents"]


def test_deposit_rounding_order_not_sum_then_round(api):
    """PRD §2.5: "Where a calculation both rounds and sums, the pinned order stated in §3 must
    be followed exactly, because rounding each component before summing can differ from summing
    before rounding."

    Design: Difficulty/combinatorial_formula/deposit_round_per_seat_then_sum
    """
    _ctx, _guest, booking = provision_pending_booking(
        seat_count=2, seat_price_cents=4990, deposit_pct=0.25, table_mode="COMMUNAL")
    # sum-then-round would give round_half_up(2495.0) = 2495; the pinned order gives 2496.
    assert booking["deposit_due_cents"] != 2495
    assert booking["deposit_due_cents"] == 2496


# ─── Difficulty: boundary_precision_check / party_size >= 6 ────────────

def test_party_size_exactly_6_triggers_discount(api):
    """PRD §3.5: "A group discount applies only when the event's table_mode is PRIVATE and
    party_size is at least 6; otherwise the discount is 0."

    Design: Difficulty/boundary_precision_check/group_discount_party_size_gte_6_boundary
    """
    _ctx, _guest, booking = provision_pending_booking(
        seat_count=6, seat_price_cents=10000, deposit_pct=0.25, table_mode="PRIVATE")
    assert booking["total_price_cents"] == 54000, booking["total_price_cents"]


def test_party_size_5_below_boundary_no_discount(api):
    """PRD §3.5: "A group discount applies only when the event's table_mode is PRIVATE and
    party_size is at least 6; otherwise the discount is 0."

    Design: Difficulty/boundary_precision_check/group_discount_party_size_gte_6_boundary
    """
    _ctx, _guest, booking = provision_pending_booking(
        seat_count=5, seat_price_cents=10000, deposit_pct=0.25, table_mode="PRIVATE")
    # party 5 (< 6) -> no discount -> total == subtotal 50000.
    assert booking["total_price_cents"] == 50000, booking["total_price_cents"]


# ─── Corner: calculations / corkage + head-table supplement ────────────

def test_corkage_computed_on_byob_booking(api):
    """PRD §3.5: "Corkage is added next: when the event's byob_allowed is true, corkage equals
    byob_bottles multiplied by the event's corkage_fee_cents; when BYOB is not allowed, corkage
    is 0. The total_price_cents is then the subtotal minus the group discount plus the corkage."

    Design: Corner/calculations/corkage_computed_on_byob_booking
    """
    ctx = provision_open_event(event_overrides={
        "seat_capacity": 2, "seat_price_cents": 10000, "deposit_pct": 0.25,
        "table_mode": "PRIVATE", "byob_allowed": True, "corkage_fee_cents": 1500})
    guest = create_guest()
    seat_ids = [s["id"] for s in ctx["seats"][:2]]
    booking = book_seats(ctx["event"]["id"], guest["id"], seat_ids, party_size=2, byob_bottles=2)
    assert booking["corkage_due_cents"] == 3000, booking["corkage_due_cents"]
    # subtotal 20000, party 2 -> no discount, corkage 3000 -> total 23000.
    assert booking["total_price_cents"] == 23000, booking["total_price_cents"]


def test_head_table_supplement_in_deposit_and_total(api):
    """PRD §3.5: "For a given seat, the base price is the seat's own price_override_cents when
    that override is set, otherwise the event's seat_price_cents; then, if that seat's seat_type
    is HEAD_TABLE, a head-table supplement of 2000 cents is added on top."

    Design: Corner/calculations/head_table_supplement_in_deposit_and_total
    """
    ctx = provision_open_event(
        head_table_count=1,
        event_overrides={"seat_capacity": 2, "seat_price_cents": 10000,
                         "deposit_pct": 0.25, "table_mode": "PRIVATE"})
    head_seat = ctx["seats"][0]
    assert head_seat["seat_type"] == "HEAD_TABLE"
    guest = create_guest()
    booking = book_seats(ctx["event"]["id"], guest["id"], [head_seat["id"]], party_size=1)
    # base 10000+2000=12000; deposit round_half_up(12000*0.25)=3000; total (party 1) = 12000.
    assert booking["deposit_due_cents"] == 3000, booking["deposit_due_cents"]
    assert booking["total_price_cents"] == 12000, booking["total_price_cents"]


# ─── Corner: entities / booking system-field defaults ──────────────────

def test_booking_system_fields_defaulted_on_create(api):
    """PRD §3.5: "On success the booking is created with booking_status of PENDING_DEPOSIT and,
    on the independent money dimension, payment_status of UNPAID."

    Design: Corner/entities/booking_system_fields_defaulted_on_create
    """
    _ctx, _guest, booking = provision_pending_booking(seat_count=1)
    assert booking["deposit_paid_cents"] == 0
    assert booking["refund_cents"] == 0
    assert booking["payment_status"] == "UNPAID"
    assert booking["booking_status"] == "PENDING_DEPOSIT"


# ─── Corner: consistency_model / booking holds seat immediately ────────

def test_booking_reduces_available_seat_count_same_flow(api):
    """PRD §3.5: "Each requested seat transitions AVAILABLE → HELD and records the new booking's
    id in its current_booking_id."
    PRD §3.8: "available_seat_count is the number whose status is AVAILABLE".

    Design: Corner/consistency_model/booking_create_holds_seat_same_request
    """
    ctx = provision_open_event(event_overrides={"seat_capacity": 2})
    guest = create_guest()
    book_seats(ctx["event"]["id"], guest["id"], [ctx["seats"][0]["id"]], party_size=1)
    event = get_event(ctx["event"]["id"])
    assert event["available_seat_count"] == 1, event["available_seat_count"]


# ─── Corner: validations / pay-deposit success + mismatch ──────────────

def test_pay_exact_deposit_confirms_booking(api):
    """PRD §3.5: "Paying the deposit advances the booking PENDING_DEPOSIT → CONFIRMED. The
    request carries amount_cents, which must exactly equal the booking's deposit_due_cents".
    PRD §3.8: "confirmed_seat_count is the number of the event's seats whose status is BOOKED".

    Design: Corner/validations/pay_deposit_exact_amount_confirms_booking
    """
    ctx, guest, booking = provision_pending_booking(seat_count=2, seat_price_cents=10000,
                                                    deposit_pct=0.25, table_mode="COMMUNAL")
    assert booking["deposit_due_cents"] == 5000
    paid = pay_deposit(booking["id"], guest["id"], 5000)
    assert paid["booking_status"] == "CONFIRMED"
    assert paid["payment_status"] == "DEPOSIT_PAID"
    event = get_event(ctx["event"]["id"])
    assert event["confirmed_seat_count"] == 2, event["confirmed_seat_count"]


def test_pay_deposit_wrong_amount_rejected(api):
    """PRD §3.5: "which must exactly equal the booking's deposit_due_cents; any other amount is
    rejected with ERR_DEPOSIT_AMOUNT_MISMATCH".

    Design: Corner/errors/error_deposit_amount_mismatch_triggerable
    """
    _ctx, guest, booking = provision_pending_booking(seat_count=1)
    res = api.pay_deposit(booking["id"], {"amount_cents": 9999}, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH")


# ─── Corner: validations / booking guards ──────────────────────────────

def test_booking_missing_seat_ids_returns_validation(api):
    """PRD §2.10: "Well-formedness — required fields present, enum values legal, types correct,
    else ERR_VALIDATION (422)."

    Design: Corner/entities/create_booking_missing_seat_ids_returns_422
    """
    ctx = provision_open_event(event_overrides={"seat_capacity": 1})
    guest = create_guest()
    payload = {"event_id": ctx["event"]["id"], "guest_id": guest["id"], "party_size": 1}
    res = api.create_booking(payload, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_VALIDATION")


def test_booking_party_size_mismatch_returns_error(api):
    """PRD §3.5: "The party_size must equal the number of entries in seat_ids, or the request
    fails with ERR_SEAT_COUNT_MISMATCH."

    Design: Corner/validations/booking_party_size_mismatch_returns_422
    """
    ctx = provision_open_event(event_overrides={"seat_capacity": 2})
    guest = create_guest()
    payload = create_booking_payload(ctx["event"]["id"], guest["id"],
                                     [ctx["seats"][0]["id"]], party_size=2)
    res = api.create_booking(payload, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_SEAT_COUNT_MISMATCH")


def test_booking_byob_on_non_byob_event_rejected(api):
    """PRD §3.5: "If byob_bottles is greater than 0, the event's byob_allowed must be true,
    otherwise the request fails with ERR_BYOB_NOT_ALLOWED."

    Design: Corner/validations/booking_byob_on_non_byob_event_returns_422
    """
    ctx = provision_open_event(event_overrides={"seat_capacity": 1})  # byob_allowed default false
    guest = create_guest()
    payload = create_booking_payload(ctx["event"]["id"], guest["id"],
                                     [ctx["seats"][0]["id"]], party_size=1, byob_bottles=1)
    res = api.create_booking(payload, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_BYOB_NOT_ALLOWED")


def test_booking_nut_allergy_against_nuts_menu_rejected(api):
    """PRD §3.5: "a booking whose dietary_restrictions include NUT_ALLERGY may not be placed
    against an event any of whose menu courses lists NUTS in contains_allergens; such a conflict
    is rejected with ERR_ALLERGEN_CONFLICT."

    Design: Corner/validations/booking_allergen_conflict_returns_409
    """
    ctx = provision_open_event(menu_allergens=["NUTS"], event_overrides={"seat_capacity": 1})
    guest = create_guest()
    payload = create_booking_payload(ctx["event"]["id"], guest["id"],
                                     [ctx["seats"][0]["id"]], party_size=1,
                                     dietary_restrictions=["NUT_ALLERGY"])
    res = api.create_booking(payload, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_ALLERGEN_CONFLICT")


def test_booking_seat_from_other_event_rejected(api):
    """PRD §3.5: "Every seat listed in seat_ids must have an event_id equal to the target event,
    or the request fails with ERR_SEAT_NOT_IN_EVENT".

    Design: Corner/validations/booking_seat_from_other_event_returns_422
    """
    ctx_a = provision_open_event(event_overrides={"seat_capacity": 1})
    ctx_b = provision_open_event(event_overrides={
        "seat_capacity": 1, "event_start": "2026-03-16T18:00:00Z",
        "event_end": "2026-03-16T21:00:00Z", "booking_deadline": "2026-03-15T00:00:00Z"})
    guest = create_guest()
    seat_b = ctx_b["seats"][0]["id"]
    payload = create_booking_payload(ctx_a["event"]["id"], guest["id"], [seat_b], party_size=1)
    res = api.create_booking(payload, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_SEAT_NOT_IN_EVENT")


# ─── Difficulty: cross_entity_state_dependency / booking requires OPEN ─

def test_booking_on_scheduled_event_rejected(api):
    """PRD §3.5: "Creating a booking is only legal when the event is OPEN; against any other
    status the attempt fails with ERR_EVENT_NOT_OPEN."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_event_open
    """
    ctx = provision_scheduled_event(event_overrides={"seat_capacity": 1})  # seats exist, not OPEN
    guest = create_guest()
    payload = create_booking_payload(ctx["event"]["id"], guest["id"],
                                     [ctx["seats"][0]["id"]], party_size=1)
    res = api.create_booking(payload, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_EVENT_NOT_OPEN")


def test_booking_on_suspended_event_rejected(api):
    """PRD §3.4: "While an event is SUSPENDED, new booking attempts against it are rejected with
    ERR_EVENT_NOT_OPEN, exactly as they would be for any non-open status."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_event_open
    """
    ctx = provision_open_event(event_overrides={"seat_capacity": 1})
    validate_success(api.suspend_event(ctx["event"]["id"], ADMIN), 200)
    guest = create_guest()
    payload = create_booking_payload(ctx["event"]["id"], guest["id"],
                                     [ctx["seats"][0]["id"]], party_size=1)
    res = api.create_booking(payload, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_EVENT_NOT_OPEN")


# ─── Difficulty: priority_pair_validation_conflict / temporal beats constraint ─

def test_past_deadline_beats_seat_unavailable(api):
    """PRD §2.10: "A lower-numbered tier always decides the outcome before a higher-numbered one
    is consulted; for example, a mid-flight allergen conflict (tier 6) surfaces before a
    seat-availability failure (tier 9) on the same booking request."
    PRD §3.5: "The current logical-clock time must be at or before the event's booking_deadline;
    a later request fails with ERR_PAST_BOOKING_DEADLINE."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_booking
    """
    ctx = provision_open_event(event_overrides={
        "seat_capacity": 2, "event_start": "2026-03-15T18:00:00Z",
        "event_end": "2026-03-15T21:00:00Z", "booking_deadline": "2026-03-10T00:00:00Z"})
    g1 = create_guest(email="g1@x.com")
    seat0 = ctx["seats"][0]["id"]
    b1 = book_seats(ctx["event"]["id"], g1["id"], [seat0], party_size=1)
    pay_deposit(b1["id"], g1["id"], b1["deposit_due_cents"])  # seat0 now BOOKED (unavailable)
    set_clock("2026-03-12T00:00:00Z")  # past deadline 03-10, before event_start
    g2 = create_guest(email="g2@x.com")
    payload = create_booking_payload(ctx["event"]["id"], g2["id"], [seat0], party_size=1)
    res = api.create_booking(payload, make_guest_headers(g2["id"]))
    validate_error(res, "ERR_PAST_BOOKING_DEADLINE")


def test_past_deadline_fires_even_with_available_seat(api):
    """PRD §3.5: "The current logical-clock time must be at or before the event's booking_deadline;
    a later request fails with ERR_PAST_BOOKING_DEADLINE."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_booking
    """
    ctx = provision_open_event(event_overrides={
        "seat_capacity": 2, "event_start": "2026-03-15T18:00:00Z",
        "event_end": "2026-03-15T21:00:00Z", "booking_deadline": "2026-03-10T00:00:00Z"})
    set_clock("2026-03-12T00:00:00Z")  # past deadline
    guest = create_guest()
    seat_free = ctx["seats"][1]["id"]  # still AVAILABLE
    payload = create_booking_payload(ctx["event"]["id"], guest["id"], [seat_free], party_size=1)
    res = api.create_booking(payload, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_PAST_BOOKING_DEADLINE")


# ─── Difficulty: priority_pair_validation_conflict / state beats fiscal ─

def test_invalid_booking_state_beats_deposit_mismatch(api):
    """PRD §3.5: "any other amount is rejected with ERR_DEPOSIT_AMOUNT_MISMATCH, and attempting
    to pay a booking that is not currently PENDING_DEPOSIT is rejected with
    ERR_INVALID_BOOKING_STATE."
    PRD §2.10: "A lower-numbered tier always decides the outcome before a higher-numbered one is
    consulted".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay_deposit
    """
    _ctx, guest, booking = provision_confirmed_booking(seat_count=1)  # already CONFIRMED
    # Wrong amount AND wrong state: state (tier 5) must win over fiscal (tier 10).
    res = api.pay_deposit(booking["id"], {"amount_cents": 9999}, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_INVALID_BOOKING_STATE")


def test_state_check_wins_even_with_correct_amount(api):
    """PRD §3.5: "attempting to pay a booking that is not currently PENDING_DEPOSIT is rejected
    with ERR_INVALID_BOOKING_STATE."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay_deposit
    """
    _ctx, guest, booking = provision_confirmed_booking(seat_count=1)
    # Even a fiscally-correct re-payment is rejected on the state check for a CONFIRMED booking.
    correct = booking["deposit_due_cents"]
    res = api.pay_deposit(booking["id"], {"amount_cents": correct}, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_INVALID_BOOKING_STATE")
