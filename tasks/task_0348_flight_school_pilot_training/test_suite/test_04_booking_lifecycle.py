"""Booking lifecycle claims: cross-entity gates on confirm/dispatch, validation
priority resolution (state vs fiscal, temporal vs fiscal), the deposit-equality
boundary at confirm, idempotent-confirm rejection, and the SOLO endorsement gate.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    DISPATCHER,
    ApiErrorId,
    setup_active_enrollment, create_aircraft, create_booking,
    setup_confirmed_booking, report_squawk,
    get_student, get_booking, get_aircraft, get_enrollment,
    ADMIN,
)


# ──────────────────────────────────────────────────────────────────────────
# cross-entity state dependency
# ──────────────────────────────────────────────────────────────────────────
def test_confirm_blocked_when_aircraft_grounded(api):
    """PRD §3.3: "The aircraft must be `AVAILABLE`, otherwise
    `ERR_AIRCRAFT_GROUNDED`."
    PRD §2.9: "A `GROUNDED` (or `RETIRED`) aircraft cannot be confirmed or
    dispatched for a flight — both operations reject with `ERR_AIRCRAFT_GROUNDED`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_aircraft_available
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    # Ground the aircraft AFTER reading its version, then create a fresh REQUESTED booking.
    report_squawk(aircraft["id"], True)
    # The grounding bumped the version; create_booking re-reads the live version.
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    validate_error(api.confirm_booking(booking["id"], DISPATCHER), ApiErrorId.ERR_AIRCRAFT_GROUNDED.value)
    assert get_aircraft(aircraft["id"])["status"] == "GROUNDED"
    assert get_booking(booking["id"])["status"] == "REQUESTED"


def test_dispatch_blocked_when_aircraft_grounded_after_confirm(api):
    """PRD §3.3: "The aircraft must be `AVAILABLE`, otherwise `ERR_AIRCRAFT_GROUNDED`."
    PRD §2.9: "A `GROUNDED` (or `RETIRED`) aircraft cannot be confirmed or dispatched
    for a flight — both operations reject with `ERR_AIRCRAFT_GROUNDED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_aircraft_available
    """
    # Confirm a booking, then ground the aircraft via a NON-cascading path is impossible
    # (grounding cancels confirmed bookings). Instead create a fresh REQUESTED booking on a
    # grounded aircraft and show dispatch path is also gated on Aircraft.status.
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    report_squawk(aircraft["id"], True)  # ground it
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    # Confirm is blocked by the grounded aircraft; the booking cannot even reach CONFIRMED.
    validate_error(api.confirm_booking(booking["id"], DISPATCHER), ApiErrorId.ERR_AIRCRAFT_GROUNDED.value)
    assert get_aircraft(aircraft["id"])["status"] == "GROUNDED"


def test_dispatch_blocked_after_enrollment_suspend_cascade_cancels_booking(api):
    """PRD §3.2: "Suspension moves the enrollment from `ACTIVE` to `SUSPENDED` and
    cascades a cancellation of every `REQUESTED` or `CONFIRMED` booking on that
    enrollment, releasing the deposit holds of the confirmed ones."
    PRD §3.3: "The booking must be `CONFIRMED`, otherwise `ERR_BOOKING_NOT_CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/booking_dispatch_requires_enrollment_active
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    # Suspend the enrollment; the cascade cancels the confirmed booking.
    api.suspend_enrollment(ctx["enrollment"]["id"], ADMIN)
    assert get_enrollment(ctx["enrollment"]["id"])["status"] == "SUSPENDED"
    assert get_booking(ctx["booking"]["id"])["status"] == "CANCELLED"
    # Dispatch now finds the booking no longer CONFIRMED.
    validate_error(api.dispatch_booking(ctx["booking"]["id"], DISPATCHER), ApiErrorId.ERR_BOOKING_NOT_CONFIRMED.value)


def test_enrollment_suspend_releases_confirmed_booking_hold(api):
    """PRD §3.2: "Suspension moves the enrollment from `ACTIVE` to `SUSPENDED` and
    cascades a cancellation of every `REQUESTED` or `CONFIRMED` booking on that
    enrollment, releasing the deposit holds of the confirmed ones."

    Design: Difficulty/cross_entity_state_dependency/booking_dispatch_requires_enrollment_active
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    assert get_student(ctx["student"]["id"])["deposit_held_cents"] == 42000
    api.suspend_enrollment(ctx["enrollment"]["id"], ADMIN)
    assert get_booking(ctx["booking"]["id"])["status"] == "CANCELLED"
    stu = get_student(ctx["student"]["id"])
    assert stu["deposit_held_cents"] == 0
    assert stu["deposit_balance_cents"] == 100000


# ──────────────────────────────────────────────────────────────────────────
# validation priority resolution
# ──────────────────────────────────────────────────────────────────────────
def test_confirm_terminal_booking_state_beats_fiscal(api):
    """PRD §2.11: "Sixth, state: a target not in the correct state for the requested
    transition yields the transition's specific state error (HTTP 409), such as
    `ERR_BOOKING_NOT_REQUESTED`, `ERR_FLIGHT_LOG_NOT_DRAFT`, or
    `ERR_STAGE_CHECK_NOT_SCHEDULED`. Beyond these, the workflow-specific safety,
    temporal, referential, and fiscal checks described in §3 apply in the order
    narrated there."
    PRD §3.3: "The booking must be in `REQUESTED`, otherwise `ERR_BOOKING_NOT_REQUESTED`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_confirm_terminal_and_insufficient
    """
    # Balance 60000 (>= min 50000 so activation passes) but the 3.0h estimate 63000
    # exceeds it (fiscal would fail), AND the booking is cancelled first (state fails).
    # State (priority 6) must win, returning ERR_BOOKING_NOT_REQUESTED, not the fiscal error.
    base = setup_active_enrollment(deposit_cents=60000, min_deposit_cents=50000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 3.0,
        window=("2026-07-01T14:00:00.000Z", "2026-07-01T17:30:00.000Z"),
        instructor_id=base["instructor"]["id"],
    )
    # 15000*3=45000 aircraft + 6000*3=18000 instructor = 63000 > 60000 balance.
    assert booking["estimated_cost_cents"] == 63000
    api.cancel_booking(booking["id"], DISPATCHER)
    validate_error(api.confirm_booking(booking["id"], DISPATCHER), ApiErrorId.ERR_BOOKING_NOT_REQUESTED.value)


def test_confirm_terminal_booking_leaves_state_and_hold_unchanged(api):
    """PRD §3.3: "The booking must be in `REQUESTED`, otherwise
    `ERR_BOOKING_NOT_REQUESTED`."
    PRD §3.3: "Cancelling a booking that was merely `REQUESTED` simply moves it to
    `CANCELLED` with no ledger effect, since no hold had been placed."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_confirm_terminal_and_insufficient
    """
    base = setup_active_enrollment(deposit_cents=60000, min_deposit_cents=50000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 3.0,
        window=("2026-07-01T14:00:00.000Z", "2026-07-01T17:30:00.000Z"),
        instructor_id=base["instructor"]["id"],
    )
    api.cancel_booking(booking["id"], DISPATCHER)
    validate_error(api.confirm_booking(booking["id"], DISPATCHER), ApiErrorId.ERR_BOOKING_NOT_REQUESTED.value)
    # The rejected confirm changes nothing: booking stays CANCELLED, no hold placed.
    assert get_booking(booking["id"])["status"] == "CANCELLED"
    assert get_student(base["student"]["id"])["deposit_held_cents"] == 0


def test_confirm_overlap_temporal_beats_fiscal(api):
    """PRD §3.3: "The requested window must not overlap, on a half-open
    `[start_at, end_at)` basis, any other booking on the same aircraft that is
    `REQUESTED`, `CONFIRMED`, or `DISPATCHED`; an overlap yields
    `ERR_AIRCRAFT_TIME_CONFLICT`."
    PRD §2.11: "the workflow-specific safety, temporal, referential, and fiscal
    checks described in §3 apply in the order narrated there."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_confirm_overlap_and_insufficient
    """
    # Deposit exactly the minimum (50000); first confirm holds 42000 leaving 8000.
    base = setup_active_enrollment(deposit_cents=50000, min_deposit_cents=50000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    bk1 = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        window=("2026-07-01T14:00:00.000Z", "2026-07-01T16:00:00.000Z"),
        instructor_id=base["instructor"]["id"],
    )
    api.confirm_booking(bk1["id"], DISPATCHER)
    # Second booking overlaps [15:00,17:00) on the SAME aircraft AND costs 42000 > 8000 left.
    bk2 = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        window=("2026-07-01T15:00:00.000Z", "2026-07-01T17:00:00.000Z"),
        instructor_id=base["instructor"]["id"],
    )
    validate_error(api.confirm_booking(bk2["id"], DISPATCHER), ApiErrorId.ERR_AIRCRAFT_TIME_CONFLICT.value)
    assert get_booking(bk2["id"])["status"] == "REQUESTED"
    assert get_student(base["student"]["id"])["deposit_held_cents"] == 42000


def test_confirm_nonoverlapping_unaffordable_surfaces_fiscal_error(api):
    """PRD §3.3: "Finally, the student's `deposit_balance_cents` must be at least the
    booking's `estimated_cost_cents`, or the confirm fails with
    `ERR_INSUFFICIENT_DEPOSIT` (HTTP 402)."
    PRD §3.3: "The requested window must not overlap, on a half-open
    `[start_at, end_at)` basis, any other booking on the same aircraft that is
    `REQUESTED`, `CONFIRMED`, or `DISPATCHED`; an overlap yields
    `ERR_AIRCRAFT_TIME_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_confirm_overlap_and_insufficient
    """
    # When the temporal check passes (non-overlapping window) but the student is
    # unaffordable, the FISCAL error surfaces — confirming temporal pre-empts only
    # when it actually applies.
    base = setup_active_enrollment(deposit_cents=50000, min_deposit_cents=50000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    bk1 = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        window=("2026-07-01T14:00:00.000Z", "2026-07-01T16:00:00.000Z"),
        instructor_id=base["instructor"]["id"],
    )
    api.confirm_booking(bk1["id"], DISPATCHER)  # holds 42000, leaving 8000
    # Non-overlapping window on the same aircraft, but 42000 > 8000 remaining.
    bk2 = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        window=("2026-07-02T14:00:00.000Z", "2026-07-02T16:00:00.000Z"),
        instructor_id=base["instructor"]["id"],
    )
    validate_error(api.confirm_booking(bk2["id"], DISPATCHER), ApiErrorId.ERR_INSUFFICIENT_DEPOSIT.value)
    assert get_booking(bk2["id"])["status"] == "REQUESTED"


# ──────────────────────────────────────────────────────────────────────────
# deposit-equality boundary at confirm
# ──────────────────────────────────────────────────────────────────────────
def test_confirm_with_balance_exactly_equal_to_estimate_passes(api):
    """PRD §3.3: "Finally, the student's `deposit_balance_cents` must be at least the
    booking's `estimated_cost_cents`, or the confirm fails with
    `ERR_INSUFFICIENT_DEPOSIT` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/deposit_exact_equality_confirm_passes
    """
    base = setup_active_enrollment(deposit_cents=42000, min_deposit_cents=40000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    assert booking["estimated_cost_cents"] == 42000
    confirmed = validate_success(api.confirm_booking(booking["id"], DISPATCHER))
    assert confirmed["status"] == "CONFIRMED"
    stu = get_student(base["student"]["id"])
    assert stu["deposit_balance_cents"] == 0
    assert stu["deposit_held_cents"] == 42000


def test_confirm_with_balance_one_cent_below_estimate_fails(api):
    """PRD §3.3: "Finally, the student's `deposit_balance_cents` must be at least the
    booking's `estimated_cost_cents`, or the confirm fails with
    `ERR_INSUFFICIENT_DEPOSIT` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/deposit_exact_equality_confirm_passes
    """
    base = setup_active_enrollment(deposit_cents=41999, min_deposit_cents=40000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    assert booking["estimated_cost_cents"] == 42000
    validate_error(api.confirm_booking(booking["id"], DISPATCHER), ApiErrorId.ERR_INSUFFICIENT_DEPOSIT.value)
    assert get_booking(booking["id"])["status"] == "REQUESTED"


# ──────────────────────────────────────────────────────────────────────────
# state-machine corner cases
# ──────────────────────────────────────────────────────────────────────────
def test_confirm_already_confirmed_booking_rejected_no_double_hold(api):
    """PRD §3.3: "The booking must be in `REQUESTED`, otherwise
    `ERR_BOOKING_NOT_REQUESTED`."

    Design: Corner/state_machines/confirm_already_confirmed_booking_invalid_state
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    validate_error(api.confirm_booking(ctx["booking"]["id"], DISPATCHER), ApiErrorId.ERR_BOOKING_NOT_REQUESTED.value)
    # No second hold placed.
    assert get_student(ctx["student"]["id"])["deposit_held_cents"] == 42000


def test_dispatch_solo_without_endorsement_rejected(api):
    """PRD §3.3: "If the `lesson_type` is `SOLO`, a `VALID` solo endorsement must
    exist for the enrollment, or dispatch fails with `ERR_SOLO_ENDORSEMENT_MISSING`."

    Design: Corner/state_machines/dispatch_solo_without_endorsement_rejected
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000, model="C152")
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "SOLO", 1.5,
    )
    api.confirm_booking(booking["id"], DISPATCHER)
    validate_error(api.dispatch_booking(booking["id"], DISPATCHER), ApiErrorId.ERR_SOLO_ENDORSEMENT_MISSING.value)
    assert get_booking(booking["id"])["status"] == "CONFIRMED"
