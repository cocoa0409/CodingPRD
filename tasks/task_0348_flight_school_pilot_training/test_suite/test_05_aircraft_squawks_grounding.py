"""Aircraft and squawk claims: the AVAILABLE<->GROUNDED cycle, the depth-4
grounding cascade (squawk -> aircraft -> booking -> deposit release), squawk
lifecycle preconditions (defer/resolve/reopen), and aircraft retirement gating.
"""
from test_helpers import (
    validate_error,
    MECHANIC, ADMIN,
    ApiErrorId,
    create_aircraft, report_squawk, get_aircraft, get_squawk, get_student, get_booking,
    setup_grounded_aircraft, setup_confirmed_booking, setup_active_enrollment, create_booking,
)


def test_aircraft_cycles_available_grounded_available(api):
    """PRD §2.9: "Whenever that count is at least one, the aircraft is `GROUNDED`;
    when it returns to zero, the aircraft is `AVAILABLE` again."
    PRD §3.5: "if it was the last open grounding squawk, cascades the aircraft from
    `GROUNDED` back to `AVAILABLE` (incrementing the aircraft's `version`)."

    Design: Difficulty/non_linear_state_machine/aircraft_cyclic_available_grounded_available
    """
    aircraft = create_aircraft(initial_hobbs=10.0, initial_tach=8.0)
    squawk = report_squawk(aircraft["id"], True)
    grounded = get_aircraft(aircraft["id"])
    assert grounded["status"] == "GROUNDED"
    assert grounded["open_squawk_count"] == 1

    api.resolve_squawk(squawk["id"], MECHANIC)
    available = get_aircraft(aircraft["id"])
    assert available["status"] == "AVAILABLE"
    assert available["open_squawk_count"] == 0


def test_aircraft_version_advances_across_grounding_cycle(api):
    """PRD §3.5: "this cascades it from `AVAILABLE` to `GROUNDED` — which itself
    cancels the aircraft's `REQUESTED` and `CONFIRMED` bookings (releasing holds on
    the confirmed ones) and increments the aircraft's `version` by one."
    PRD §3.5: "if it was the last open grounding squawk, cascades the aircraft from
    `GROUNDED` back to `AVAILABLE` (incrementing the aircraft's `version`)."

    Design: Difficulty/non_linear_state_machine/aircraft_cyclic_available_grounded_available
    """
    aircraft = create_aircraft(initial_hobbs=10.0, initial_tach=8.0)
    v0 = aircraft["version"]
    squawk = report_squawk(aircraft["id"], True)
    v_grounded = get_aircraft(aircraft["id"])["version"]
    assert v_grounded > v0, "grounding bumps version"
    api.resolve_squawk(squawk["id"], MECHANIC)
    v_available = get_aircraft(aircraft["id"])["version"]
    assert v_available > v_grounded, "un-grounding bumps version again"


def test_grounding_cascade_cancels_confirmed_booking_and_releases_hold(api):
    """PRD §2.6: "When an aircraft is grounded, every booking on that aircraft that
    is still `REQUESTED` or `CONFIRMED` is cancelled, and a cancelled booking that
    had been `CONFIRMED` releases its provisional deposit hold as part of the same
    step."
    PRD §3.5: "If it is a grounding squawk, reporting it increments the aircraft's
    `open_squawk_count` by one, and if the aircraft was `AVAILABLE` this cascades it
    from `AVAILABLE` to `GROUNDED`..."

    Design: Difficulty/transitive_cascade/grounding_cascade_squawk_aircraft_booking_deposit
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    # Confirmed: 42000 held.
    assert get_student(ctx["student"]["id"])["deposit_held_cents"] == 42000
    # Ground the aircraft by reporting a grounding squawk.
    report_squawk(ctx["aircraft"]["id"], True)

    assert get_aircraft(ctx["aircraft"]["id"])["status"] == "GROUNDED"
    assert get_booking(ctx["booking"]["id"])["status"] == "CANCELLED"
    stu = get_student(ctx["student"]["id"])
    assert stu["deposit_held_cents"] == 0
    assert stu["deposit_balance_cents"] == 100000


def test_grounding_cascade_cancels_requested_booking_no_ledger_effect(api):
    """PRD §2.6: "When an aircraft is grounded, every booking on that aircraft that
    is still `REQUESTED` or `CONFIRMED` is cancelled, and a cancelled booking that
    had been `CONFIRMED` releases its provisional deposit hold as part of the same
    step."
    PRD §3.3: "Cancelling a booking that was merely `REQUESTED` simply moves it to
    `CANCELLED` with no ledger effect, since no hold had been placed."

    Design: Difficulty/transitive_cascade/grounding_cascade_squawk_aircraft_booking_deposit
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    # A REQUESTED (never confirmed, so no hold) booking on the aircraft.
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    report_squawk(aircraft["id"], True)
    assert get_aircraft(aircraft["id"])["status"] == "GROUNDED"
    assert get_booking(booking["id"])["status"] == "CANCELLED"
    stu = get_student(base["student"]["id"])
    # No hold was ever placed, so the balance is untouched and nothing is held.
    assert stu["deposit_held_cents"] == 0
    assert stu["deposit_balance_cents"] == 100000


def test_grounding_squawk_cannot_be_deferred(api):
    """PRD §3.5: "additionally requires that it is not a grounding squawk — a
    grounding squawk cannot be deferred and yields
    `ERR_GROUNDING_SQUAWK_NOT_DEFERRABLE`..."

    Design: Corner/state_machines/squawk_defer_grounding_rejected
    """
    ctx = setup_grounded_aircraft(initial_hobbs=10.0, initial_tach=8.0)
    validate_error(api.defer_squawk(ctx["squawk"]["id"], MECHANIC),
                   ApiErrorId.ERR_GROUNDING_SQUAWK_NOT_DEFERRABLE.value)
    assert get_aircraft(ctx["aircraft"]["id"])["status"] == "GROUNDED"
    assert get_squawk(ctx["squawk"]["id"])["status"] == "OPEN"


def test_reopen_resolved_grounding_squawk_regrounds_aircraft(api):
    """PRD §3.5: "Reopening a grounding squawk increments the aircraft's
    `open_squawk_count`, and if that grounding squawk's reopen finds the aircraft
    `AVAILABLE`, it cascades the aircraft from `AVAILABLE` to `GROUNDED` (which
    itself cancels open bookings)."

    Design: Corner/state_machines/squawk_reopen_regrounds_aircraft_bubble
    """
    aircraft = create_aircraft(initial_hobbs=10.0, initial_tach=8.0)
    squawk = report_squawk(aircraft["id"], True)
    api.resolve_squawk(squawk["id"], MECHANIC)
    assert get_aircraft(aircraft["id"])["status"] == "AVAILABLE"

    api.reopen_squawk(squawk["id"], MECHANIC)
    assert get_squawk(squawk["id"])["status"] == "OPEN"
    re = get_aircraft(aircraft["id"])
    assert re["status"] == "GROUNDED"
    assert re["open_squawk_count"] == 1


def test_resolve_already_resolved_squawk_rejected(api):
    """PRD §3.5: "Resolving a squawk requires it to be `OPEN` or `DEFERRED`,
    otherwise `ERR_SQUAWK_NOT_RESOLVABLE`; resolution moves it to `RESOLVED`, and if
    it was a grounding squawk that had been `OPEN`, decrements the aircraft's
    `open_squawk_count`, and if it was the last open grounding squawk, cascades the
    aircraft from `GROUNDED` back to `AVAILABLE` (incrementing the aircraft's
    `version`)."

    Design: Corner/errors/squawk_resolve_already_resolved
    """
    aircraft = create_aircraft(initial_hobbs=10.0, initial_tach=8.0)
    squawk = report_squawk(aircraft["id"], False, description="Loose panel")
    api.resolve_squawk(squawk["id"], MECHANIC)
    validate_error(api.resolve_squawk(squawk["id"], MECHANIC), ApiErrorId.ERR_SQUAWK_NOT_RESOLVABLE.value)


def test_retire_aircraft_with_active_booking_rejected(api):
    """PRD §3.1: "an aircraft with any booking still in `REQUESTED`, `CONFIRMED`, or
    `DISPATCHED` cannot be retired and yields `ERR_AIRCRAFT_HAS_ACTIVE_BOOKINGS`."

    Design: Corner/state_machines/aircraft_retire_with_active_bookings_rejected
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    validate_error(api.retire_aircraft(ctx["aircraft"]["id"], ADMIN),
                   ApiErrorId.ERR_AIRCRAFT_HAS_ACTIVE_BOOKINGS.value)
    assert get_aircraft(ctx["aircraft"]["id"])["status"] == "AVAILABLE"
