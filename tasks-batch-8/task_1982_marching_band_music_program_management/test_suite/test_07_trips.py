"""Trips and enrollments: provisional shares, confirm gate, roster lock gate,
pinned finalize order, refund tiers, waitlist promotion, supersede, OCC, and the
event-cancel cascade."""
from test_helpers import (
    DIRECTOR_HEADERS,
    READER_HEADERS,
    TREASURER_HEADERS,
    ApiErrorId,
    advance_clock,
    confirm_enrollment,
    create_charter,
    create_enrolled_student,
    create_event,
    create_open_program,
    create_trip,
    create_trip_enrollment_payload,
    enroll_in_trip,
    get_event,
    get_student,
    get_trip,
    get_trip_enrollment,
    mark_attendance_payload,
    post_payment,
    setup_finalized_trip,
    setup_locked_trip,
    setup_trip_with_open_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = DIRECTOR_HEADERS
READER = READER_HEADERS
TREASURER_H = TREASURER_HEADERS


# --- Corner: provisional shares, duplicate, waitlist, refund tiers --------------

def test_provisional_share_snapshots_per_enrollment(api, reader_headers):
    """PRD §3.6: "An enrollment that lands a seat starts `REGISTERED` with `payment_status` `UNPAID`; its provisional share is the trip's `estimated_cost_cents` divided by the roster count including this new enrollment, rounded half up to integer cents, and `amount_due_cents` mirrors the provisional share until finalization replaces it." PRD §3.6: "For contrast, the provisional share assigned at enrollment time is the trip's `estimated_cost_cents` divided by the roster count, so an estimated 90000 cents over seven registered students yields a provisional 12857 cents, while a finalized actual of 100000 cents with a 20000-cent pool (the cap of 25000 does not bind) over seven confirmed students yields a final 11429 cents."

    Design: Corner/calculations/trip_provisional_share_snapshot_per_enrollment
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=10, estimated_cost_cents=90000,
        departure_at="2026-09-15T06:00:00Z")
    students = [create_enrolled_student(program["id"], full_name=f"P{i}",
                                        grade=9, section="BRASS")
                for i in range(3)]
    enrollments = [enroll_in_trip(trip["id"], s["id"]) for s in students]

    assert enrollments[0]["provisional_share_cents"] == 90000
    assert enrollments[1]["provisional_share_cents"] == 45000
    assert enrollments[2]["provisional_share_cents"] == 30000

    # Snapshots are fixed at creation; re-reads after the roster grew agree.
    reread = [get_trip_enrollment(e["id"]) for e in enrollments]
    assert [e["provisional_share_cents"] for e in reread] == [90000, 45000, 30000]
    assert [e["amount_due_cents"] for e in reread] == [90000, 45000, 30000]
    assert all(e["payment_status"] == "UNPAID" for e in reread)
    _ = reader_headers


def test_duplicate_enrollment_rejected(api, reader_headers):
    """PRD §3.6: "The student must be `ENROLLED` else `ERR_STUDENT_NOT_ENROLLED`, must not be delinquent else `ERR_STUDENT_DELINQUENT_FEES`, and must not already hold a non-terminal enrollment for the same trip, else `ERR_ENROLLMENT_DUPLICATE`."

    Design: Corner/errors/duplicate_trip_enrollment_rejected
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=5000)
    student = create_enrolled_student(program["id"], full_name="DE")
    enroll_in_trip(trip["id"], student["id"])

    dup = api.create_trip_enrollment(
        create_trip_enrollment_payload(trip["id"], student["id"]), DIRECTOR)
    validate_error(dup, ApiErrorId.ERR_ENROLLMENT_DUPLICATE)

    _rows, meta = validate_paginated(api.list_trip_enrollments(
        reader_headers, params={"trip_id": trip["id"]}))
    assert meta["total_count"] == 1


def test_waitlist_promotion_on_excuse(api, reader_headers):
    """PRD §3.6: "Capacity is inclusive: enrollments whose `attendance_status` is `REGISTERED` or `CONFIRMED` may number up to exactly the trip's `capacity`, and an enrollment created when the count already equals capacity lands with `attendance_status` `WAITLISTED` and both `provisional_share_cents` and `amount_due_cents` set to zero." PRD §3.6: "Excusing frees the seat, which fires the waitlist: among the trip's `WAITLISTED` enrollments, the one with the earliest `created_at` — never any identifier ordering — is promoted to `REGISTERED` exactly when the roster count after the freeing is below capacity, and the promoted enrollment's `provisional_share_cents` is recomputed as the trip's `estimated_cost_cents` divided by the new roster count, rounded half up, with `amount_due_cents` following it."

    Design: Corner/state_machines/waitlist_promotion_on_excuse
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=1, estimated_cost_cents=8000,
        departure_at="2026-09-15T06:00:00Z")
    student_a = create_enrolled_student(program["id"], full_name="WA")
    student_b = create_enrolled_student(program["id"], full_name="WB")
    enrollment_a = enroll_in_trip(trip["id"], student_a["id"])
    enrollment_b = enroll_in_trip(trip["id"], student_b["id"])
    assert enrollment_a["attendance_status"] == "REGISTERED"
    assert enrollment_b["attendance_status"] == "WAITLISTED"
    assert enrollment_b["provisional_share_cents"] == 0
    assert enrollment_b["amount_due_cents"] == 0

    excused = validate_success(api.excuse_trip_enrollment(enrollment_a["id"],
                                                          DIRECTOR))
    assert excused["attendance_status"] == "EXCUSED"

    promoted = validate_success(api.get_trip_enrollment(enrollment_b["id"],
                                                        reader_headers))
    assert promoted["attendance_status"] == "REGISTERED"
    assert promoted["provisional_share_cents"] == 8000, (
        "sole registrant after the freeing: estimated 8000 over a count of 1")
    assert promoted["amount_due_cents"] == 8000


def test_refund_tier_boundary_exactly_fourteen_days(api, director_headers):
    """PRD §3.6: "The refund percentage keys off the whole days between now and the trip's `departure_at` (any partial day discarded): at least 14 days out, the full net paid amount is refunded; from 7 up to but not including 14 days, half; under 7 days, nothing." PRD §3.6: "Boundary cases are exact: exactly 14 days to departure refunds 100 percent, and exactly 7 days refunds 50 percent."

    Design: Corner/calculations/refund_tier_boundary_exactly_14_days
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=10000,
        departure_at="2026-08-15T00:00:00Z",
        event_overrides={"starts_at": "2026-08-15T15:00:00Z",
                         "ends_at": "2026-08-15T21:00:00Z"})
    student_a = create_enrolled_student(program["id"], full_name="RA")
    student_b = create_enrolled_student(program["id"], full_name="RB")
    enrollment_a = enroll_in_trip(trip["id"], student_a["id"])
    enrollment_b = enroll_in_trip(trip["id"], student_b["id"])
    post_payment(student_a["id"], "PAYMENT", 10000,
                 trip_enrollment_id=enrollment_a["id"])
    post_payment(student_b["id"], "PAYMENT", 10000,
                 trip_enrollment_id=enrollment_b["id"])

    # Clock default 2026-08-01T00:00:00Z is exactly 14 days before departure.
    validate_success(api.excuse_trip_enrollment(enrollment_a["id"],
                                                director_headers))
    enrollment_a = get_trip_enrollment(enrollment_a["id"])
    assert enrollment_a["refunded_cents"] == 10000, "14 days: 100 percent tier"
    assert enrollment_a["payment_status"] == "REFUNDED"

    advance_clock("2026-08-02T00:00:00Z")  # 13 whole days to departure
    validate_success(api.excuse_trip_enrollment(enrollment_b["id"],
                                                director_headers))
    enrollment_b = get_trip_enrollment(enrollment_b["id"])
    assert enrollment_b["refunded_cents"] == 5000, (
        "13 days: 50 percent tier, round_half_up(10000 * 0.5)")
    # enrollment_b's amount_due_cents is its provisional share: PRD §3.6 pins
    # "estimated_cost_cents divided by the roster count including this new
    # enrollment" -> 10000 / 2 = 5000. After the half refund net_paid_cents is
    # 5000, which is still at least amount_due 5000, so §3.6's payment_status
    # definition yields PAID; a partial refund is not a full-refund path, so
    # REFUNDED does not apply.
    assert enrollment_b["payment_status"] == "PAID"


# --- Difficulty: trip_enrollment_parallel_state_dimensions -----------------------

def test_payment_dimension_moves_independently_of_attendance(
        api, director_headers, reader_headers):
    """PRD §3.6: "`payment_status` reads `UNPAID` when `net_paid_cents` is zero, `PAID` when `net_paid_cents` is at least `amount_due_cents` and `amount_due_cents` is positive, and `PARTIAL` otherwise; `REFUNDED` is set only by the full-refund paths of excuse and trip cancellation." PRD §3.6: "it requires the trip in `ROSTER_OPEN` or `ROSTER_LOCKED` (else `ERR_TRIP_ROSTER_NOT_OPEN`), the enrollment in `REGISTERED` (else `ERR_ENROLLMENT_NOT_CONFIRMABLE`), and `payment_status` exactly `PAID` (else `ERR_ENROLLMENT_NOT_PAID`)."

    Design: Difficulty/non_linear_state_machine/trip_enrollment_parallel_state_dimensions
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=10000,
        departure_at="2026-09-15T06:00:00Z")
    student = create_enrolled_student(program["id"], full_name="PP",
                                      section="GUARD")
    enrollment = enroll_in_trip(trip["id"], student["id"])
    assert enrollment["amount_due_cents"] == 10000

    post_payment(student["id"], "PAYMENT", 4000,
                 trip_enrollment_id=enrollment["id"])
    current = validate_success(api.get_trip_enrollment(enrollment["id"],
                                                       reader_headers))
    assert current["payment_status"] == "PARTIAL"
    assert current["attendance_status"] == "REGISTERED", (
        "the payment dimension moves without touching attendance")

    premature = api.confirm_trip_enrollment(enrollment["id"], director_headers)
    validate_error(premature, ApiErrorId.ERR_ENROLLMENT_NOT_PAID)

    post_payment(student["id"], "PAYMENT", 6000,
                 trip_enrollment_id=enrollment["id"])
    confirmed = confirm_enrollment(enrollment["id"])
    assert confirmed["payment_status"] == "PAID"
    assert confirmed["attendance_status"] == "CONFIRMED"


def test_unpaid_enrollment_cannot_confirm(api, director_headers):
    """PRD §3.6: "`payment_status` reads `UNPAID` when `net_paid_cents` is zero, `PAID` when `net_paid_cents` is at least `amount_due_cents` and `amount_due_cents` is positive, and `PARTIAL` otherwise; `REFUNDED` is set only by the full-refund paths of excuse and trip cancellation." PRD §3.6: "it requires the trip in `ROSTER_OPEN` or `ROSTER_LOCKED` (else `ERR_TRIP_ROSTER_NOT_OPEN`), the enrollment in `REGISTERED` (else `ERR_ENROLLMENT_NOT_CONFIRMABLE`), and `payment_status` exactly `PAID` (else `ERR_ENROLLMENT_NOT_PAID`)."

    Design: Difficulty/non_linear_state_machine/trip_enrollment_parallel_state_dimensions
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=10000,
        departure_at="2026-09-15T06:00:00Z")
    student = create_enrolled_student(program["id"], full_name="UP")
    enrollment = enroll_in_trip(trip["id"], student["id"])
    assert enrollment["payment_status"] == "UNPAID"
    assert enrollment["attendance_status"] == "REGISTERED"

    blocked = api.confirm_trip_enrollment(enrollment["id"], director_headers)
    validate_error(blocked, ApiErrorId.ERR_ENROLLMENT_NOT_PAID)
    enrollment = get_trip_enrollment(enrollment["id"])
    assert enrollment["attendance_status"] == "REGISTERED"


# --- Difficulty: trip_lock_requires_event_truck_charter --------------------------

def test_lock_roster_requires_charter_then_succeeds(api, director_headers):
    """PRD §3.6: "Locking the roster moves it from `ROSTER_OPEN` to `ROSTER_LOCKED` (again else `ERR_TRIP_ROSTER_NOT_OPEN`), but only once transportation exists: at least one truck charter linked to the trip's event must be in `RESERVED`, `LOADED`, `DEPARTED`, or `RETURNED` status, else `ERR_CHARTER_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/trip_lock_requires_event_truck_charter
    """
    program, event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=5000,
        departure_at="2026-09-15T06:00:00Z")

    blocked = api.lock_trip_roster(trip["id"], director_headers)
    validate_error(blocked, ApiErrorId.ERR_CHARTER_REQUIRED)
    assert get_trip(trip["id"])["status"] == "ROSTER_OPEN"

    create_charter(program["id"], event["id"], vehicle_label="TRUCK-3",
                   capacity_weight_lb=2000, capacity_volume_cuft=200,
                   window_start="2026-09-15T04:00:00Z",
                   window_end="2026-09-16T02:00:00Z")
    locked = validate_success(api.lock_trip_roster(trip["id"], director_headers))
    assert locked["status"] == "ROSTER_LOCKED"


def test_cancelled_charter_does_not_satisfy_the_lock_gate(api, director_headers,
                                                          equipment_headers):
    """PRD §3.6: "Locking the roster moves it from `ROSTER_OPEN` to `ROSTER_LOCKED` (again else `ERR_TRIP_ROSTER_NOT_OPEN`), but only once transportation exists: at least one truck charter linked to the trip's event must be in `RESERVED`, `LOADED`, `DEPARTED`, or `RETURNED` status, else `ERR_CHARTER_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/trip_lock_requires_event_truck_charter
    """
    program, event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=5000,
        departure_at="2026-09-15T06:00:00Z")
    charter = create_charter(program["id"], event["id"], vehicle_label="TRUCK-4",
                             window_start="2026-09-15T04:00:00Z",
                             window_end="2026-09-16T02:00:00Z")
    cancelled = validate_success(api.cancel_truck_charter(charter["id"],
                                                          equipment_headers))
    assert cancelled["status"] == "CANCELLED"

    blocked = api.lock_trip_roster(trip["id"], director_headers)
    validate_error(blocked, ApiErrorId.ERR_CHARTER_REQUIRED)
    assert get_trip(trip["id"])["status"] == "ROSTER_OPEN"


# --- Difficulty: trip_finalize_pinned_evaluation_order ---------------------------

def test_finalize_uses_pinned_order_subsidy_off_gross(api, reader_headers):
    """PRD §3.6: "third, `subsidy_applied_cents` is set to the lesser of the program's `subsidy_pool_cents` and 25 percent of the gross rounded half up to integer cents; fourth, the net is the gross minus the subsidy; fifth, each confirmed enrollment's `final_share_cents` is the net divided by the confirmed count, rounded half up to integer cents — which requires at least one confirmed enrollment." PRD §3.6: "For contrast, the provisional share assigned at enrollment time is the trip's `estimated_cost_cents` divided by the roster count, so an estimated 90000 cents over seven registered students yields a provisional 12857 cents, while a finalized actual of 100000 cents with a 20000-cent pool (the cap of 25000 does not bind) over seven confirmed students yields a final 11429 cents."

    Design: Difficulty/combinatorial_formula/trip_finalize_pinned_evaluation_order
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=10, estimated_cost_cents=90000,
        departure_at="2026-09-01T06:00:00Z",
        event_overrides={"starts_at": "2026-09-01T15:00:00Z",
                         "ends_at": "2026-09-01T21:00:00Z"},
        program_overrides={"season_name": "TR", "subsidy_pool_cents": 20000})
    enrollments = []
    for i in range(7):
        student = create_enrolled_student(program["id"], full_name=f"T{i + 1}")
        enrollment = enroll_in_trip(trip["id"], student["id"])
        post_payment(student["id"], "PAYMENT", enrollment["amount_due_cents"],
                     trip_enrollment_id=enrollment["id"])
        confirm_enrollment(enrollment["id"])
        enrollments.append(enrollment)
    create_charter(program["id"], _event["id"], vehicle_label="TRUCK-1",
                   window_start="2026-09-01T04:00:00Z",
                   window_end="2026-09-02T02:00:00Z")
    validate_success(api.lock_trip_roster(trip["id"], DIRECTOR))

    finalized = validate_success(api.finalize_trip(
        trip["id"], {"actual_cost_cents": 100000}, TREASURER_H))
    assert finalized["status"] == "FINALIZED"
    # min(pool 20000, round_half_up(0.25 * 100000) = 25000) = 20000
    assert finalized["subsidy_applied_cents"] == 20000

    first = get_trip_enrollment(enrollments[0]["id"])
    assert first["final_share_cents"] == 11429, (
        "round_half_up((100000 - 20000) / 7) — subsidy off gross, divide after")
    assert first["amount_due_cents"] == 11429
    assert first["payment_status"] == "PAID", (
        "the 90000 provisional payment covers the 11429 final share")

    student = validate_success(api.get_student(first["student_id"],
                                               reader_headers))
    assert student["account_balance_cents"] == -78571, (
        "11429 TRIP_SHARE_DEBIT minus the 90000 PAYMENT")


def test_finalize_subsidy_cap_binds_when_pool_exceeds_quarter(api):
    """PRD §3.6: "third, `subsidy_applied_cents` is set to the lesser of the program's `subsidy_pool_cents` and 25 percent of the gross rounded half up to integer cents; fourth, the net is the gross minus the subsidy; fifth, each confirmed enrollment's `final_share_cents` is the net divided by the confirmed count, rounded half up to integer cents — which requires at least one confirmed enrollment. Sizing the subsidy off the net rather than the gross, or dividing before subtracting the subsidy, is forbidden."

    Design: Difficulty/combinatorial_formula/trip_finalize_pinned_evaluation_order
    """
    program, _event, trip, student, enrollment = setup_locked_trip(
        capacity=5, estimated_cost_cents=5000,
        departure_at="2026-09-15T06:00:00Z",
        program_overrides={"season_name": "TR2", "subsidy_pool_cents": 60000})

    finalized = validate_success(api.finalize_trip(
        trip["id"], {"actual_cost_cents": 100000}, TREASURER_H))
    # min(pool 60000, round_half_up(0.25 * 100000) = 25000) = 25000 — cap binds
    assert finalized["subsidy_applied_cents"] == 25000
    enrollment = get_trip_enrollment(enrollment["id"])
    assert enrollment["final_share_cents"] == 75000, (
        "net 100000 - 25000 = 75000 over one confirmed seat")
    assert enrollment["amount_due_cents"] == 75000
    student = get_student(student["id"])
    assert student["account_balance_cents"] == 70000, (
        "75000 TRIP_SHARE_DEBIT minus the 5000 PAYMENT")


# --- Difficulty: trip_payment_then_cancel_refund_conserves_net_cash ---------------

def test_full_payment_then_cancel_conserves_net_cash(api, director_headers,
                                                     reader_headers):
    """PRD §3.6: "Cancellation of a trip is available to a `BandDirector` from `PLANNING`, `ROSTER_OPEN`, `ROSTER_LOCKED`, or `FINALIZED` (else `ERR_INVALID_STATE`), and triggers the same cascade as the event-driven cancellation above: enrollments in `REGISTERED`, `CONFIRMED`, or `WAITLISTED` move to `EXCUSED`, every enrollment with positive `net_paid_cents` is refunded in full via a `REFUND` payment and moves to `REFUNDED`, and affected student balances recompute." PRD §3.6: "An enrollment's `net_paid_cents` is the sum of `PAYMENT` rows minus the sum of `REFUND` rows linked to it via `trip_enrollment_id`, and `refunded_cents` is the sum of those `REFUND` rows alone."

    Design: Difficulty/compensating_invariant/trip_payment_then_cancel_refund_conserves_net_cash
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=8000,
        departure_at="2026-09-15T06:00:00Z")
    student = create_enrolled_student(program["id"], full_name="Inv")
    enrollment = enroll_in_trip(trip["id"], student["id"])
    post_payment(student["id"], "PAYMENT", 8000,
                 trip_enrollment_id=enrollment["id"])
    assert get_trip_enrollment(enrollment["id"])["net_paid_cents"] == 8000

    cancelled = validate_success(api.cancel_trip(trip["id"], director_headers))
    assert cancelled["status"] == "CANCELLED"

    enrollment = validate_success(api.get_trip_enrollment(enrollment["id"],
                                                          reader_headers))
    assert enrollment["attendance_status"] == "EXCUSED"
    assert enrollment["net_paid_cents"] == 0, "8000 PAYMENT - 8000 REFUND"
    assert enrollment["refunded_cents"] == 8000
    assert enrollment["payment_status"] == "REFUNDED"
    assert get_student(student["id"])["account_balance_cents"] == 0, (
        "forward payment plus compensating refund conserve net cash")


def test_partial_payment_then_cancel_refunds_exactly_net_paid(
        api, director_headers):
    """PRD §3.6: "Cancellation of a trip is available to a `BandDirector` from `PLANNING`, `ROSTER_OPEN`, `ROSTER_LOCKED`, or `FINALIZED` (else `ERR_INVALID_STATE`), and triggers the same cascade as the event-driven cancellation above: enrollments in `REGISTERED`, `CONFIRMED`, or `WAITLISTED` move to `EXCUSED`, every enrollment with positive `net_paid_cents` is refunded in full via a `REFUND` payment and moves to `REFUNDED`, and affected student balances recompute."

    Design: Difficulty/compensating_invariant/trip_payment_then_cancel_refund_conserves_net_cash
    """
    program, _event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=8000,
        departure_at="2026-09-15T06:00:00Z")
    student = create_enrolled_student(program["id"], full_name="Inv2")
    enrollment = enroll_in_trip(trip["id"], student["id"])
    post_payment(student["id"], "PAYMENT", 3000,
                 trip_enrollment_id=enrollment["id"])
    assert get_trip_enrollment(enrollment["id"])["payment_status"] == "PARTIAL"

    validate_success(api.cancel_trip(trip["id"], director_headers))
    enrollment = get_trip_enrollment(enrollment["id"])
    assert enrollment["refunded_cents"] == 3000, "refunded in full means net paid"
    assert enrollment["net_paid_cents"] == 0
    assert enrollment["payment_status"] == "REFUNDED"
    assert get_student(student["id"])["account_balance_cents"] == 0


# --- Difficulty: event_cancel_cascades_trip_enrollment_refund_balance -------------

def test_event_cancel_cascades_to_refund_and_zero_balance(
        api, director_headers, reader_headers):
    """PRD §3.6: "Cancelling an event in `SCHEDULED`, `WEATHER_WATCH`, `INDOOR_RELOCATED`, or `POSTPONED` (else `ERR_EVENT_TERMINAL`) moves it to `CANCELLED` and forces any linked trip in `PLANNING`, `ROSTER_OPEN`, `ROSTER_LOCKED`, or `FINALIZED` to `CANCELLED` as well. That trip cancellation then cascades in full: every enrollment of the trip with attendance `REGISTERED`, `CONFIRMED`, or `WAITLISTED` moves to `EXCUSED`; every enrollment with a positive `net_paid_cents` receives a `REFUND` payment of its full `net_paid_cents` and its `payment_status` moves to `REFUNDED`; and each affected student's `account_balance_cents` is recomputed."

    Design: Difficulty/transitive_cascade/event_cancel_cascades_trip_enrollment_refund_balance
    """
    program, event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=10000,
        departure_at="2026-09-15T06:00:00Z")
    student = create_enrolled_student(program["id"], full_name="CC")
    enrollment = enroll_in_trip(trip["id"], student["id"])
    post_payment(student["id"], "PAYMENT", 10000,
                 trip_enrollment_id=enrollment["id"])
    confirm_enrollment(enrollment["id"])
    create_charter(program["id"], event["id"], vehicle_label="TRUCK-9",
                   window_start="2026-09-15T04:00:00Z",
                   window_end="2026-09-16T02:00:00Z")
    validate_success(api.lock_trip_roster(trip["id"], director_headers))

    cancelled = validate_success(api.cancel_event(event["id"], director_headers))
    assert cancelled["status"] == "CANCELLED"

    trip = validate_success(api.get_trip(trip["id"], reader_headers))
    assert trip["status"] == "CANCELLED", "cancelled via the event, not directly"

    enrollment = validate_success(api.get_trip_enrollment(enrollment["id"],
                                                          reader_headers))
    assert enrollment["attendance_status"] == "EXCUSED"
    assert enrollment["payment_status"] == "REFUNDED"

    refunds, meta = validate_paginated(api.list_payments(
        reader_headers, params={"student_id": student["id"], "kind": "REFUND"}))
    assert meta["total_count"] == 1
    assert refunds[0]["amount_cents"] == 10000, "full net_paid at the far tier"
    assert refunds[0]["trip_enrollment_id"] == enrollment["id"]
    assert get_student(student["id"])["account_balance_cents"] == 0


def test_event_cancel_leaves_unpaid_enrollment_without_refund(
        api, director_headers, reader_headers):
    """PRD §3.6: "That trip cancellation then cascades in full: every enrollment of the trip with attendance `REGISTERED`, `CONFIRMED`, or `WAITLISTED` moves to `EXCUSED`; every enrollment with a positive `net_paid_cents` receives a `REFUND` payment of its full `net_paid_cents` and its `payment_status` moves to `REFUNDED`; and each affected student's `account_balance_cents` is recomputed." PRD §3.6: "`payment_status` reads `UNPAID` when `net_paid_cents` is zero, `PAID` when `net_paid_cents` is at least `amount_due_cents` and `amount_due_cents` is positive, and `PARTIAL` otherwise; `REFUNDED` is set only by the full-refund paths of excuse and trip cancellation."

    Design: Difficulty/transitive_cascade/event_cancel_cascades_trip_enrollment_refund_balance
    """
    program, event, trip = setup_trip_with_open_roster(
        capacity=5, estimated_cost_cents=10000,
        departure_at="2026-09-15T06:00:00Z")
    paid_student = create_enrolled_student(program["id"], full_name="CP")
    unpaid_student = create_enrolled_student(program["id"], full_name="CU")
    paid_enrollment = enroll_in_trip(trip["id"], paid_student["id"])
    unpaid_enrollment = enroll_in_trip(trip["id"], unpaid_student["id"])
    post_payment(paid_student["id"], "PAYMENT", 10000,
                 trip_enrollment_id=paid_enrollment["id"])

    validate_success(api.cancel_event(event["id"], director_headers))

    paid = validate_success(api.get_trip_enrollment(paid_enrollment["id"],
                                                    reader_headers))
    assert paid["attendance_status"] == "EXCUSED"
    assert paid["payment_status"] == "REFUNDED"

    unpaid = validate_success(api.get_trip_enrollment(unpaid_enrollment["id"],
                                                      reader_headers))
    assert unpaid["attendance_status"] == "EXCUSED"
    assert unpaid["payment_status"] == "UNPAID", (
        "no positive net_paid: no refund, no REFUNDED transition")
    assert unpaid["refunded_cents"] == 0

    refunds, meta = validate_paginated(api.list_payments(
        reader_headers, params={"student_id": unpaid_student["id"],
                                "kind": "REFUND"}))
    assert meta["total_count"] == 0
    assert get_student(unpaid_student["id"])["account_balance_cents"] == 0


# --- Corner: supersede, OCC on trip create, completion gate -----------------------

def test_trip_supersede_and_active_trip_rejection(api, director_headers,
                                                  reader_headers):
    """PRD §3.6: "One event has at most one live trip: if the event's existing trip is still in `PLANNING`, creating the new trip legitimately supersedes it, moving the old trip to `SUPERSEDED`; if the existing trip has advanced beyond `PLANNING`, creation is rejected with `ERR_EVENT_HAS_ACTIVE_TRIP`."

    Design: Corner/endpoints/trip_supersede_and_active_trip_rejection
    """
    program = create_open_program(season_name="SP")
    event = create_event(program["id"], event_type="COMPETITION", facility="AWAY",
                         starts_at="2026-09-15T15:00:00Z",
                         ends_at="2026-09-15T21:00:00Z", is_outdoor=True)
    trip1 = create_trip(event["id"], event["version"], capacity=5,
                        estimated_cost_cents=5000,
                        departure_at="2026-09-15T06:00:00Z")

    trip2 = create_trip(event["id"], None, capacity=6, estimated_cost_cents=6000,
                        departure_at="2026-09-15T06:00:00Z")
    assert validate_success(api.get_trip(trip1["id"], reader_headers))[
        "status"] == "SUPERSEDED"
    assert trip2["status"] == "PLANNING"

    validate_success(api.open_trip_roster(trip2["id"], director_headers))
    rejected = api.create_trip(
        {"event_id": event["id"],
         "expected_event_version": get_event(event["id"])["version"],
         "capacity": 7, "estimated_cost_cents": 7000,
         "departure_at": "2026-09-15T06:00:00Z"}, director_headers)
    validate_error(rejected, ApiErrorId.ERR_EVENT_HAS_ACTIVE_TRIP)
    _ = program


def test_trip_create_rejects_stale_event_version(api, director_headers,
                                                 reader_headers):
    """PRD §2.10: "Creating a trip requires the request to carry `expected_event_version` holding the `version` of the parent `Event` the client last observed. Because creating a trip legitimately supersedes the event's existing `PLANNING` trip, a writer acting on a stale view of the event is refused: a mismatch with the event's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.6: "Creation is OCC-guarded per §2.10: the request must carry `expected_event_version` matching the event's current `version`, else `ERR_STALE_VERSION`, and a successful creation increments the event's `version` by 1."

    Design: Corner/cross_cutting_layers/trip_create_occ_stale_event_version
    """
    program = create_open_program(season_name="OC2")
    event = create_event(program["id"], event_type="COMPETITION", facility="AWAY",
                         starts_at="2026-09-15T15:00:00Z",
                         ends_at="2026-09-15T21:00:00Z", is_outdoor=True)
    observed_version = event["version"]

    trip1 = create_trip(event["id"], observed_version, capacity=5,
                        estimated_cost_cents=5000,
                        departure_at="2026-09-15T06:00:00Z")
    assert get_event(event["id"])["version"] == observed_version + 1, (
        "a successful creation increments the event's version by 1")

    stale = api.create_trip(
        {"event_id": event["id"], "expected_event_version": observed_version,
         "capacity": 6, "estimated_cost_cents": 6000,
         "departure_at": "2026-09-15T06:00:00Z"}, director_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    _rows, meta = validate_paginated(api.list_trips(
        reader_headers, params={"event_id": event["id"]}))
    assert meta["total_count"] == 1, "the stale create persisted nothing"
    _ = trip1, program


def test_trip_complete_requires_all_attendance_resolved(api, director_headers,
                                                        reader_headers):
    """PRD §3.6: "A `FINALIZED` trip may be completed by a `BandDirector` or `AssistantDirector` (else `ERR_TRIP_NOT_LOCKED`), but only when every enrollment's attendance is resolved to `ATTENDED`, `NO_SHOW`, or `EXCUSED` — any unresolved seat yields `ERR_UNRESOLVED_ENROLLMENTS_EXIST`." PRD §3.6: "A `BandDirector` or `AssistantDirector` may mark a `CONFIRMED` enrollment on a `FINALIZED` trip (else `ERR_TRIP_NOT_LOCKED`) with an `outcome` of `ATTENDED` or `NO_SHOW`."

    Design: Corner/endpoints/trip_complete_requires_resolved_attendance
    """
    _program, _event, trip, _student, enrollment = setup_finalized_trip(
        actual_cost_cents=5000, capacity=5, estimated_cost_cents=5000,
        departure_at="2026-09-15T06:00:00Z")
    assert trip["status"] == "FINALIZED"

    blocked = api.complete_trip(trip["id"], director_headers)
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_ENROLLMENTS_EXIST)

    marked = validate_success(api.mark_trip_attendance(
        enrollment["id"], mark_attendance_payload("ATTENDED"), director_headers))
    assert marked["attendance_status"] == "ATTENDED"

    completed = validate_success(api.complete_trip(trip["id"], director_headers))
    assert completed["status"] == "COMPLETED"
    enrollment = validate_success(api.get_trip_enrollment(enrollment["id"],
                                                          reader_headers))
    assert enrollment["payment_status"] == "PAID", (
        "5000 paid against the 5000 final share")
    assert enrollment["final_share_cents"] == 5000
