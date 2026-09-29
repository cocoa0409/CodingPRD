"""Confirmation preconditions, the capacity line, the containment cascade onto
confirmed bookings, the promotion sweep and the closing sweep."""

from test_helpers import (
    ADMIN,
    CLERK,
    COORDINATOR,
    ApiErrorId,
    add_resident_with_appointment,
    appointment_action,
    assert_kg,
    book_appointment,
    event_action,
    inspect_event,
    read_appointment,
    read_event,
    read_program,
    read_resident,
    release_lane,
    assign_lane,
    set_clock,
    setup_canon,
    setup_deficiency_cascade_scenario,
    setup_two_confirmed_appointments,
    validate_error,
    validate_success,
)


def test_business_origin_appointment_cannot_be_confirmed(api):
    """PRD §3.5: "The event must be `OPEN_FOR_REGISTRATION`; the event's containment
    axis must read `COMPLIANT` or `REMEDIATED`; the resident must be `ELIGIBLE`, or
    the request is refused with `ERR_RESIDENT_NOT_ELIGIBLE`; the appointment's
    `waste_origin` must be `HOUSEHOLD`, or it is refused with
    `ERR_BUSINESS_WASTE_EXCLUDED`; the program's posture must be fully `OPEN`; and
    there must be room — the event's `reserved_slot_count` plus one must be no greater
    than its `slot_capacity`, or the request is refused with
    `ERR_EVENT_SLOT_CAPACITY_EXCEEDED`."
    PRD §3.5: "Note that a `BUSINESS` declaration does not block the booking itself —
    a business generator may legitimately hold a `REQUESTED` appointment and be dealt
    with at the desk — it blocks everything that comes after."

    Design: Corner/validations/confirm_business_origin_appointment_returns_excluded_error
    """
    ctx = setup_canon(
        13, appointment={"waste_origin": "BUSINESS", "declared_total_kg": 40.0}
    )
    assert ctx["appointment"]["waste_origin"] == "BUSINESS"
    assert ctx["appointment"]["status"] == "REQUESTED"

    response = api.appointment_transition(
        ctx["appointment_id"], {"action": "CONFIRM"}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_BUSINESS_WASTE_EXCLUDED, 422)

    assert read_appointment(ctx["appointment_id"])["status"] == "REQUESTED"
    assert read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"] == 0


def test_unverified_resident_cannot_have_their_booking_confirmed(api):
    """PRD §3.5: "The event must be `OPEN_FOR_REGISTRATION`; the event's containment
    axis must read `COMPLIANT` or `REMEDIATED`; the resident must be `ELIGIBLE`, or
    the request is refused with `ERR_RESIDENT_NOT_ELIGIBLE`; the appointment's
    `waste_origin` must be `HOUSEHOLD`, or it is refused with
    `ERR_BUSINESS_WASTE_EXCLUDED`; the program's posture must be fully `OPEN`; and
    there must be room — the event's `reserved_slot_count` plus one must be no greater
    than its `slot_capacity`, or the request is refused with
    `ERR_EVENT_SLOT_CAPACITY_EXCEEDED`."
    PRD §3.5: "Both doors produce a resident in `PENDING_VERIFICATION` with a
    `version` of 1, a null `verified_jurisdiction_code`, and zeroed ledgers:
    `annual_quantity_reserved_kg`, `annual_quantity_settled_kg`,
    `no_show_strike_count` and `completed_visit_count` all start at zero."

    Design: Corner/validations/confirm_unverified_resident_returns_not_eligible
    """
    ctx = setup_canon(11)
    assert ctx["resident"]["eligibility_status"] == "PENDING_VERIFICATION"
    appointment = book_appointment(
        ctx["event_id"], ctx["resident"], [ctx["category_id"]], declared_total_kg=8.0
    )

    response = api.appointment_transition(appointment["id"], {"action": "CONFIRM"}, CLERK)
    validate_error(response, ApiErrorId.ERR_RESIDENT_NOT_ELIGIBLE, 403)

    assert read_appointment(appointment["id"])["status"] == "REQUESTED"


def test_confirmation_beyond_the_slot_capacity_is_refused(api):
    """PRD §3.5: "The event must be `OPEN_FOR_REGISTRATION`; the event's containment
    axis must read `COMPLIANT` or `REMEDIATED`; the resident must be `ELIGIBLE`, or
    the request is refused with `ERR_RESIDENT_NOT_ELIGIBLE`; the appointment's
    `waste_origin` must be `HOUSEHOLD`, or it is refused with
    `ERR_BUSINESS_WASTE_EXCLUDED`; the program's posture must be fully `OPEN`; and
    there must be room — the event's `reserved_slot_count` plus one must be no greater
    than its `slot_capacity`, or the request is refused with
    `ERR_EVENT_SLOT_CAPACITY_EXCEEDED`."

    Design: Corner/validations/confirm_beyond_slot_capacity_returns_event_slot_capacity_exceeded
    """
    ctx = setup_canon(10, lane={"end_utc": "2026-09-12T08:15:00.000Z"})
    assert read_event(ctx["event_id"])["slot_capacity"] == 1

    add_resident_with_appointment(
        ctx,
        full_name="Ana Ruiz",
        jurisdiction="CO-ARV",
        declared_total_kg=5.0,
        slot_start_utc="2026-09-12T09:00:00.000Z",
        confirm=True,
    )
    second = add_resident_with_appointment(
        ctx, full_name="Ben Ortiz", jurisdiction="CO-DEN", declared_total_kg=5.0
    )

    response = api.appointment_transition(
        second["appointment"]["id"], {"action": "CONFIRM"}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_EVENT_SLOT_CAPACITY_EXCEEDED, 409)

    assert read_appointment(second["appointment"]["id"])["status"] == "REQUESTED"
    assert read_event(ctx["event_id"])["reserved_slot_count"] == 1
    assert (
        read_resident(second["resident"]["id"])["annual_quantity_reserved_kg"] == 0
    )


def test_restricted_programme_stops_confirming_appointments(api):
    """PRD §2.8: "A `RESTRICTED` posture blocks a strictly narrower set: opening
    registration, and appointment confirmation and promotion — those requests are
    rejected with `ERR_PROGRAM_RESTRICTED`."
    PRD §2.8: "Failing that, the program is `RESTRICTED` when the committed total has
    reached or passed eighty-five percent of `budget_cents`, or when at least one
    collection event of the program is currently open for registration and that
    event's `projected_cost_per_participant_cents` is strictly greater than the
    program's `cost_per_participant_ceiling_cents`."

    Design: Corner/cross_cutting_complexity_layers/restricted_program_blocks_appointment_confirmation
    """
    ctx = setup_canon(
        13,
        program={"cost_per_participant_ceiling_cents": 30_000},
        appointment={"declared_total_kg": 8.0},
    )
    event = read_event(ctx["event_id"])
    assert event["projected_cost_per_participant_cents"] == 50400
    assert read_program(ctx["program_id"])["posture"] == "RESTRICTED"

    response = api.appointment_transition(
        ctx["appointment_id"], {"action": "CONFIRM"}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_RESTRICTED, 409)

    assert read_appointment(ctx["appointment_id"])["status"] == "REQUESTED"
    assert read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"] == 0
    assert read_event(ctx["event_id"])["reserved_slot_count"] == 0


def test_open_override_lifts_the_restriction_and_lets_the_booking_confirm(api):
    """PRD §2.8: "When `posture_override` holds the value `OPEN` and the logical
    clock has not yet reached `posture_override_expires_utc`, the effective `posture`
    is reported as `OPEN` — **but only when the raw posture is not `FROZEN`**. An
    override can lift a restriction; it can never lift a freeze."
    PRD §3.1: "An administrator may record a posture override at any time by
    supplying `posture_override` and `posture_override_expires_utc`. The override is
    written to the program, the posture is immediately recomputed under the rules of
    §2.8, and the program's `version` advances by one."

    Design: Corner/cross_cutting_complexity_layers/posture_override_lifts_restricted_and_unblocks_confirmation
    """
    ctx = setup_canon(
        13,
        program={"cost_per_participant_ceiling_cents": 30_000},
        appointment={"declared_total_kg": 8.0},
    )
    assert read_program(ctx["program_id"])["posture"] == "RESTRICTED"

    program = validate_success(
        api.set_posture_override(
            ctx["program_id"],
            {
                "posture_override": "OPEN",
                "posture_override_expires_utc": "2026-12-31T00:00:00.000Z",
            },
            ADMIN,
        ),
        200,
    )
    assert program["posture_override"] == "OPEN"
    assert program["posture"] == "OPEN"

    confirmed = validate_success(
        api.appointment_transition(ctx["appointment_id"], {"action": "CONFIRM"}, CLERK), 200
    )
    assert confirmed["status"] == "CONFIRMED"
    assert_kg(confirmed["reserved_kg"], 8.0, "reserved_kg")

    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"], 8.0, "resident ledger"
    )
    event = read_event(ctx["event_id"])
    assert event["reserved_slot_count"] == 1
    assert event["projected_cost_per_participant_cents"] == 50400


def test_clerk_promotion_off_the_waitlist_takes_the_reservation(api):
    """PRD §3.5: "Waitlisting moves `REQUESTED → WAITLISTED` and is a clerk-only
    action for the case where the event is full. It requires only that the event is
    `OPEN_FOR_REGISTRATION` and the resident is `ELIGIBLE` — but the business-origin
    exclusion applies here too, so a `BUSINESS` appointment cannot be parked on the
    waitlist either. The appointment's `waitlist_reason` is set to `CAPACITY`, and
    crucially **no reservation is taken**: the resident's
    `annual_quantity_reserved_kg` is untouched and the event's `reserved_slot_count`
    does not move."
    PRD §3.5: "On success `waitlist_reason` is cleared to null, `reserved_kg` becomes
    `declared_total_kg`, the resident's `annual_quantity_reserved_kg` rises by
    `declared_total_kg`, and the event's `reserved_slot_count` rises by one with
    `projected_cost_per_participant_cents` recomputed."

    Design: Corner/state_machines/promote_waitlisted_appointment_takes_the_reservation
    """
    ctx = setup_canon(13, appointment={"declared_total_kg": 8.0})

    waitlisted = validate_success(
        api.appointment_transition(ctx["appointment_id"], {"action": "WAITLIST"}, CLERK), 200
    )
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["waitlist_reason"] == "CAPACITY"
    assert_kg(waitlisted["reserved_kg"], 0.0, "reserved_kg while waitlisted")

    promoted = validate_success(
        api.appointment_transition(ctx["appointment_id"], {"action": "PROMOTE"}, CLERK), 200
    )
    assert promoted["status"] == "CONFIRMED"
    assert promoted["waitlist_reason"] is None
    assert_kg(promoted["reserved_kg"], 8.0, "reserved_kg after promotion")

    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"], 8.0, "resident ledger"
    )
    assert read_event(ctx["event_id"])["reserved_slot_count"] == 1


def test_closing_expires_the_waitlist_and_no_shows_the_confirmed(api):
    """PRD §3.3: "Closing sweeps the day's loose ends in two passes, each over the
    event's appointments in `created_at` ascending order. First, every appointment
    still sitting `WAITLISTED` transitions to `EXPIRED`. Second, every appointment
    still sitting `REQUESTED` or `CONFIRMED` transitions to `NO_SHOW`, releasing
    whatever reservation it held."
    PRD §3.7: "Second, because the appointment has entered `NO_SHOW`, the resident's
    `no_show_strike_count` is recomputed; when it reaches two or more, the resident
    transitions `ELIGIBLE → SUSPENDED` automatically."

    Design: Corner/state_machines/event_close_expires_waitlisted_and_no_shows_confirmed
    """
    ctx = setup_canon(14, appointment={"declared_total_kg": 11.0})
    second = add_resident_with_appointment(
        ctx, full_name="Ben Ortiz", jurisdiction="CO-DEN", declared_total_kg=6.0
    )
    waitlisted = appointment_action(second["appointment"]["id"], "WAITLIST")
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["waitlist_reason"] == "CAPACITY"

    set_clock("2026-09-12T09:00:00.000Z")
    event_action(ctx["event_id"], "START")
    set_clock("2026-09-12T21:00:00.000Z")

    closed = validate_success(
        api.event_transition(ctx["event_id"], {"action": "CLOSE"}, COORDINATOR), 200
    )
    assert closed["lifecycle_status"] == "CLOSED"
    assert closed["reserved_slot_count"] == 0
    assert closed["participant_count"] == 0

    assert read_appointment(ctx["appointment_id"])["status"] == "NO_SHOW"
    assert read_appointment(second["appointment"]["id"])["status"] == "EXPIRED"

    first_resident = read_resident(ctx["resident_id"])
    assert first_resident["no_show_strike_count"] == 1
    assert first_resident["eligibility_status"] == "ELIGIBLE", (
        "One strike is below the automatic suspension threshold"
    )
    assert_kg(first_resident["annual_quantity_reserved_kg"], 0.0, "released reservation")
    assert read_resident(second["resident"]["id"])["no_show_strike_count"] == 0


def test_recovery_sweep_promotes_in_queue_order_and_stops_at_capacity(api):
    """PRD §3.6: "Candidates are ordered by `created_at` ascending, with ties broken
    by `queue_seq` ascending; the appointment's `id` is never consulted."
    PRD §3.6: "Each candidate in turn is promoted to `CONFIRMED` — clearing
    `waitlist_reason` and re-reserving its `declared_total_kg` on the resident — but
    only when three conditions all hold at that moment: the event's
    `reserved_slot_count` plus one is no greater than its `slot_capacity`, the
    resident is `ELIGIBLE`, and the program's posture is `OPEN`."
    PRD §3.6: "Because capacity is re-read after every promotion, however, a sweep
    that has already filled the event will fail the capacity test for every remaining
    candidate and leave them all in place."

    Design: Corner/calculations/waitlist_sweep_promotes_in_created_at_order_up_to_capacity
    """
    ctx = setup_two_confirmed_appointments()

    inspect_event(ctx["event_id"], "FAIL", finding_code="BERM-CRACK")
    release_lane(ctx["lane_id"])
    narrow_lane = assign_lane(
        ctx["event_id"],
        ctx["staffer_id"],
        start_utc="2026-09-12T08:00:00.000Z",
        end_utc="2026-09-12T08:15:00.000Z",
    )
    assert narrow_lane["duration_hours"] == 0.25

    recovered = inspect_event(
        ctx["event_id"],
        "PASS",
        finding_code="BERM-PATCHED",
        remediation_note="Berm re-sealed",
    )
    assert recovered["containment_status"] == "REMEDIATED"
    assert recovered["slot_capacity"] == 1, "min(144 lane, 1 staffing, 25 derated pad)"
    assert recovered["reserved_slot_count"] == 1

    first = read_appointment(ctx["first"]["appointment"]["id"])
    second = read_appointment(ctx["second"]["appointment"]["id"])
    assert first["status"] == "CONFIRMED"
    assert first["waitlist_reason"] is None
    assert second["status"] == "WAITLISTED", "The sweep stops exactly at the capacity line"
    assert second["waitlist_reason"] == "CONTAINMENT_DEFICIENCY"

    assert_kg(
        read_resident(ctx["first"]["resident"]["id"])["annual_quantity_reserved_kg"],
        10.0,
        "promoted resident ledger",
    )
    assert_kg(
        read_resident(ctx["second"]["resident"]["id"])["annual_quantity_reserved_kg"],
        0.0,
        "skipped resident ledger",
    )


def test_confirmation_is_refused_while_the_pad_reads_deficient(api):
    """PRD §3.5: "Confirming an appointment moves `REQUESTED → CONFIRMED` and may be
    performed by the `EligibilityClerk` or by the owning `Resident`. It carries the
    longest precondition list in the system. The event must be
    `OPEN_FOR_REGISTRATION`; the event's containment axis must read `COMPLIANT` or
    `REMEDIATED`; the resident must be `ELIGIBLE`, or the request is refused with
    `ERR_RESIDENT_NOT_ELIGIBLE`; the appointment's `waste_origin` must be
    `HOUSEHOLD`, or it is refused with `ERR_BUSINESS_WASTE_EXCLUDED`; the program's
    posture must be fully `OPEN`; and there must be room — the event's
    `reserved_slot_count` plus one must be no greater than its `slot_capacity`, or the
    request is refused with `ERR_EVENT_SLOT_CAPACITY_EXCEEDED`."
    PRD §2.5: "The event's containment axis is neither deficient nor pending
    inspection, when confirming or promoting an appointment, checking a vehicle in,
    starting the event, or opening registration — otherwise `ERR_CONTAINMENT_DEFICIENT`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/appointment_confirm_depends_on_event_containment_axis
    """
    ctx = setup_canon(13, appointment={"declared_total_kg": 7.0})
    failed = inspect_event(ctx["event_id"], "FAIL", finding_code="BERM-CRACK")
    assert failed["containment_status"] == "DEFICIENT"
    assert failed["lifecycle_status"] == "OPEN_FOR_REGISTRATION"

    response = api.appointment_transition(
        ctx["appointment_id"], {"action": "CONFIRM"}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_CONTAINMENT_DEFICIENT, 409)


def test_deficient_pad_rejection_leaves_the_booking_and_ledgers_untouched(api):
    """PRD §2.4: "A rejected request writes nothing at all: no state change, no
    counter movement, no `version` increment, no `updated_at` refresh."
    PRD §2.5: "The event's containment axis is neither deficient nor pending
    inspection, when confirming or promoting an appointment, checking a vehicle in,
    starting the event, or opening registration — otherwise `ERR_CONTAINMENT_DEFICIENT`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/appointment_confirm_depends_on_event_containment_axis
    """
    ctx = setup_canon(13, appointment={"declared_total_kg": 7.0})
    inspect_event(ctx["event_id"], "FAIL", finding_code="BERM-CRACK")

    response = api.appointment_transition(
        ctx["appointment_id"], {"action": "CONFIRM"}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_CONTAINMENT_DEFICIENT, 409)

    assert read_appointment(ctx["appointment_id"])["status"] == "REQUESTED"
    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"],
        0.0,
        "annual_quantity_reserved_kg",
    )
    assert read_event(ctx["event_id"])["reserved_slot_count"] == 0


def test_event_already_started_beats_the_capacity_rule_on_confirmation(api):
    """PRD §2.5: "The target event is open for registration, when booking,
    confirming, waitlisting or promoting — otherwise
    `ERR_EVENT_NOT_ACCEPTING_REGISTRATIONS` (HTTP 409). This guards appointment
    creation and the confirm, waitlist and promote actions."
    PRD §2.5: "Event slot capacity, when confirming or promoting — otherwise
    `ERR_EVENT_SLOT_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD §2.5: "The rules below are evaluated in ascending priority order and the
    **first** rule that fails decides the response; no later rule is consulted, and no
    partial write occurs."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm_after_event_start
    """
    ctx = setup_canon(10, lane={"end_utc": "2026-09-12T08:15:00.000Z"})
    add_resident_with_appointment(
        ctx,
        full_name="Ana Ruiz",
        jurisdiction="CO-ARV",
        declared_total_kg=5.0,
        slot_start_utc="2026-09-12T09:00:00.000Z",
        confirm=True,
    )
    second = add_resident_with_appointment(
        ctx, full_name="Ben Ortiz", jurisdiction="CO-DEN", declared_total_kg=5.0
    )
    set_clock("2026-09-12T09:00:00.000Z")
    started = event_action(ctx["event_id"], "START")
    assert started["lifecycle_status"] == "IN_PROGRESS"
    assert started["slot_capacity"] == 1
    assert started["reserved_slot_count"] == 1

    response = api.appointment_transition(
        second["appointment"]["id"], {"action": "CONFIRM"}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_EVENT_NOT_ACCEPTING_REGISTRATIONS, 409)


def test_the_pre_empted_capacity_breach_writes_nothing(api):
    """PRD §2.5: "The rules below are evaluated in ascending priority order and the
    **first** rule that fails decides the response; no later rule is consulted, and no
    partial write occurs."
    PRD §2.4: "A rejected request writes nothing at all: no state change, no counter
    movement, no `version` increment, no `updated_at` refresh."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm_after_event_start
    """
    ctx = setup_canon(10, lane={"end_utc": "2026-09-12T08:15:00.000Z"})
    add_resident_with_appointment(
        ctx,
        full_name="Ana Ruiz",
        jurisdiction="CO-ARV",
        declared_total_kg=5.0,
        slot_start_utc="2026-09-12T09:00:00.000Z",
        confirm=True,
    )
    second = add_resident_with_appointment(
        ctx, full_name="Ben Ortiz", jurisdiction="CO-DEN", declared_total_kg=5.0
    )
    set_clock("2026-09-12T09:00:00.000Z")
    event_action(ctx["event_id"], "START")

    response = api.appointment_transition(
        second["appointment"]["id"], {"action": "CONFIRM"}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_EVENT_NOT_ACCEPTING_REGISTRATIONS, 409)

    assert read_appointment(second["appointment"]["id"])["status"] == "REQUESTED"
    assert read_event(ctx["event_id"])["reserved_slot_count"] == 1


def test_deficiency_waitlists_every_confirmed_booking_and_releases_its_mass(api):
    """PRD §3.6: "Second, because the event has become deficient, every appointment
    of that event currently `CONFIRMED` transitions to `WAITLISTED` with a
    `waitlist_reason` of `CONTAINMENT_DEFICIENCY`, processed in `created_at` ascending
    order; each such appointment's `reserved_kg` falls to zero and its resident's
    `annual_quantity_reserved_kg` is reduced by that appointment's
    `declared_total_kg`."

    Design: Difficulty/transitive_cascade/containment_failure_cascades_to_program_posture_depth4
    """
    ctx = setup_deficiency_cascade_scenario()

    failed = inspect_event(ctx["event_id"], "FAIL", finding_code="SUMP-OVERFLOW")
    assert failed["containment_status"] == "DEFICIENT"

    for slot in ("first", "second"):
        appointment = read_appointment(ctx[slot]["appointment"]["id"])
        assert appointment["status"] == "WAITLISTED"
        assert appointment["waitlist_reason"] == "CONTAINMENT_DEFICIENCY"
        assert_kg(
            read_resident(ctx[slot]["resident"]["id"])["annual_quantity_reserved_kg"],
            0.0,
            f"{slot} resident ledger",
        )

    assert failed["slot_capacity"] == 0


def test_released_reservations_drive_the_projection_past_the_ceiling(api):
    """PRD §3.6: "Third, because those reservations were released, the event's
    `reserved_slot_count` falls and its `projected_cost_per_participant_cents` is
    recomputed as `staffing_cost_cents` divided by the greater of
    `reserved_slot_count` and one, with the fraction discarded — which is why a
    deficiency makes the event look **more** expensive per head, not less: the
    staffing bill is already committed and there are now fewer participants to spread
    it over."
    PRD §2.8: "Each time the effective posture moves from `OPEN` to `RESTRICTED`,
    from `OPEN` to `FROZEN`, or from `RESTRICTED` to `FROZEN` within a single request,
    `budget_alert_count` is incremented by one."

    Design: Difficulty/transitive_cascade/containment_failure_cascades_to_program_posture_depth4
    """
    ctx = setup_deficiency_cascade_scenario()
    assert ctx["event"]["certified_staff_hours"] == 14.0
    assert ctx["event"]["staffing_cost_cents"] == 58800
    assert ctx["event"]["reserved_slot_count"] == 2
    assert ctx["event"]["projected_cost_per_participant_cents"] == 29400
    assert ctx["program"]["posture"] == "OPEN"
    assert ctx["program"]["budget_alert_count"] == 0

    failed = inspect_event(ctx["event_id"], "FAIL", finding_code="SUMP-OVERFLOW")
    assert failed["reserved_slot_count"] == 0
    assert failed["projected_cost_per_participant_cents"] == 58800

    program = read_program(ctx["program_id"])
    assert program["posture"] == "RESTRICTED"
    assert program["budget_alert_count"] == 1
    assert program["open_containment_deficiency_count"] == 1


def test_deficiency_pushes_a_confirmed_booking_onto_the_waitlist(api):
    """PRD §3.6: "Second, because the event has become deficient, every appointment
    of that event currently `CONFIRMED` transitions to `WAITLISTED` with a
    `waitlist_reason` of `CONTAINMENT_DEFICIENCY`, processed in `created_at` ascending
    order; each such appointment's `reserved_kg` falls to zero and its resident's
    `annual_quantity_reserved_kg` is reduced by that appointment's
    `declared_total_kg`."

    Design: Difficulty/non_linear_state_machine/appointment_confirmed_waitlisted_confirmed_cycle
    """
    ctx = setup_canon(14)
    assert ctx["appointment"]["status"] == "CONFIRMED"
    assert_kg(ctx["appointment"]["reserved_kg"], 18.5, "reserved_kg")

    inspect_event(ctx["event_id"], "FAIL", finding_code="BERM-CRACK")

    waitlisted = read_appointment(ctx["appointment_id"])
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["waitlist_reason"] == "CONTAINMENT_DEFICIENCY"
    assert_kg(waitlisted["reserved_kg"], 0.0, "reserved_kg after the deficiency")


def test_remediation_sweeps_the_displaced_booking_back_to_confirmed(api):
    """PRD §3.6: "Both recovery transitions — into `REMEDIATED` and into
    `COMPLIANT` — run an automatic sweep that tries to put back the people the
    deficiency displaced. The candidate set is precisely the appointments of this
    event whose status is `WAITLISTED` **and** whose `waitlist_reason` is
    `CONTAINMENT_DEFICIENCY`."
    PRD §3.6: "Entering `REMEDIATED` recomputes `slot_capacity` **with** the half
    derate of §3.4; entering `COMPLIANT` recomputes it **without** the derate,
    restoring full containment throughput."

    Design: Difficulty/non_linear_state_machine/appointment_confirmed_waitlisted_confirmed_cycle
    """
    ctx = setup_canon(14)
    inspect_event(ctx["event_id"], "FAIL", finding_code="BERM-CRACK")

    remediated = inspect_event(
        ctx["event_id"],
        "PASS",
        finding_code="BERM-PATCHED",
        remediation_note="Berm re-sealed",
    )
    assert remediated["containment_status"] == "REMEDIATED"
    assert remediated["slot_capacity"] == 25
    assert remediated["reserved_slot_count"] == 1

    recycled = read_appointment(ctx["appointment_id"])
    assert recycled["status"] == "CONFIRMED"
    assert recycled["waitlist_reason"] is None
    assert_kg(recycled["reserved_kg"], 18.5, "reserved_kg after promotion")
    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"],
        18.5,
        "annual_quantity_reserved_kg",
    )
