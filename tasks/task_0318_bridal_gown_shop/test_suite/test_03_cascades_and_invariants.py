"""Multi-hop cancellation cascades, room-capacity conservation, the refund
compensating invariant, and derived-field reconciliation.

Covers difficulty rules transitive_cascade and compensating_invariant, plus the
cross_cutting_complexity_layers cascade / derived-field instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    setup_fitting_job_on_room, create_stylist, create_fitting_room,
    create_booked_appointment, create_held_booking,
    create_cancelled_order_with_deposit, create_draft_order, create_bridal_party,
    create_order_with_plan,
)
from test_helpers.fixtures import CONSULTANT, MANAGER, CLERK, SEAMSTRESS, get_plan


# ─── transitive_cascade / order_cancel_three_hop_cascade_to_room_capacity ────

def test_order_cancel_cascades_job_and_room_booking(api):
    """PRD §3.4: "First, every alteration job on the order that is not already
    `COMPLETED` or `CANCELLED` is moved to `CANCELLED`. Second, for each such
    cascade-cancelled job that holds a `HELD` fitting-room booking on its
    `fitting_room_id`, that booking is moved to `RELEASED`".

    Design: Difficulty/transitive_cascade/order_cancel_three_hop_cascade_to_room_capacity
    """
    order, job, booking, room = setup_fitting_job_on_room(room_capacity=4)
    cancelled = validate_success(api.cancel_gown_order(order["id"], MANAGER), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"

    job_after = validate_success(api.get_alteration_job(job["id"], SEAMSTRESS), 200)
    assert job_after["status"] == "CANCELLED"
    booking_after = validate_success(api.get_fitting_room_booking(booking["id"], CONSULTANT), 200)
    assert booking_after["status"] == "RELEASED"


def test_order_cancel_frees_room_capacity_for_new_booking(api):
    """PRD §3.4: the cascade releases the job's `HELD` booking "which in turn frees the
    room's capacity over the booking interval." After cancel, the formerly-full room
    accepts a fresh full-capacity booking over the same interval.

    Design: Difficulty/transitive_cascade/order_cancel_three_hop_cascade_to_room_capacity
    """
    order, job, booking, room = setup_fitting_job_on_room(room_capacity=4)
    validate_success(api.cancel_gown_order(order["id"], MANAGER), 200)

    # A fresh appointment + full-capacity booking over the same slot now succeeds.
    appt2, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-01T15:00:00.000Z", end_at="2026-07-01T16:00:00.000Z")
    res = api.create_fitting_room_booking(
        {"appointment_id": appt2["id"], "fitting_room_id": room["id"], "party_size": 4,
         "slot_start_at": "2026-07-01T15:00:00.000Z", "slot_end_at": "2026-07-01T16:00:00.000Z"},
        CONSULTANT)
    new_booking = validate_success(res, 201)
    assert new_booking["status"] == "HELD"


# ─ transitive_cascade / appointment_complete_releases_room_capacity_two_hop ──

def test_appointment_complete_releases_held_booking(api):
    """PRD §3.2: "The three terminating transitions — complete, cancel, and mark-no-show
    — share one side effect: every `HELD` fitting-room booking attached to that
    appointment is moved to `RELEASED`, freeing each room's capacity for the booking's
    interval."

    Design: Difficulty/transitive_cascade/appointment_complete_releases_room_capacity_two_hop
    """
    room = create_fitting_room(room_label="Suite B", capacity=2)
    appt, stylist_id = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-02T15:00:00.000Z", end_at="2026-07-02T16:00:00.000Z")
    booking = create_held_booking(
        room["id"], appt["id"], party_size=2,
        slot_start_at="2026-07-02T15:00:00.000Z", slot_end_at="2026-07-02T16:00:00.000Z")
    validate_success(api.check_in_appointment(appt["id"], CONSULTANT), 200)

    validate_success(api.complete_appointment(appt["id"], CONSULTANT), 200)
    booking_after = validate_success(api.get_fitting_room_booking(booking["id"], CONSULTANT), 200)
    assert booking_after["status"] == "RELEASED"


def test_appointment_complete_frees_capacity_for_new_full_booking(api):
    """PRD §3.2: completing an appointment releases its `HELD` bookings "freeing each
    room's capacity for the booking's interval." A new full-capacity booking over the
    freed interval then succeeds.

    Design: Difficulty/transitive_cascade/appointment_complete_releases_room_capacity_two_hop
    """
    room = create_fitting_room(room_label="Suite B", capacity=2)
    appt, stylist_id = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-02T15:00:00.000Z", end_at="2026-07-02T16:00:00.000Z")
    create_held_booking(
        room["id"], appt["id"], party_size=2,
        slot_start_at="2026-07-02T15:00:00.000Z", slot_end_at="2026-07-02T16:00:00.000Z")
    validate_success(api.check_in_appointment(appt["id"], CONSULTANT), 200)
    # Non-overlapping appointment to host the second booking.
    appt2, _ = create_booked_appointment(
        stylist_id, appointment_type="FITTING",
        start_at="2026-07-02T16:30:00.000Z", end_at="2026-07-02T17:30:00.000Z")

    validate_success(api.complete_appointment(appt["id"], CONSULTANT), 200)
    res = api.create_fitting_room_booking(
        {"appointment_id": appt2["id"], "fitting_room_id": room["id"], "party_size": 2,
         "slot_start_at": "2026-07-02T15:00:00.000Z", "slot_end_at": "2026-07-02T16:00:00.000Z"},
        CONSULTANT)
    new_booking = validate_success(res, 201)
    assert new_booking["status"] == "HELD"


# ─── compensating_invariant / refund_restores_payment_ledger_to_zero ─────────

def test_refund_restores_ledger_to_zero(api):
    """PRD §3.7: "The refund posts a single `REFUND` payment whose amount equals the
    plan's current `amount_paid_cents`, flips every prior `SETTLED` payment on the plan
    to `REVERSED`, returns the plan's `amount_paid_cents` to 0 ... and moves the linked
    order's `payment_status` to `REFUNDED`". PRD §3.7: balance_due_cents is
    plan_total_cents minus amount_paid_cents, so it returns to plan_total_cents 290000.

    Design: Difficulty/compensating_invariant/refund_restores_payment_ledger_to_zero
    """
    order, plan = create_cancelled_order_with_deposit(
        order_overrides={"gown_style_code": "ELEGANCE", "ordered_size": 22,
                         "base_price_cents": 200000, "standard_lead_days": 90, "is_rush": True},
        plan_overrides={"term_installments": 5, "deposit_cents": 145000})
    fresh = get_plan(plan["id"])
    validate_success(api.refund_payment_plan(
        plan["id"], {"expected_plan_version": fresh["version"]}, CLERK), 201)

    plan_after = get_plan(plan["id"])
    assert plan_after["amount_paid_cents"] == 0
    assert plan_after["balance_due_cents"] == 290000
    order_after = validate_success(api.get_gown_order(order["id"], MANAGER), 200)
    assert order_after["payment_status"] == "REFUNDED"


def test_refund_reverses_prior_settled_payment(api):
    """PRD §3.7: a refund "flips every prior `SETTLED` payment on the plan to `REVERSED`".
    After the refund the deposit payment is REVERSED and a REFUND payment exists.

    Design: Difficulty/compensating_invariant/refund_restores_payment_ledger_to_zero
    """
    order, plan = create_cancelled_order_with_deposit(
        order_overrides={"gown_style_code": "ELEGANCE", "ordered_size": 22,
                         "base_price_cents": 200000, "standard_lead_days": 90, "is_rush": True},
        plan_overrides={"term_installments": 5, "deposit_cents": 145000})
    fresh = get_plan(plan["id"])
    validate_success(api.refund_payment_plan(
        plan["id"], {"expected_plan_version": fresh["version"]}, CLERK), 201)

    from test_helpers import validate_paginated
    payments, _ = validate_paginated(api.list_payments(plan["id"], CLERK))
    kinds = [p["kind"] for p in payments]
    assert "REFUND" in kinds
    deposit_payments = [p for p in payments if p["kind"] == "DEPOSIT"]
    assert deposit_payments and all(p["settlement_status"] == "REVERSED" for p in deposit_payments)


# ─── compensating_invariant / book_then_release_conserves_room_capacity ──────

def test_release_restores_full_room_headroom(api):
    """PRD §3.2: releasing a booking "returns its `party_size` occupants to the room's
    capacity over the booking interval." After holding 3 and releasing, a fresh
    party_size-4 booking over the same interval succeeds in a capacity-4 room.

    Design: Difficulty/compensating_invariant/book_then_release_conserves_room_capacity
    """
    room = create_fitting_room(room_label="Suite E", capacity=4)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-07T15:00:00.000Z", end_at="2026-07-07T16:00:00.000Z")
    booking = create_held_booking(
        room["id"], appt["id"], party_size=3,
        slot_start_at="2026-07-07T15:00:00.000Z", slot_end_at="2026-07-07T16:00:00.000Z")
    released = validate_success(api.release_fitting_room_booking(booking["id"], CONSULTANT), 200)
    assert released["status"] == "RELEASED"

    res = api.create_fitting_room_booking(
        {"appointment_id": appt["id"], "fitting_room_id": room["id"], "party_size": 4,
         "slot_start_at": "2026-07-07T15:00:00.000Z", "slot_end_at": "2026-07-07T16:00:00.000Z"},
        CONSULTANT)
    new_booking = validate_success(res, 201)
    assert new_booking["status"] == "HELD"


def test_manual_release_marks_booking_released(api):
    """PRD §3.2: "a `BridalConsultant` or `ShopManager` may release a booking, moving
    `HELD -> RELEASED`, which requires the booking to be `HELD` (else
    `ERR_BOOKING_NOT_HELD`) and returns its `party_size` occupants to the room's capacity".

    Design: Difficulty/compensating_invariant/book_then_release_conserves_room_capacity
    """
    room = create_fitting_room(room_label="Suite E", capacity=4)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-07T15:00:00.000Z", end_at="2026-07-07T16:00:00.000Z")
    booking = create_held_booking(
        room["id"], appt["id"], party_size=3,
        slot_start_at="2026-07-07T15:00:00.000Z", slot_end_at="2026-07-07T16:00:00.000Z")
    released = validate_success(api.release_fitting_room_booking(booking["id"], CONSULTANT), 200)
    assert released["status"] == "RELEASED"


# ─── Corner: cross_cutting_complexity_layers (cascade / derived field) ───────

def test_cancel_zero_paid_plan_cascades_to_cancelled(api):
    """PRD §3.4: "Third, the order's payment plan, if its status is not already
    `CANCELLED` and it has taken in no money (`amount_paid_cents` equal to 0), is moved
    to `CANCELLED`." Cancelling a DRAFT order with an unpaid plan cancels the plan.

    Design: Corner/cross_cutting_complexity_layers/cascade_order_cancel_zero_paid_plan_cancelled
    """
    order, plan = create_order_with_plan(
        order_overrides={"gown_style_code": "ATELIER", "ordered_size": 10,
                         "base_price_cents": 180000, "standard_lead_days": 60},
        plan_overrides={"term_installments": 2, "deposit_cents": 90000})
    cancelled = validate_success(api.cancel_gown_order(order["id"], MANAGER), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    plan_after = get_plan(plan["id"])
    assert plan_after["status"] == "CANCELLED"


def test_member_order_count_reconciles_on_cancel(api):
    """PRD §3.1: "The `member_order_count` is a derived figure: it is the number of
    `GownOrder` rows whose `bridal_party_id` points at this party and whose
    `fulfillment_status` is anything other than `CANCELLED`. This count is recomputed and
    re-stamped whenever a linked order is created or cancelled". Two orders give 2;
    cancelling one reconciles to 1.

    Design: Corner/cross_cutting_complexity_layers/derived_member_order_count_reconciles_on_cancel
    """
    party = create_bridal_party(party_name="Count Wedding", event_date="2026-12-15T00:00:00.000Z")
    o1 = create_draft_order(gown_style_code="M1", ordered_size=10, base_price_cents=100000,
                            standard_lead_days=30, bridal_party_id=party["id"])
    o2 = create_draft_order(gown_style_code="M2", ordered_size=12, base_price_cents=120000,
                            standard_lead_days=30, bridal_party_id=party["id"])
    validate_success(api.cancel_gown_order(o2["id"], MANAGER), 200)

    party_after = validate_success(api.get_bridal_party(party["id"], CONSULTANT), 200)
    assert party_after["member_order_count"] == 1, (
        f"member_order_count should reconcile to 1, got {party_after['member_order_count']}"
    )
