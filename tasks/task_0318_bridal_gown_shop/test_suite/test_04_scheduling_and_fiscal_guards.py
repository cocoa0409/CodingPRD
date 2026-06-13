"""Stylist double-booking buffer, fitting-room capacity overlap, fiscal boundaries
(overpayment, deposit floor), and validation-priority conflicts.

Covers difficulty rules resource_temporal_overlap, boundary_precision_check, and
priority_pair_validation_conflict, plus the corner validations section.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_stylist, create_fitting_room, create_booked_appointment, create_held_booking,
    create_draft_order, create_received_order, create_locked_party,
)
from test_helpers.fixtures import CONSULTANT, MANAGER, CLERK, SEAMSTRESS, get_plan


# ─── resource_temporal_overlap / stylist_buffered_overlap_rejected ───────────

def test_stylist_buffered_overlap_rejected(api):
    """PRD §3.2: "A candidate appointment must not overlap any other non-terminal
    appointment on the same stylist once each existing appointment is extended on its end
    side by that stylist's `turnaround_buffer_minutes`." With a 15-min buffer, an existing
    [10:00,11:00) blocks a start at 11:10 (inside 11:00+15=11:15).

    Design: Difficulty/resource_temporal_overlap/stylist_buffered_overlap_rejected
    """
    stylist = create_stylist(full_name="Pia", turnaround_buffer_minutes=15)
    create_booked_appointment(
        stylist["id"], appointment_type="CONSULTATION",
        start_at="2026-07-05T10:00:00.000Z", end_at="2026-07-05T11:00:00.000Z")
    res = api.create_appointment(
        {"stylist_id": stylist["id"], "appointment_type": "CONSULTATION",
         "start_at": "2026-07-05T11:10:00.000Z", "end_at": "2026-07-05T12:00:00.000Z"},
        CONSULTANT)
    validate_error(res, ApiErrorId.ERR_STYLIST_DOUBLE_BOOKED.value)


def test_stylist_booking_after_full_buffer_succeeds(api):
    """PRD §3.2: "back-to-back bookings are only legal once the full buffer has elapsed
    after the earlier appointment's `end_at`." With a 15-min buffer and existing
    [10:00,11:00), a candidate starting at 11:15 is past the buffer and succeeds.

    Design: Difficulty/resource_temporal_overlap/stylist_buffered_overlap_rejected
    """
    stylist = create_stylist(full_name="Pia", turnaround_buffer_minutes=15)
    create_booked_appointment(
        stylist["id"], appointment_type="CONSULTATION",
        start_at="2026-07-05T10:00:00.000Z", end_at="2026-07-05T11:00:00.000Z")
    res = api.create_appointment(
        {"stylist_id": stylist["id"], "appointment_type": "CONSULTATION",
         "start_at": "2026-07-05T11:15:00.000Z", "end_at": "2026-07-05T12:00:00.000Z"},
        CONSULTANT)
    appt2 = validate_success(res, 201)
    assert appt2["status"] == "BOOKED"


# ─── resource_temporal_overlap / fitting_room_aggregate_capacity_half_open ───

def test_fitting_room_aggregate_overbooking_rejected(api):
    """PRD §3.2: "at each such instant, sum the `party_size` of all `HELD` bookings on the
    same room whose own `[slot_start_at, slot_end_at)` interval contains that instant. The
    peak of that running sum across the candidate's interval, plus the candidate's own
    `party_size`, must not exceed the room's `capacity`." Two party_size-2 bookings
    overlapping in a capacity-3 room (sum 4 > 3) are rejected.

    Design: Difficulty/resource_temporal_overlap/fitting_room_aggregate_capacity_half_open
    """
    room = create_fitting_room(room_label="Suite D", capacity=3)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-06T15:00:00.000Z", end_at="2026-07-06T16:00:00.000Z")
    create_held_booking(
        room["id"], appt["id"], party_size=2,
        slot_start_at="2026-07-06T15:00:00.000Z", slot_end_at="2026-07-06T16:00:00.000Z")
    res = api.create_fitting_room_booking(
        {"appointment_id": appt["id"], "fitting_room_id": room["id"], "party_size": 2,
         "slot_start_at": "2026-07-06T15:30:00.000Z", "slot_end_at": "2026-07-06T16:30:00.000Z"},
        CONSULTANT)
    validate_error(res, ApiErrorId.ERR_FITTING_ROOM_OVERBOOKED.value)


def test_fitting_room_adjacent_intervals_do_not_conflict(api):
    """PRD §3.2: "The intervals are half-open, so adjacency does not conflict: a booking
    ending exactly when another begins does not overlap it". Two party_size-2 bookings in
    a capacity-3 room over adjacent (gap=0) intervals both succeed.

    Design: Difficulty/resource_temporal_overlap/fitting_room_aggregate_capacity_half_open
    """
    room = create_fitting_room(room_label="Suite D", capacity=3)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-06T15:00:00.000Z", end_at="2026-07-06T17:00:00.000Z")
    create_held_booking(
        room["id"], appt["id"], party_size=2,
        slot_start_at="2026-07-06T15:00:00.000Z", slot_end_at="2026-07-06T16:00:00.000Z")
    res = api.create_fitting_room_booking(
        {"appointment_id": appt["id"], "fitting_room_id": room["id"], "party_size": 2,
         "slot_start_at": "2026-07-06T16:00:00.000Z", "slot_end_at": "2026-07-06T17:00:00.000Z"},
        CONSULTANT)
    second = validate_success(res, 201)
    assert second["status"] == "HELD"


# ─── boundary_precision_check / overpayment_boundary_exact_vs_over ───────────

def test_payment_exact_to_balance_succeeds(api):
    """PRD §3.7: "An overpayment guard protects the ledger: a payment whose `amount_cents`
    would drive `amount_paid_cents` strictly above `plan_total_cents` is rejected with
    `ERR_OVERPAYMENT`." A second payment of exactly the remaining 145000 lands paid at
    plan_total 290000 and is accepted (not strictly above).

    Design: Difficulty/boundary_precision_check/overpayment_boundary_exact_vs_over
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    plan = validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 5, "deposit_cents": 145000}, CLERK), 201)
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 145000, "expected_plan_version": plan["version"]}, CLERK), 201)
    fresh = get_plan(plan["id"])
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 145000, "expected_plan_version": fresh["version"]}, CLERK), 201)

    final = get_plan(plan["id"])
    assert final["amount_paid_cents"] == 290000
    assert final["balance_due_cents"] == 0


def test_payment_one_cent_over_balance_rejected(api):
    """PRD §3.7: "a payment whose `amount_cents` would drive `amount_paid_cents` strictly
    above `plan_total_cents` is rejected with `ERR_OVERPAYMENT`." With 145000 already paid
    on a 290000 plan, a 145001 payment crosses the line and is rejected; ledger unchanged.

    Design: Difficulty/boundary_precision_check/overpayment_boundary_exact_vs_over
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    plan = validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 5, "deposit_cents": 145000}, CLERK), 201)
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 145000, "expected_plan_version": plan["version"]}, CLERK), 201)
    fresh = get_plan(plan["id"])

    res = api.post_payment(
        plan["id"], {"amount_cents": 145001, "expected_plan_version": fresh["version"]}, CLERK)
    validate_error(res, ApiErrorId.ERR_OVERPAYMENT.value)
    after = get_plan(plan["id"])
    assert after["amount_paid_cents"] == 145000


# ─── boundary_precision_check / room_capacity_zero_headroom_empty_set_edge ───

def test_zero_headroom_room_rejects_party_size_one(api):
    """PRD §3.2: the running sum of `HELD` party_size "plus the candidate's own
    `party_size`, must not exceed the room's `capacity`." With a HELD party_size-2 booking
    filling a capacity-2 room, even a party_size-1 candidate overlapping it is rejected.

    Design: Difficulty/boundary_precision_check/room_capacity_zero_headroom_empty_set_edge
    """
    room = create_fitting_room(room_label="Suite C", capacity=2)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-04T15:00:00.000Z", end_at="2026-07-04T16:00:00.000Z")
    create_held_booking(
        room["id"], appt["id"], party_size=2,
        slot_start_at="2026-07-04T15:00:00.000Z", slot_end_at="2026-07-04T16:00:00.000Z")
    res = api.create_fitting_room_booking(
        {"appointment_id": appt["id"], "fitting_room_id": room["id"], "party_size": 1,
         "slot_start_at": "2026-07-04T15:30:00.000Z", "slot_end_at": "2026-07-04T15:45:00.000Z"},
        CONSULTANT)
    validate_error(res, ApiErrorId.ERR_FITTING_ROOM_OVERBOOKED.value)


def test_zero_headroom_room_accepts_non_overlapping_slot(api):
    """PRD §3.2: "a booking ending exactly when another begins does not overlap it". With a
    HELD [15:00,16:00) party_size-2 booking filling a capacity-2 room, a party_size-2
    candidate over the adjacent [16:00,16:30) interval has zero overlap and succeeds.

    Design: Difficulty/boundary_precision_check/room_capacity_zero_headroom_empty_set_edge
    """
    room = create_fitting_room(room_label="Suite C", capacity=2)
    appt, _ = create_booked_appointment(
        appointment_type="FITTING",
        start_at="2026-07-04T15:00:00.000Z", end_at="2026-07-04T17:00:00.000Z")
    create_held_booking(
        room["id"], appt["id"], party_size=2,
        slot_start_at="2026-07-04T15:00:00.000Z", slot_end_at="2026-07-04T16:00:00.000Z")
    res = api.create_fitting_room_booking(
        {"appointment_id": appt["id"], "fitting_room_id": room["id"], "party_size": 2,
         "slot_start_at": "2026-07-04T16:00:00.000Z", "slot_end_at": "2026-07-04T16:30:00.000Z"},
        CONSULTANT)
    second = validate_success(res, 201)
    assert second["status"] == "HELD"


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_pickup ────────

def test_state_check_beats_fiscal_on_pickup(api):
    """PRD §2.8: the pipeline runs "(5) state legality of the targeted transition; (6)
    cross-entity referential preconditions; and then the domain-specific temporal,
    capacity, fiscal, and safety rules". A RECEIVED (not READY) unpaid order on pickup
    fails the state check first, returning ERR_ORDER_NOT_READY, not the fiscal balance error.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pickup
    """
    order, plan = create_received_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60}, plan_overrides={"term_installments": 2, "deposit_cents": 90000})
    res = api.pickup_gown_order(order["id"], {"final_steam_done": True}, CONSULTANT)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_READY.value)


def test_state_check_beats_fiscal_status_409(api):
    """PRD §2.8: state legality (step 5) is screened before the domain-specific fiscal
    rules. PRD §3.4: pickup on an order that is not READY returns `ERR_ORDER_NOT_READY`
    (HTTP 409), masking the later balance guard.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pickup
    """
    order, plan = create_received_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60}, plan_overrides={"term_installments": 2, "deposit_cents": 90000})
    res = api.pickup_gown_order(order["id"], {"final_steam_done": True}, CONSULTANT)
    assert res.status_code == 409
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_READY.value, expected_status=409)


# ─ priority_pair_validation_conflict / temporal_beats_referential_on_party_appointment ─

def test_existence_beats_temporal_on_appointment(api):
    """PRD §2.8: "The order is: ... (3) existence resolution; (4) request-body
    well-formedness ... and then the domain-specific temporal ... rules". A booking that
    BOTH names a non-existent bridal_party_id AND double-books the stylist fails the
    earlier existence check, returning ERR_PARTY_NOT_FOUND.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_party_appointment
    """
    stylist = create_stylist(full_name="Mara")
    create_booked_appointment(
        stylist["id"], appointment_type="CONSULTATION",
        start_at="2026-07-03T15:00:00.000Z", end_at="2026-07-03T16:00:00.000Z")
    res = api.create_appointment(
        {"stylist_id": stylist["id"], "appointment_type": "CONSULTATION",
         "start_at": "2026-07-03T15:30:00.000Z", "end_at": "2026-07-03T16:30:00.000Z",
         "bridal_party_id": "00000000-0000-4000-8000-000000000000"},
        CONSULTANT)
    validate_error(res, ApiErrorId.ERR_PARTY_NOT_FOUND.value)


def test_existence_beats_temporal_status_404(api):
    """PRD §2.8: "Existence resolution (step 3) walks the path identifier first and then
    the body's foreign keys in their declaration order ... and rejects on the first
    identifier that does not resolve to an existing row." The bogus party FK yields a 404
    ERR_PARTY_NOT_FOUND even though the stylist overlap (a later temporal rule) also fails.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_party_appointment
    """
    stylist = create_stylist(full_name="Mara")
    create_booked_appointment(
        stylist["id"], appointment_type="CONSULTATION",
        start_at="2026-07-03T15:00:00.000Z", end_at="2026-07-03T16:00:00.000Z")
    res = api.create_appointment(
        {"stylist_id": stylist["id"], "appointment_type": "CONSULTATION",
         "start_at": "2026-07-03T15:30:00.000Z", "end_at": "2026-07-03T16:30:00.000Z",
         "bridal_party_id": "00000000-0000-4000-8000-000000000000"},
        CONSULTANT)
    assert res.status_code == 404
    validate_error(res, ApiErrorId.ERR_PARTY_NOT_FOUND.value, expected_status=404)


# ─── Corner: validations ─────────────────────────────────────────────────────

def test_deposit_below_floor_rejected(api):
    """PRD §3.6: "The minimum acceptable deposit is fifty percent of `plan_total_cents`,
    rounded up to the next whole cent. The supplied `deposit_cents` must be at least that
    floor; a deposit below the floor is rejected with `ERR_DEPOSIT_BELOW_FLOOR`." On a
    290000 plan the floor is 145000, so 144999 is rejected.

    Design: Corner/validations/deposit_below_floor_rejected
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    res = api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 5, "deposit_cents": 144999}, CLERK)
    validate_error(res, ApiErrorId.ERR_DEPOSIT_BELOW_FLOOR.value)


def test_create_order_on_locked_party_rejected(api):
    """PRD §3.3: "If a `bridal_party_id` is supplied, that party must be `FORMING` (a
    `LOCKED` party rejects the new membership with `ERR_PARTY_NOT_FORMING`)".

    Design: Corner/validations/add_party_member_when_locked_rejected
    """
    party = create_locked_party(party_name="Locked Wedding", event_date="2026-09-01T00:00:00.000Z")
    res = api.create_gown_order(
        {"gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
         "standard_lead_days": 60, "bridal_party_id": party["id"]},
        CONSULTANT)
    validate_error(res, ApiErrorId.ERR_PARTY_NOT_FORMING.value)


def test_appointment_end_not_after_start_rejected(api):
    """PRD §2.8: "any appointment or booking window must have an exclusive end strictly
    after its inclusive start. Any such shape failure is rejected with
    `ERR_INVALID_REQUEST` and HTTP status 422." end_at == start_at is rejected.

    Design: Corner/validations/appointment_end_not_after_start_rejected
    """
    stylist = create_stylist(full_name="Vee")
    res = api.create_appointment(
        {"stylist_id": stylist["id"], "appointment_type": "CONSULTATION",
         "start_at": "2026-07-10T10:00:00.000Z", "end_at": "2026-07-10T10:00:00.000Z"},
        CONSULTANT)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
