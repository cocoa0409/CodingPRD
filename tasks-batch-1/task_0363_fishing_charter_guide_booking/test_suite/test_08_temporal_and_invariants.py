"""Resource temporal-overlap conflicts, conserved-quantity invariants, and
validation-priority conflicts: the buffered slot-window conflict and the
no-buffer captain double-booking, seats_booked and open_slot_count conservation
across a book/cancel and a schedule/cancel, and the state-over-fiscal and
referential-over-safety precedence pairs. Covers the difficulty-design
resource_temporal_overlap, compensating_invariant, and
priority_pair_validation_conflict instances rooted in §2.9, §3.2–§3.8 of the PRD.
"""
from test_helpers import (
    validate_success,
    validate_error,
    make_captain_headers,
    make_customer_headers,
    create_slot_reservation_payload,
    create_booking_payload,
    pin_clock,
    create_marina,
    create_dock_slot,
    create_boat,
    create_captain,
    create_customer,
    create_permit,
    create_charter,
    create_booking,
    pay_deposit,
    reserve_slot,
    assign_captain,
    current_charter_version,
    get_charter,
    setup_scheduled_charter,
    api_client,
)
from test_helpers.fixtures import FLEET_MANAGER, DOCK_MASTER


# ===========================================================================
# Difficulty: resource_temporal_overlap / slot_window_overlap_with_turnaround_buffer
# ===========================================================================

def test_slot_reservation_inside_turnaround_buffer_rejected(api):
    """PRD §3.3: "The marina's `turnaround_buffer_minutes` is applied **after** a
    prior window: the earliest a new window may legitimately open on the same slot
    is the prior window's end plus that buffer. ... A new reservation whose
    `[window_start, window_end)` interval collides with any existing `HELD` or
    `OCCUPIED` reservation on the same slot under this buffered rule is rejected
    with `ERR_SLOT_WINDOW_CONFLICT`."

    Slot held [12:00,16:00); marina turnaround_buffer 30 min. A second window
    opening at 16:15 (inside the 30-min buffer after 16:00) -> ERR_SLOT_WINDOW_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/slot_window_overlap_with_turnaround_buffer
    """
    marina = create_marina(name="Buf Marina", slot_count=1, turnaround_buffer_minutes=30)
    slot = create_dock_slot(marina["id"], slot_label="K1")
    boat_a = create_boat(marina["id"], name="Bufboat A")
    boat_b = create_boat(marina["id"], name="Bufboat B")
    charter_a = create_charter(marina["id"], boat_a["id"],
                               depart_at="2027-02-10T12:00:00Z",
                               return_at="2027-02-10T16:00:00Z")
    reserve_slot(slot["id"], charter_a["id"])
    charter_b = create_charter(marina["id"], boat_b["id"],
                               depart_at="2027-02-10T16:15:00Z",
                               return_at="2027-02-10T20:00:00Z")
    version_b = current_charter_version(charter_b["id"])
    res = api.create_slot_reservation(
        create_slot_reservation_payload(slot["id"], charter_b["id"], version_b),
        DOCK_MASTER,
    )
    validate_error(res, "ERR_SLOT_WINDOW_CONFLICT")


def test_slot_reservation_closed_adjacency_at_prior_window_end_rejected(api):
    """PRD §3.3: "The adjacency is closed — a window that opens exactly at a prior
    window's end, with no buffer cleared, is still a conflict, and so is any
    genuine overlap."

    Slot held [12:00,16:00); a second window opening exactly at 16:00 (the prior
    end, no buffer cleared) -> ERR_SLOT_WINDOW_CONFLICT under the closed-adjacency
    buffered rule.

    Design: Difficulty/resource_temporal_overlap/slot_window_overlap_with_turnaround_buffer
    """
    marina = create_marina(name="Adj Marina", slot_count=1, turnaround_buffer_minutes=30)
    slot = create_dock_slot(marina["id"], slot_label="K2")
    boat_a = create_boat(marina["id"], name="Adjboat A")
    boat_b = create_boat(marina["id"], name="Adjboat B")
    charter_a = create_charter(marina["id"], boat_a["id"],
                               depart_at="2027-02-10T12:00:00Z",
                               return_at="2027-02-10T16:00:00Z")
    reserve_slot(slot["id"], charter_a["id"])
    charter_b = create_charter(marina["id"], boat_b["id"],
                               depart_at="2027-02-10T16:00:00Z",
                               return_at="2027-02-10T20:00:00Z")
    version_b = current_charter_version(charter_b["id"])
    res = api.create_slot_reservation(
        create_slot_reservation_payload(slot["id"], charter_b["id"], version_b),
        DOCK_MASTER,
    )
    validate_error(res, "ERR_SLOT_WINDOW_CONFLICT")


# ===========================================================================
# Difficulty: resource_temporal_overlap / captain_double_booked_half_open_no_buffer
# ===========================================================================

def test_captain_double_booked_on_overlapping_charter_rejected(api):
    """PRD §3.2: "A captain already named on a `TENTATIVE` or `LOCKED` assignment
    whose charter's sailing interval — its half-open window from `depart_at` up to
    but not including `return_at` — strictly overlaps the new charter's interval
    cannot be assigned again; this is rejected with `ERR_CAPTAIN_DOUBLE_BOOKED`."

    Captain assigned to A [12:00,16:00); assigning to B [15:00,18:00) (a strict
    overlap, no buffer) -> ERR_CAPTAIN_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/captain_double_booked_half_open_no_buffer
    """
    marina = create_marina(name="Dbl Marina", slot_count=4)
    boat_a = create_boat(marina["id"], name="Dblboat A")
    boat_b = create_boat(marina["id"], name="Dblboat B")
    captain = create_captain(marina["id"], full_name="Cap Dbl")
    charter_a = create_charter(marina["id"], boat_a["id"],
                               depart_at="2027-03-10T12:00:00Z",
                               return_at="2027-03-10T16:00:00Z")
    charter_b = create_charter(marina["id"], boat_b["id"],
                               depart_at="2027-03-10T15:00:00Z",
                               return_at="2027-03-10T18:00:00Z")
    assign_captain(charter_a["id"], captain["id"])
    res = api.create_crew_assignment(
        {"charter_id": charter_b["id"], "role_slot": "CAPTAIN", "captain_id": captain["id"]},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_CAPTAIN_DOUBLE_BOOKED")


def test_captain_touching_windows_at_shared_endpoint_allowed(api):
    """PRD §3.2: "The overlap test here uses no buffer: two charters whose windows
    merely touch at a shared endpoint (one's `return_at` equal to the other's
    `depart_at`) do not overlap and are permitted."

    Captain assigned to A [12:00,16:00); assigning to B [16:00,18:00) (touching at
    16:00, half-open, no overlap) is permitted (201).

    Design: Difficulty/resource_temporal_overlap/captain_double_booked_half_open_no_buffer
    """
    marina = create_marina(name="Touch Marina", slot_count=4)
    boat_a = create_boat(marina["id"], name="Touchboat A")
    boat_b = create_boat(marina["id"], name="Touchboat B")
    captain = create_captain(marina["id"], full_name="Cap Touch")
    charter_a = create_charter(marina["id"], boat_a["id"],
                               depart_at="2027-03-10T12:00:00Z",
                               return_at="2027-03-10T16:00:00Z")
    charter_b = create_charter(marina["id"], boat_b["id"],
                               depart_at="2027-03-10T16:00:00Z",
                               return_at="2027-03-10T18:00:00Z")
    assign_captain(charter_a["id"], captain["id"])
    res = api.create_crew_assignment(
        {"charter_id": charter_b["id"], "role_slot": "CAPTAIN", "captain_id": captain["id"]},
        FLEET_MANAGER,
    )
    assignment = validate_success(res, expected_status=201)
    assert assignment["status"] == "TENTATIVE", assignment["status"]


# ===========================================================================
# Difficulty: compensating_invariant / seats_booked_conserved_on_book_then_cancel
# ===========================================================================

def test_seats_booked_returns_to_zero_after_book_then_cancel(api):
    """PRD §3.4: "On success, the charter's `seats_booked` is increased by
    `party_size`."
    PRD §3.8: "Cancelling a booking computes its `refund_cents`, decrements the
    charter's `seats_booked` by the booking's `party_size`."

    Book (+2) then cancel (-2) leaves seats_booked exactly at its pre-create value
    0 — the conserved quantity has zero drift.

    Design: Difficulty/compensating_invariant/seats_booked_conserved_on_book_then_cancel
    """
    marina = create_marina(name="Seat Marina")
    boat = create_boat(marina["id"], name="Seatboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], seats_total=6)
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    api.cancel_booking(booking["id"], make_customer_headers(customer["id"]))
    fresh = get_charter(charter["id"])
    assert fresh["seats_booked"] == 0, fresh["seats_booked"]


def test_booking_cancelled_after_book_then_cancel(api):
    """PRD §3.8: "A `Customer` (or `FleetManager`) may also cancel a single
    **Booking** directly, from either `RESERVED` or `CONFIRMED` to `CANCELLED`."

    The cancelled booking that conserves the seat count itself moves to CANCELLED.

    Design: Difficulty/compensating_invariant/seats_booked_conserved_on_book_then_cancel
    """
    marina = create_marina(name="Seat Marina 2")
    boat = create_boat(marina["id"], name="Seatboat2")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], seats_total=6)
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    res = api.cancel_booking(booking["id"], make_customer_headers(customer["id"]))
    cancelled = validate_success(res, expected_status=200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]


# ===========================================================================
# Difficulty: compensating_invariant / slot_occupancy_conserved_on_schedule_then_cancel
# ===========================================================================

def test_open_slot_count_restored_after_schedule_then_cancel(api):
    """PRD §3.7: "scheduling ... converts the charter's slot reservation from
    `HELD` to `OCCUPIED`."
    PRD §3.8: "Cancelling cascades: ... the slot reservation is `RELEASED`."
    PRD §3.6: "The open count is the marina's `slot_count` minus the number of
    distinct busy slots."

    Clock inside the window; schedule occupies the slot, charter cancel releases
    it, restoring open_slot_count to 2 — the slot capacity is conserved with no leak.

    Design: Difficulty/compensating_invariant/slot_occupancy_conserved_on_schedule_then_cancel
    """
    pin_clock("2027-05-10T13:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2027-05-10T12:00:00Z",
                           "return_at": "2027-05-10T16:00:00Z"})
    api.cancel_charter(ctx["charter"]["id"], FLEET_MANAGER)
    fresh = validate_success(api.get_marina(ctx["marina"]["id"], FLEET_MANAGER),
                             expected_status=200)
    assert fresh["open_slot_count"] == 2, fresh["open_slot_count"]


def test_charter_cancelled_after_schedule_then_cancel(api):
    """PRD §3.8: "A charter may be **cancelled** by the `FleetManager` from
    `DRAFT`, `SCHEDULED`, or `WEATHER_HOLD`, moving it to `CANCELLED`."

    The cancel that conserves the slot capacity moves the charter to CANCELLED.

    Design: Difficulty/compensating_invariant/slot_occupancy_conserved_on_schedule_then_cancel
    """
    pin_clock("2027-05-10T13:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2027-05-10T12:00:00Z",
                           "return_at": "2027-05-10T16:00:00Z"})
    res = api.cancel_charter(ctx["charter"]["id"], FLEET_MANAGER)
    cancelled = validate_success(res, expected_status=200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / state_before_fiscal_on_pay_deposit
# ===========================================================================

def test_pay_deposit_state_error_outranks_fiscal_underpayment(api):
    """PRD §2.9: "(5) the target resource is in a state that permits the requested
    transition ... (12) deposit sufficiency on payment (`ERR_DEPOSIT_UNDERPAID`)
    ... Lower-numbered checks always take precedence."
    PRD §3.4: "This is permitted only while the booking is `RESERVED` ... (otherwise
    `ERR_BOOKING_NOT_RESERVED` ...). ... an underpayment is rejected with
    `ERR_DEPOSIT_UNDERPAID`."

    An already-CONFIRMED booking (state p5 fails) paid 100 below deposit_due
    (fiscal p12 fails) returns the state error ERR_BOOKING_NOT_RESERVED.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_pay_deposit
    """
    marina = create_marina(name="Pri Marina")
    boat = create_boat(marina["id"], name="Priboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    pay_deposit(booking["id"], customer["id"], 5000)  # -> CONFIRMED
    res = api.pay_deposit(booking["id"], {"amount_cents": 100},
                          make_customer_headers(customer["id"]))
    validate_error(res, "ERR_BOOKING_NOT_RESERVED")


def test_pay_deposit_on_confirmed_booking_rejects_on_state(api):
    """PRD §3.4: "This is permitted only while the booking is `RESERVED` and its
    charter is still in `DRAFT` or `SCHEDULED` (otherwise `ERR_BOOKING_NOT_RESERVED`
    or `ERR_CHARTER_NOT_BOOKABLE`)."

    Re-paying an already-CONFIRMED booking with a sufficient amount (no fiscal
    failure) still fails on the state precondition with ERR_BOOKING_NOT_RESERVED,
    confirming the state check is the rejection path.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_pay_deposit
    """
    marina = create_marina(name="Pri Marina 2")
    boat = create_boat(marina["id"], name="Priboat2")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    pay_deposit(booking["id"], customer["id"], 5000)  # -> CONFIRMED
    res = api.pay_deposit(booking["id"], {"amount_cents": 5000},
                          make_customer_headers(customer["id"]))
    validate_error(res, "ERR_BOOKING_NOT_RESERVED")


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / referential_before_safety_on_crew_assignment
# ===========================================================================

def test_crew_assignment_referential_error_outranks_safety(api):
    """PRD §2.9: "(6) cross-entity referential wiring is consistent
    (`ERR_CROSS_MARINA_MISMATCH`); (7) credential and capacity safety ... Lower-
    numbered checks always take precedence."
    PRD §3.2: "the captain's and mate's rostered marina ... must all equal the
    charter's `marina_id` ... Any of these mismatches is rejected with
    `ERR_CROSS_MARINA_MISMATCH`."

    A captain at marina Y (cross-marina, referential p6) who is also only OUPV
    (under-graded for OFFSHORE, safety p7) returns the referential error
    ERR_CROSS_MARINA_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/referential_before_safety_on_crew_assignment
    """
    marina_x = create_marina(name="Marina X")
    marina_y = create_marina(name="Marina Y")
    boat = create_boat(marina_x["id"], name="Offboat", length_ft=40,
                       passenger_capacity=8, offshore_rated=True)
    permit = create_permit(permit_number="F-1", daily_bag_limit=20)
    captain_y = create_captain(marina_y["id"], full_name="Cap Y",
                               uscg_license_grade="OUPV")
    charter = create_charter(marina_x["id"], boat["id"], trip_type="OFFSHORE",
                             permit_id=permit["id"], base_seat_price_cents=30000,
                             seats_total=8, depart_at="2026-11-10T06:00:00Z",
                             return_at="2026-11-10T18:00:00Z")
    res = api.create_crew_assignment(
        {"charter_id": charter["id"], "role_slot": "CAPTAIN", "captain_id": captain_y["id"]},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_CROSS_MARINA_MISMATCH")


def test_crew_assignment_cross_marina_captain_rejects_on_referential(api):
    """PRD §3.2: "The boat's home marina, the captain's and mate's rostered marina,
    and the dock slot's owning marina must all equal the charter's `marina_id`
    ... Any of these mismatches is rejected with `ERR_CROSS_MARINA_MISMATCH`."

    A sufficiently-graded captain (MASTER_100) rostered at marina Y assigned to an
    OFFSHORE charter at marina X still fails on the referential wiring with
    ERR_CROSS_MARINA_MISMATCH, confirming the referential check is the rejection path.

    Design: Difficulty/priority_pair_validation_conflict/referential_before_safety_on_crew_assignment
    """
    marina_x = create_marina(name="Marina X2")
    marina_y = create_marina(name="Marina Y2")
    boat = create_boat(marina_x["id"], name="Offboat2", length_ft=40,
                       passenger_capacity=8, offshore_rated=True)
    permit = create_permit(permit_number="F-1b", daily_bag_limit=20)
    captain_y = create_captain(marina_y["id"], full_name="Cap Y2",
                               uscg_license_grade="MASTER_100")
    charter = create_charter(marina_x["id"], boat["id"], trip_type="OFFSHORE",
                             permit_id=permit["id"], base_seat_price_cents=30000,
                             seats_total=8, depart_at="2026-11-10T06:00:00Z",
                             return_at="2026-11-10T18:00:00Z")
    res = api.create_crew_assignment(
        {"charter_id": charter["id"], "role_slot": "CAPTAIN", "captain_id": captain_y["id"]},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_CROSS_MARINA_MISMATCH")
