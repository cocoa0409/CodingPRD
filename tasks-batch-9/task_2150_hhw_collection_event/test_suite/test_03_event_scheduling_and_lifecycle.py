"""Scheduling a collection event against the site's occupancy buffer and monthly
cap, the two independent state axes, and cancellation."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    NON_EXISTENT_UUID,
    SITE_APPROVER,
    ApiErrorId,
    assert_collection_event,
    assert_hours,
    create_event,
    create_event_payload,
    create_program,
    event_action,
    inspect_event,
    read_appointment,
    read_event,
    read_lane_assignment,
    read_program,
    read_staffer,
    setup_canon,
    setup_frozen_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_get_event_with_unknown_id_returns_event_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/get_event_with_unknown_id_returns_event_not_found
    """
    response = api.get_event(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_EVENT_NOT_FOUND, 404)


def test_scheduling_against_an_unknown_site_reports_the_missing_site(api):
    """PRD §2.5: "Foreign-key resolution inside the request body, evaluated in this
    declared order: `program_id`, then `site_id`, then `replaces_site_id`, then
    `event_id`, then `resident_id`, then `staffer_id`, then `appointment_id`, then
    `material_category_id`, then each element of `container_ids`, then
    `dropoff_line_id`. The same not-found codes apply, at HTTP 404."

    Design: Corner/entities/create_event_with_unknown_site_id_returns_site_not_found
    """
    program = create_program(eligible_jurisdiction_codes=["CO-DEN"])

    response = api.create_event(
        create_event_payload(program["id"], NON_EXISTENT_UUID), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_SITE_NOT_FOUND, 404)


def test_new_event_opens_planned_pending_inspection_with_no_capacity(api):
    """PRD §3.3: "A newly scheduled event opens with `lifecycle_status` of `PLANNED`
    and `containment_status` of `PENDING_INSPECTION`. Its `slot_capacity` computes to
    zero, because no lanes are staffed and no pad has been certified."
    PRD §3.3: "The coordinator may also state `min_viable_registrations`, the
    board-set floor of confirmed registrations below which the event is considered
    undersubscribed; it defaults to 20 when omitted and may not be negative."
    PRD §3.3: "`event_date` is the UTC calendar date of `window_start_utc` written as
    a plain `YYYY-MM-DD` string — it is the key on which staffing certification and
    monthly caps are judged."

    Design: Corner/state_machines/new_event_starts_in_planned_and_pending_inspection
    """
    ctx = setup_canon(3)
    payload = create_event_payload(ctx["program_id"], ctx["site_id"])
    payload.pop("min_viable_registrations")

    response = api.create_event(payload, COORDINATOR)
    event = validate_success(response, 201)

    assert_collection_event(event)
    assert event["lifecycle_status"] == "PLANNED"
    assert event["containment_status"] == "PENDING_INSPECTION"
    assert event["slot_capacity"] == 0
    assert event["reserved_slot_count"] == 0
    assert event["min_viable_registrations"] == 20
    assert_hours(event["window_duration_hours"], 12.0, "window_duration_hours")
    assert event["event_date"] == "2026-09-12"
    assert event["version"] == 1


def test_cancelling_an_already_cancelled_event_is_refused(api):
    """PRD §3.3: "Both `RECONCILED` and `CANCELLED` are terminal on the lifecycle
    axis."
    PRD §2.5: "The requested action is a declared transition out of the target row's
    current state on the relevant axis — otherwise `ERR_INVALID_STATE_TRANSITION`
    (HTTP 409). This includes any action attempted against a terminal state."

    Design: Corner/state_machines/cancel_already_cancelled_event_returns_invalid_state
    """
    ctx = setup_canon(5)
    cancelled = event_action(ctx["event_id"], "CANCEL", cancel_reason="BUDGET_CUT")
    assert cancelled["lifecycle_status"] == "CANCELLED"

    response = api.event_transition(
        ctx["event_id"], {"action": "CANCEL", "cancel_reason": "SECOND_ATTEMPT"}, COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    assert read_event(ctx["event_id"])["cancel_reason"] == "BUDGET_CUT"


def test_registration_cannot_open_on_an_uninspected_pad(api):
    """PRD §3.3: "Opening registration moves `SITE_CONFIRMED →
    OPEN_FOR_REGISTRATION` and is the most heavily gated transition on the axis: the
    event's containment axis must read exactly `COMPLIANT`, the logical clock must
    still be strictly before `window_start_utc`, and the program's posture must be
    fully `OPEN` — a merely restricted program cannot open registrations, and that
    rejection carries `ERR_PROGRAM_RESTRICTED`, while a frozen one carries
    `ERR_PROGRAM_FROZEN` and a non-compliant pad carries `ERR_CONTAINMENT_DEFICIENT`."

    Design: Corner/state_machines/open_registration_before_containment_pass_returns_containment_deficient
    """
    ctx = setup_canon(6)

    response = api.event_transition(
        ctx["event_id"], {"action": "OPEN_REGISTRATION"}, COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_CONTAINMENT_DEFICIENT, 409)

    assert read_event(ctx["event_id"])["lifecycle_status"] == "SITE_CONFIRMED"


def test_event_cannot_start_before_the_logical_clock_reaches_its_window(api):
    """PRD §3.3: "Starting the event moves `OPEN_FOR_REGISTRATION → IN_PROGRESS` and
    requires three things: the logical clock must have reached or passed
    `window_start_utc`, the containment axis must read either `COMPLIANT` or
    `REMEDIATED`, and `open_lane_count` must be at least one."
    PRD §2.9: "Before any client moves it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/state_machines/event_start_before_window_open_returns_invalid_state
    """
    ctx = setup_canon(10)

    response = api.event_transition(ctx["event_id"], {"action": "START"}, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    assert read_event(ctx["event_id"])["lifecycle_status"] == "OPEN_FOR_REGISTRATION"


def test_third_event_in_one_calendar_month_breaches_the_site_cap(api):
    """PRD §3.3: "No site may host more than two non-cancelled events whose
    `event_date` falls in the same UTC calendar month, expressed as year-and-month.
    When a site already hosts two such events, a third is rejected with
    `ERR_SITE_MONTHLY_EVENT_CAP`."

    Design: Corner/validations/third_event_in_same_calendar_month_returns_site_monthly_cap
    """
    ctx = setup_canon(3)
    create_event(
        ctx["program_id"],
        ctx["site_id"],
        window_start_utc="2026-09-01T08:00:00.000Z",
        window_end_utc="2026-09-01T20:00:00.000Z",
    )
    create_event(
        ctx["program_id"],
        ctx["site_id"],
        window_start_utc="2026-09-06T08:00:00.000Z",
        window_end_utc="2026-09-06T20:00:00.000Z",
    )

    response = api.create_event(
        create_event_payload(
            ctx["program_id"],
            ctx["site_id"],
            window_start_utc="2026-09-20T08:00:00.000Z",
            window_end_utc="2026-09-20T20:00:00.000Z",
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_SITE_MONTHLY_EVENT_CAP, 409)

    _, meta = validate_paginated(
        api.list_events(COORDINATOR, params={"site_id": ctx["site_id"]})
    )
    assert meta["total_count"] == 2


def test_touching_the_buffered_closing_endpoint_is_a_site_conflict(api):
    """PRD §3.3: "Site availability is judged on a **closed** interval widened
    symmetrically on both sides. Every non-cancelled event already at that site
    projects an occupancy band running from two full days before its own
    `window_start_utc` to two full days after its own `window_end_utc` — that is, a
    mobilisation-and-teardown buffer of forty-eight hours on each side."
    PRD §3.3: "Because both intervals are closed, touching a buffered endpoint
    exactly is a conflict, not a clean fit: a new event beginning at precisely the
    instant two days after an existing event's window ended is refused."

    Design: Difficulty/resource_temporal_overlap/site_closed_interval_with_symmetric_mobilisation_buffer
    """
    ctx = setup_canon(3)
    first = create_event(ctx["program_id"], ctx["site_id"])
    assert first["event_date"] == "2026-09-12"

    response = api.create_event(
        create_event_payload(
            ctx["program_id"],
            ctx["site_id"],
            window_start_utc="2026-09-14T20:00:00.000Z",
            window_end_utc="2026-09-14T22:00:00.000Z",
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_SITE_INTERVAL_CONFLICT, 409)


def test_one_minute_past_the_buffered_endpoint_schedules_cleanly(api):
    """PRD §3.3: "Because both intervals are closed, touching a buffered endpoint
    exactly is a conflict, not a clean fit: a new event beginning at precisely the
    instant two days after an existing event's window ended is refused."
    PRD §3.3: "`window_duration_hours` is the elapsed time between the two window
    bounds expressed in hours and rounded half up to two decimal places; an
    eight-in-the-morning to eight-in-the-evening window is `12.00`."

    Design: Difficulty/resource_temporal_overlap/site_closed_interval_with_symmetric_mobilisation_buffer
    """
    ctx = setup_canon(3)
    create_event(ctx["program_id"], ctx["site_id"])

    response = api.create_event(
        create_event_payload(
            ctx["program_id"],
            ctx["site_id"],
            window_start_utc="2026-09-14T20:01:00.000Z",
            window_end_utc="2026-09-14T22:00:00.000Z",
        ),
        COORDINATOR,
    )
    second = validate_success(response, 201)

    assert second["event_date"] == "2026-09-14"
    assert_hours(second["window_duration_hours"], 1.98, "window_duration_hours")
    assert second["lifecycle_status"] == "PLANNED"
    assert second["containment_status"] == "PENDING_INSPECTION"


def test_lifecycle_axis_advances_without_disturbing_the_containment_axis(api):
    """PRD §3.6: "The containment axis is the second, wholly independent state axis
    carried on the collection event row. It moves under a `ContainmentInspector`'s
    hand alone, it never waits on the lifecycle axis, and the lifecycle axis never
    waits on it — an event can be closed while its pad is deficient, and a pad can be
    certified compliant while the event is still merely planned."
    PRD §3.6: "From `PENDING_INSPECTION`, a passing inspection moves the axis to
    `COMPLIANT` and recomputes `slot_capacity` — which is what finally lifts the
    containment leg of §3.4 off zero."

    Design: Difficulty/non_linear_state_machine/event_lifecycle_and_containment_axes_advance_independently
    """
    ctx = setup_canon(5)
    assert ctx["event"]["lifecycle_status"] == "PLANNED"
    assert ctx["event"]["containment_status"] == "PENDING_INSPECTION"

    confirmed = event_action(ctx["event_id"], "CONFIRM_SITE")
    assert confirmed["lifecycle_status"] == "SITE_CONFIRMED"
    assert confirmed["containment_status"] == "PENDING_INSPECTION", (
        "Confirming the site does not touch the containment axis"
    )

    inspected = inspect_event(ctx["event_id"], "PASS", finding_code="PAD-OK")
    assert inspected["lifecycle_status"] == "SITE_CONFIRMED"
    assert inspected["containment_status"] == "COMPLIANT"

    opened = event_action(ctx["event_id"], "OPEN_REGISTRATION")
    assert opened["lifecycle_status"] == "OPEN_FOR_REGISTRATION"
    assert opened["containment_status"] == "COMPLIANT"


def test_containment_axis_walks_on_while_the_lifecycle_axis_stays_pinned(api):
    """PRD §3.6: "The consequential transition is a pad that fails after it had
    passed — `COMPLIANT → DEFICIENT` — and it cascades four levels deep."
    PRD §3.6: "Recovery is deliberately staged and cannot be short-circuited. A
    passing inspection on a deficient pad moves the axis to `REMEDIATED` — **never
    straight to `COMPLIANT`**."

    Design: Difficulty/non_linear_state_machine/event_lifecycle_and_containment_axes_advance_independently
    """
    ctx = setup_canon(10)

    failed = inspect_event(ctx["event_id"], "FAIL", finding_code="DRAIN-UNCOVERED")
    assert failed["containment_status"] == "DEFICIENT"
    assert failed["lifecycle_status"] == "OPEN_FOR_REGISTRATION"

    remediated = inspect_event(
        ctx["event_id"],
        "PASS",
        finding_code="DRAIN-COVERED",
        remediation_note="Storm drain mat deployed",
    )
    assert remediated["containment_status"] == "REMEDIATED"
    assert remediated["lifecycle_status"] == "OPEN_FOR_REGISTRATION"
    assert read_program(ctx["program_id"])["open_containment_deficiency_count"] == 0


def test_cancelling_an_open_event_cancels_its_booking_and_releases_its_lane(api):
    """PRD §3.3: "Cancelling from `OPEN_FOR_REGISTRATION` does both halves: every
    appointment of the event sitting `REQUESTED`, `CONFIRMED` or `WAITLISTED`
    transitions to `CANCELLED` with a `cancel_reason` of `EVENT_CANCELLED`, processed
    in `created_at` ascending order, and because those appointments were cancelled
    each affected resident's `annual_quantity_reserved_kg` is recomputed and the
    event's `reserved_slot_count` falls to zero; then, exactly as in the
    `SITE_CONFIRMED` branch, every `ACTIVE` lane assignment is released with a
    `released_reason` of `EVENT_CANCELLED` in `created_at` ascending order."

    Design: Difficulty/transitive_cascade/event_cancellation_cascades_back_to_open_posture_depth4
    """
    ctx = setup_canon(
        13,
        program={"cost_per_participant_ceiling_cents": 30_000},
        appointment={"declared_total_kg": 9.0},
    )

    response = api.event_transition(
        ctx["event_id"], {"action": "CANCEL", "cancel_reason": "SITE_FLOODED"}, COORDINATOR
    )
    cancelled = validate_success(response, 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    appointment = read_appointment(ctx["appointment_id"])
    assert appointment["status"] == "CANCELLED"
    assert appointment["cancel_reason"] == "EVENT_CANCELLED"
    assert read_lane_assignment(ctx["lane_id"])["status"] == "RELEASED"


def test_cancellation_returns_the_hours_and_relaxes_the_programme_posture(api):
    """PRD §3.3: "Cancelling from `SITE_CONFIRMED` releases staffing: every lane
    assignment of the event still `ACTIVE` transitions to `RELEASED` with a
    `released_reason` of `EVENT_CANCELLED`, processed in `created_at` ascending order,
    and because those assignments were released each affected staffer's
    `assigned_hours` is recomputed while the event's own `certified_staff_hours` and
    `staffing_cost_cents` fall to zero."
    PRD §2.8: "Only events currently open for registration participate in the
    projected-cost clause; events that are planned, site-confirmed, in progress,
    closed, reconciled or cancelled are excluded from it entirely."
    PRD §2.8: "That counter is monotonic: it never decrements when the posture
    relaxes again."

    Design: Difficulty/transitive_cascade/event_cancellation_cascades_back_to_open_posture_depth4
    """
    ctx = setup_canon(
        13,
        program={"cost_per_participant_ceiling_cents": 30_000},
        appointment={"declared_total_kg": 9.0},
    )
    assert_hours(ctx["lane"]["duration_hours"], 12.0, "lane duration")

    before = read_program(ctx["program_id"])
    assert before["posture"] == "RESTRICTED"
    assert before["budget_alert_count"] == 1

    cancelled = event_action(ctx["event_id"], "CANCEL", cancel_reason="SITE_FLOODED")
    assert_hours(cancelled["certified_staff_hours"], 0.0, "certified_staff_hours")
    assert cancelled["staffing_cost_cents"] == 0
    assert cancelled["open_lane_count"] == 0
    assert cancelled["slot_capacity"] == 0

    assert_hours(read_staffer(ctx["staffer_id"])["assigned_hours"], 0.0, "assigned_hours")

    after = read_program(ctx["program_id"])
    assert after["posture"] == "OPEN"
    assert after["budget_alert_count"] == 1, "The alert counter never decrements"


def test_site_approving_inspector_may_not_certify_that_sites_event(api):
    """PRD §2.1: "When the acting inspector's `X-User-ID` equals the site's
    `approved_by_user_id`, the inspection is rejected with
    `ERR_INSPECTOR_NOT_INDEPENDENT` (HTTP 403)."
    PRD §3.6: "Two preconditions guard every inspection regardless of result: the
    event's lifecycle axis must not have reached `RECONCILED` or `CANCELLED`, and the
    acting inspector must be independent of the site's approving inspector as §2.1
    requires, which is enforced with `ERR_INSPECTOR_NOT_INDEPENDENT`."

    Design: Corner/roles/site_approving_inspector_cannot_file_that_sites_event_inspection
    """
    ctx = setup_canon(6)

    response = api.file_containment_inspection(
        ctx["event_id"], {"result": "PASS", "finding_code": "PAD-OK"}, SITE_APPROVER
    )
    validate_error(response, ApiErrorId.ERR_INSPECTOR_NOT_INDEPENDENT, 403)

    event = read_event(ctx["event_id"])
    assert event["containment_status"] == "PENDING_INSPECTION"
    assert event["containment_findings"] == [], "A rejected inspection appends nothing"


def test_two_deficient_events_freeze_the_programme_against_new_scheduling(api):
    """PRD §2.8: "The program is `FROZEN` when the committed total is greater than
    or equal to `budget_cents`, or when `open_containment_deficiency_count` has
    reached two or more."
    PRD §2.8: "A `FROZEN` posture blocks event creation, site confirmation, opening
    registration, appointment confirmation and promotion, container sealing, and
    manifest creation — those requests are rejected with `ERR_PROGRAM_FROZEN`."

    Design: Corner/cross_cutting_complexity_layers/frozen_program_blocks_new_event_creation
    """
    ctx = setup_frozen_program()

    assert ctx["program_after_one"]["open_containment_deficiency_count"] == 1
    assert ctx["program_after_one"]["posture"] == "OPEN", (
        "One deficiency is below the freeze threshold"
    )
    assert ctx["program"]["open_containment_deficiency_count"] == 2
    assert ctx["program"]["posture"] == "FROZEN"
    assert ctx["program"]["budget_alert_count"] == 1

    response = api.create_event(
        create_event_payload(
            ctx["program_id"],
            ctx["site_id"],
            window_start_utc="2026-11-14T08:00:00.000Z",
            window_end_utc="2026-11-14T20:00:00.000Z",
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_FROZEN, 409)

    _, meta = validate_paginated(
        api.list_events(COORDINATOR, params={"program_id": ctx["program_id"]})
    )
    assert meta["total_count"] == 2


def test_administrative_override_cannot_lift_a_frozen_posture(api):
    """PRD §2.8: "When `posture_override` holds the value `OPEN` and the logical
    clock has not yet reached `posture_override_expires_utc`, the effective `posture`
    is reported as `OPEN` — **but only when the raw posture is not `FROZEN`**. An
    override can lift a restriction; it can never lift a freeze."

    Design: Corner/cross_cutting_complexity_layers/posture_override_does_not_lift_frozen_posture
    """
    ctx = setup_frozen_program()

    response = api.set_posture_override(
        ctx["program_id"],
        {
            "posture_override": "OPEN",
            "posture_override_expires_utc": "2026-12-31T00:00:00.000Z",
        },
        ADMIN,
    )
    program = validate_success(response, 200)

    assert program["posture_override"] == "OPEN"
    assert program["posture"] == "FROZEN", "An override never rewrites a frozen posture"

    blocked = api.create_event(
        create_event_payload(
            ctx["program_id"],
            ctx["site_id"],
            window_start_utc="2026-11-14T08:00:00.000Z",
            window_end_utc="2026-11-14T20:00:00.000Z",
        ),
        COORDINATOR,
    )
    validate_error(blocked, ApiErrorId.ERR_PROGRAM_FROZEN, 409)

    _, meta = validate_paginated(
        api.list_events(COORDINATOR, params={"program_id": ctx["program_id"]})
    )
    assert meta["total_count"] == 2
