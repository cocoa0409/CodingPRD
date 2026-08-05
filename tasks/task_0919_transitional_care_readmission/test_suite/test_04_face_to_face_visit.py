"""The face-to-face visit: calendar conflicts, the encounter cycle and the
independent documentation axis."""
from test_helpers import (
    ADMIN,
    CLINICIAN,
    CLINICIAN_2,
    HIGH_REQUIRED_ELEMENTS,
    MODERATE_REQUIRED_ELEMENTS,
    ApiErrorId,
    assert_same_instant,
    assert_visit,
    book_visit,
    complete_visit,
    confirm_visit,
    connect_contact,
    raise_barrier,
    read_episode,
    read_visit,
    setup_completed_medrec,
    setup_confirmed_visit,
    setup_episode,
    setup_program,
    setup_program_with_episode,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_visit_cycles_between_no_show_and_scheduled_twice(api):
    """PRD §3.4: "A no-show visit may be rescheduled: supplying a fresh
    `scheduled_start` and `scheduled_end` moves the encounter `NO_SHOW →
    SCHEDULED`, re-runs the full double-booking check against the new interval,
    resets `confirmation_status` to `UNCONFIRMED` so the patient must be
    re-confirmed, and recomputes `deadline_status` as `SCHEDULED_IN_WINDOW` or
    `SCHEDULED_LATE`. That pair of edges is a genuine cycle: a visit may bounce
    between `NO_SHOW` and `SCHEDULED` any number of times while the episode's
    records stay open."

    Design: Difficulty/non_linear_state_machine/visit_encounter_no_show_reschedule_cycle
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)

    first_no_show = validate_success(
        api.close_visit_encounter(visit["id"], {"outcome": "NO_SHOW"}, ep["nav_headers"])
    )
    assert first_no_show["encounter_status"] == "NO_SHOW"

    rebooked = validate_success(
        api.reschedule_visit(
            visit["id"],
            {"scheduled_start": "2026-05-06T09:00:00Z", "scheduled_end": "2026-05-06T10:00:00Z"},
            ep["nav_headers"],
        )
    )
    assert rebooked["encounter_status"] == "SCHEDULED"

    second_no_show = validate_success(
        api.close_visit_encounter(visit["id"], {"outcome": "NO_SHOW"}, ep["nav_headers"])
    )
    assert second_no_show["encounter_status"] == "NO_SHOW"

    final = validate_success(
        api.reschedule_visit(
            visit["id"],
            {"scheduled_start": "2026-05-07T09:00:00Z", "scheduled_end": "2026-05-07T10:00:00Z"},
            ep["nav_headers"],
        )
    )
    assert_visit(final)
    assert final["encounter_status"] == "SCHEDULED"
    assert_same_instant(
        final["scheduled_start"], "2026-05-07T09:00:00.000Z", "scheduled_start"
    )
    assert final["deadline_status"] == "SCHEDULED_IN_WINDOW"

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["visit_completed_at"] is None
    assert episode["visit_timely"] is False


def test_each_reschedule_resets_confirmation_to_unconfirmed(api):
    """PRD §3.4: "resets `confirmation_status` to `UNCONFIRMED` so the patient
    must be re-confirmed, and recomputes `deadline_status` as
    `SCHEDULED_IN_WINDOW` or `SCHEDULED_LATE`."
    PRD §3.4: "Confirming the appointment with the patient sets
    `confirmation_status` to `CONFIRMED`, and it is the one visit operation
    that a barrier can veto."

    Design: Difficulty/non_linear_state_machine/visit_encounter_no_show_reschedule_cycle
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)
    assert visit["confirmation_status"] == "CONFIRMED"

    validate_success(
        api.close_visit_encounter(visit["id"], {"outcome": "NO_SHOW"}, ep["nav_headers"])
    )
    rebooked = validate_success(
        api.reschedule_visit(
            visit["id"],
            {"scheduled_start": "2026-05-06T09:00:00Z", "scheduled_end": "2026-05-06T10:00:00Z"},
            ep["nav_headers"],
        )
    )
    assert rebooked["confirmation_status"] == "UNCONFIRMED"

    confirm_visit(ctx, ep, visit["id"])
    validate_success(
        api.close_visit_encounter(visit["id"], {"outcome": "NO_SHOW"}, ep["nav_headers"])
    )
    again = validate_success(
        api.reschedule_visit(
            visit["id"],
            {"scheduled_start": "2026-05-07T09:00:00Z", "scheduled_end": "2026-05-07T10:00:00Z"},
            ep["nav_headers"],
        )
    )
    assert again["confirmation_status"] == "UNCONFIRMED"


def test_documentation_axis_cycles_while_the_encounter_stays_completed(api):
    """PRD §3.4: "`ATTESTED → AMENDED → ATTESTED` is a revision cycle that may
    run any number of times, entirely independently of the encounter axis, which
    is already terminal at `COMPLETED`."
    PRD §3.4: "Re-attesting an amended record moves it `AMENDED → ATTESTED`,
    re-stamps `attested_by_user_id` and `attested_at` and re-derives
    `achieved_complexity`, subject to the same reconciliation and
    required-element gates as the first attestation."

    Design: Difficulty/non_linear_state_machine/visit_parallel_encounter_and_documentation_axes
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    setup_completed_medrec(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)
    complete_visit(
        ctx, visit["id"], elements=MODERATE_REQUIRED_ELEMENTS, at="2026-05-05T16:00:00Z"
    )

    attested = validate_success(api.attest_visit(visit["id"], CLINICIAN))
    assert attested["documentation_status"] == "ATTESTED"
    assert attested["encounter_status"] == "COMPLETED"

    current = read_visit(ctx, visit["id"])
    amended = validate_success(
        api.amend_visit(
            visit["id"],
            {
                "documented_elements": list(HIGH_REQUIRED_ELEMENTS),
                "expected_visit_version": current["version"],
            },
            CLINICIAN,
        )
    )
    assert amended["documentation_status"] == "AMENDED"
    assert amended["encounter_status"] == "COMPLETED"

    reattested = validate_success(api.attest_visit(visit["id"], CLINICIAN_2))
    assert reattested["documentation_status"] == "ATTESTED"
    assert reattested["encounter_status"] == "COMPLETED"
    assert reattested["attested_by_user_id"] == "clin-2"

    episode = read_episode(ctx, ep["episode_id"])
    assert_same_instant(
        episode["visit_completed_at"], "2026-05-05T16:00:00.000Z", "visit_completed_at"
    )


def test_amendment_rederives_achieved_complexity_from_the_new_elements(api):
    """PRD §3.4: "A successful attestation moves the documentation `DRAFT →
    ATTESTED`, records `attested_by_user_id` from the acting `X-User-ID` and
    `attested_at` from the logical clock, and derives `achieved_complexity`:
    `HIGH_COMPLEXITY` when the documented elements cover the full
    high-complexity set — `MED_REC_REVIEWED`, `DISCHARGE_SUMMARY_REVIEWED`,
    `PATIENT_EDUCATION`, `HIGH_COMPLEXITY_MDM` and `COMMUNITY_SERVICE_REFERRAL`
    — and `MODERATE_COMPLEXITY` otherwise."
    PRD §3.4: "An amendment replaces `documented_elements` outright, moves the
    documentation to `AMENDED`, increments `amendment_count` by 1, re-derives
    `achieved_complexity` from the new element set and increments the visit's
    own `version`; it is legal from either `ATTESTED` or `AMENDED`, and it is
    the operation that carries `expected_visit_version`."

    Design: Difficulty/non_linear_state_machine/visit_parallel_encounter_and_documentation_axes
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    setup_completed_medrec(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)
    complete_visit(
        ctx, visit["id"], elements=MODERATE_REQUIRED_ELEMENTS, at="2026-05-05T16:00:00Z"
    )

    attested = validate_success(api.attest_visit(visit["id"], CLINICIAN))
    assert attested["achieved_complexity"] == "MODERATE_COMPLEXITY"
    assert attested["amendment_count"] == 0

    current = read_visit(ctx, visit["id"])
    amended = validate_success(
        api.amend_visit(
            visit["id"],
            {
                "documented_elements": list(HIGH_REQUIRED_ELEMENTS),
                "expected_visit_version": current["version"],
            },
            CLINICIAN,
        )
    )
    assert amended["achieved_complexity"] == "HIGH_COMPLEXITY"
    assert amended["amendment_count"] == 1
    assert sorted(amended["documented_elements"]) == sorted(HIGH_REQUIRED_ELEMENTS)


def test_booking_nineteen_minutes_after_an_existing_visit_conflicts(api):
    """PRD §3.4: "The asymmetry is visible at the boundaries: a new visit
    starting exactly twenty minutes after an existing visit ends does **not**
    conflict, one starting nineteen minutes after it ends **does** conflict, and
    a new visit ending exactly when an existing visit starts does **not**
    conflict. Any collision is rejected with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/navigator_calendar_trailing_buffer_boundary
    """
    ctx = setup_program()
    ep_a = setup_episode(ctx)
    ep_b = setup_episode(ctx)
    book_visit(ctx, ep_a, start="2026-05-05T15:00:00Z", end="2026-05-05T16:00:00Z")

    validate_error(
        api.book_visit(
            ep_b["episode_id"],
            {
                "navigator_id": ctx["navigator_id"],
                "scheduled_start": "2026-05-05T16:19:00Z",
                "scheduled_end": "2026-05-05T17:00:00Z",
            },
            ep_b["nav_headers"],
        ),
        ApiErrorId.ERR_SCHEDULE_CONFLICT.value,
    )
    _, meta = validate_paginated(
        api.list_visits(ADMIN, params={"episode_id": ep_b["episode_id"]})
    )
    assert meta["total_count"] == 0


def test_booking_at_the_buffer_boundary_and_before_an_existing_start_is_admissible(api):
    """PRD §3.4: "Each candidate is treated as occupying its own interval **plus
    a trailing turnaround buffer of 20 minutes appended to its end**; there is
    deliberately no leading buffer before a candidate's start. A conflict exists
    when the proposed start falls before the candidate's end plus twenty minutes
    and the candidate's start falls before the proposed end."

    Design: Difficulty/resource_temporal_overlap/navigator_calendar_trailing_buffer_boundary
    """
    ctx = setup_program()
    ep_a = setup_episode(ctx)
    ep_b = setup_episode(ctx)
    ep_c = setup_episode(ctx)
    book_visit(ctx, ep_a, start="2026-05-05T15:00:00Z", end="2026-05-05T16:00:00Z")

    visit_b = validate_success(
        api.book_visit(
            ep_b["episode_id"],
            {
                "navigator_id": ctx["navigator_id"],
                "scheduled_start": "2026-05-05T16:20:00Z",
                "scheduled_end": "2026-05-05T17:20:00Z",
            },
            ep_b["nav_headers"],
        ),
        201,
    )
    assert visit_b["encounter_status"] == "SCHEDULED"

    visit_c = validate_success(
        api.book_visit(
            ep_c["episode_id"],
            {
                "navigator_id": ctx["navigator_id"],
                "scheduled_start": "2026-05-05T14:00:00Z",
                "scheduled_end": "2026-05-05T15:00:00Z",
            },
            ep_c["nav_headers"],
        ),
        201,
    )
    assert visit_c["encounter_status"] == "SCHEDULED"

    _, meta = validate_paginated(
        api.list_visits(ADMIN, params={"navigator_id": ctx["navigator_id"]})
    )
    assert meta["total_count"] == 3


def test_confirmation_is_vetoed_by_an_open_blocking_barrier(api):
    """PRD §3.4: "While any barrier of a blocking class on the episode sits in
    `OPEN` or `ESCALATED`, confirmation is refused with
    `ERR_BLOCKING_BARRIER_OPEN`; the appointment cannot be promised to a patient
    who has no way to get there, no interpreter-independent path and no
    authorised medication."
    PRD §3.6: "`TRANSPORTATION` carries an `sla_hours` of 48, is owned by
    `CareNavigator`, and is blocking."

    Design: Difficulty/cross_entity_state_dependency/visit_confirmation_blocked_by_open_blocking_barrier
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    raise_barrier(ctx, ep, "LANGUAGE", "needs Portuguese interpreter")
    transport = raise_barrier(ctx, ep, "TRANSPORTATION", "no ride to clinic")
    assert transport["blocking_class"] is True
    assert transport["sla_hours"] == 48
    assert_same_instant(
        transport["sla_due_at"], "2026-05-03T16:00:00.000Z", "sla_due_at"
    )
    visit = book_visit(ctx, ep)

    validate_error(
        api.confirm_visit(visit["id"], ep["nav_headers"]),
        ApiErrorId.ERR_BLOCKING_BARRIER_OPEN.value,
    )
    assert read_visit(ctx, visit["id"])["confirmation_status"] == "UNCONFIRMED"


def test_confirmation_succeeds_once_the_blocking_barrier_is_resolved(api):
    """PRD §3.6: "Either outcome stamps `closed_at` with the current instant and
    stops the barrier from blocking appointment confirmation; once no blocking
    barrier on the episode remains `OPEN` or `ESCALATED`, confirmation becomes
    available again."
    PRD §3.6: "`LANGUAGE` carries 24 hours, is owned by `CareNavigator`, and is
    **not** blocking."

    Design: Difficulty/cross_entity_state_dependency/visit_confirmation_blocked_by_open_blocking_barrier
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    language = raise_barrier(ctx, ep, "LANGUAGE", "needs Portuguese interpreter")
    transport = raise_barrier(ctx, ep, "TRANSPORTATION", "no ride to clinic")
    assert language["blocking_class"] is False
    assert language["sla_hours"] == 24
    assert language["owner_role"] == "CareNavigator"
    visit = book_visit(ctx, ep)

    validate_error(
        api.confirm_visit(visit["id"], ep["nav_headers"]),
        ApiErrorId.ERR_BLOCKING_BARRIER_OPEN.value,
    )
    closed = validate_success(
        api.close_barrier(transport["id"], {"outcome": "RESOLVED"}, ep["nav_headers"])
    )
    assert closed["status"] == "RESOLVED"

    confirmed = validate_success(api.confirm_visit(visit["id"], ep["nav_headers"]))
    assert confirmed["confirmation_status"] == "CONFIRMED"
    assert validate_success(api.get_barrier(language["id"], ADMIN))["status"] == "OPEN"


def test_cancelled_encounter_is_terminal_and_releases_the_calendar_slot(api):
    """PRD §3.4: "`CANCELLED`, reachable from either `SCHEDULED` or `NO_SHOW`,
    releases the interval permanently and is terminal on the encounter axis — a
    cancelled visit can never be rescheduled."
    PRD §3.4: "Completed, no-show and cancelled visits release their interval
    and never occupy the calendar again."

    Design: Corner/endpoints/visit_cancelled_is_terminal_and_releases_the_calendar_slot
    """
    ctx = setup_program()
    ep_a = setup_episode(ctx)
    ep_b = setup_episode(ctx)
    visit_a = book_visit(ctx, ep_a, start="2026-05-05T15:00:00Z", end="2026-05-05T16:00:00Z")

    cancelled = validate_success(
        api.close_visit_encounter(
            visit_a["id"], {"outcome": "CANCELLED"}, ep_a["nav_headers"]
        )
    )
    assert cancelled["encounter_status"] == "CANCELLED"

    validate_error(
        api.reschedule_visit(
            visit_a["id"],
            {"scheduled_start": "2026-05-06T09:00:00Z", "scheduled_end": "2026-05-06T10:00:00Z"},
            ep_a["nav_headers"],
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_visit(ctx, visit_a["id"])["encounter_status"] == "CANCELLED"

    visit_b = validate_success(
        api.book_visit(
            ep_b["episode_id"],
            {
                "navigator_id": ctx["navigator_id"],
                "scheduled_start": "2026-05-05T15:00:00Z",
                "scheduled_end": "2026-05-05T16:00:00Z",
            },
            ep_b["nav_headers"],
        ),
        201,
    )
    assert visit_b["encounter_status"] == "SCHEDULED"


def test_attestation_without_the_full_moderate_element_set_is_refused(api):
    """PRD §3.4: "and the visit's `documented_elements` must contain every
    member of the moderate required-element set — `MED_REC_REVIEWED`,
    `DISCHARGE_SUMMARY_REVIEWED` and `PATIENT_EDUCATION` — or the request is
    refused with `ERR_REQUIRED_ELEMENTS_INCOMPLETE`."
    PRD §3.4: "Before the first attestation `achieved_complexity` is null."

    Design: Corner/validations/attest_missing_moderate_element_rejected
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    setup_completed_medrec(ctx, ep)
    visit = setup_confirmed_visit(ctx, ep)
    complete_visit(
        ctx,
        visit["id"],
        elements=["MED_REC_REVIEWED", "DISCHARGE_SUMMARY_REVIEWED"],
        at="2026-05-05T16:00:00Z",
    )

    validate_error(
        api.attest_visit(visit["id"], CLINICIAN),
        ApiErrorId.ERR_REQUIRED_ELEMENTS_INCOMPLETE.value,
    )
    after = read_visit(ctx, visit["id"])
    assert after["documentation_status"] == "DRAFT"
    assert after["achieved_complexity"] is None
    assert after["attested_by_user_id"] is None
    assert after["encounter_status"] == "COMPLETED"
    assert after["deadline_status"] == "MET"
