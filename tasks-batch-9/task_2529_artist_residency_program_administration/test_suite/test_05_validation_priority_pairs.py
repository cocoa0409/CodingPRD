"""Requests that break two rules at once, and which answer must come back."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_APPLICATION_NOT_OFFERED,
    ERR_COMPLIANCE_SUSPENDED,
    ERR_MEAL_PLAN_NOT_AVAILABLE,
    ERR_RESIDENCY_NOT_SCHEDULED,
    ERR_STIPEND_POOL_EXHAUSTED,
    ERR_STUDIO_INTERVAL_CONFLICT,
    FACILITIES_HEADERS,
    assert_money_equals,
    assign_studio,
    check_in,
    complete_all_trainings,
    create_applicant,
    create_housing_unit,
    create_residency,
    create_studio,
    housing_assignments_for,
    make_housing_assignment_payload,
    make_offer_response_payload,
    make_studio_assignment_payload,
    read_application,
    read_cycle,
    read_residency,
    refresh_housing_unit,
    refresh_residency,
    refresh_studio,
    reinstate_compliance,
    schedule_residency,
    set_clock,
    setup_locked_slate,
    setup_open_cycle,
    studio_assignments_for,
    suspend_compliance,
    validate_error,
    validate_paginated,
    get_success_data,
)

STARVED_CYCLE = {
    "cohort_target_size": 1,
    "alumni_reserve_pct": 0.0,
    "stipend_pool_cents": 100000,
}

TOP_AND_TAIL = [
    [(8, 8, 8, 8), (8, 8, 8, 8)],
    [(7, 7, 7, 7), (7, 7, 7, 7)],
]


def _starved_locked_slate(api):
    """One slot, one offer, one waitlisted rival and a pool that covers neither."""
    cycle, apps, _chair = setup_locked_slate(
        api,
        applicant_count=2,
        panelist_count=2,
        score_legs=TOP_AND_TAIL,
        **STARVED_CYCLE,
    )
    offered, waitlisted = apps
    assert read_application(api, offered.application_id)["status"] == "OFFERED"
    assert read_application(api, waitlisted.application_id)["status"] == "WAITLISTED"
    return cycle, offered, waitlisted


def test_a_waitlisted_artist_hears_about_the_state_not_the_budget(api):
    """Both rules are broken; the application-state answer is the one returned.

    PRD: "The application must be in `OFFERED`; anything else is
    `ERR_APPLICATION_NOT_OFFERED` (HTTP 409), and — as §2.9 sets out — that
    state answer is given even when the money would also not have fitted."

    Design: Difficulty/priority_pair_validation_conflict/offer_state_check_beats_stipend_pool_exhausted
    """
    cycle, _offered, waitlisted = _starved_locked_slate(api)
    starved = read_cycle(api, cycle.cycle_id)
    assert_money_equals(starved["stipend_uncommitted_cents"], 100000, "uncommitted")
    assert starved["slots_open_count"] == 1

    response = api.respond_to_offer(
        waitlisted.application_id,
        make_offer_response_payload("ACCEPT"),
        waitlisted.applicant.headers,
    )
    validate_error(response, ERR_APPLICATION_NOT_OFFERED)

    assert read_application(api, waitlisted.application_id)["status"] == "WAITLISTED"


def test_the_same_endpoint_reports_the_budget_once_the_state_is_right(api):
    """With the state check satisfied the paired money rule fires alone.

    PRD: "and the cycle's `stipend_uncommitted_cents` must be at least the
    amount this acceptance would commit, which is the application's
    `requested_session_length_weeks` multiplied by the cycle's
    `stipend_weekly_rate_cents`, or `ERR_STIPEND_POOL_EXHAUSTED` (HTTP 409) —
    the last check in the entire ladder."

    Design: Difficulty/priority_pair_validation_conflict/offer_state_check_beats_stipend_pool_exhausted
    """
    _cycle, offered, _waitlisted = _starved_locked_slate(api)

    validate_error(
        api.respond_to_offer(
            offered.application_id,
            make_offer_response_payload("ACCEPT"),
            offered.applicant.headers,
        ),
        ERR_STIPEND_POOL_EXHAUSTED,
    )

    assert read_application(api, offered.application_id)["status"] == "OFFERED"


def test_neither_rejected_acceptance_starts_the_cascade(api):
    """No residency, no commitment and no slot movement behind either refusal.

    PRD: "Caused by link 1, the provisional award is committed against the
    cycle: `stipend_committed_cents` increases by the requested session length
    in weeks multiplied by the cycle's weekly rate, and
    `stipend_uncommitted_cents`, `slots_filled_count` and `slots_open_count` are
    all recomputed."

    Design: Difficulty/priority_pair_validation_conflict/offer_state_check_beats_stipend_pool_exhausted
    """
    cycle, offered, waitlisted = _starved_locked_slate(api)

    validate_error(
        api.respond_to_offer(
            waitlisted.application_id,
            make_offer_response_payload("ACCEPT"),
            waitlisted.applicant.headers,
        ),
        ERR_APPLICATION_NOT_OFFERED,
    )
    validate_error(
        api.respond_to_offer(
            offered.application_id,
            make_offer_response_payload("ACCEPT"),
            offered.applicant.headers,
        ),
        ERR_STIPEND_POOL_EXHAUSTED,
    )

    untouched = read_cycle(api, cycle.cycle_id)
    assert_money_equals(untouched["stipend_committed_cents"], 0, "committed")
    assert untouched["slots_filled_count"] == 0
    assert untouched["slots_open_count"] == 1
    rows, _meta = validate_paginated(
        api.list_residencies(ADMIN_HEADERS, {"cycle_id": cycle.cycle_id})
    )
    assert rows == []


SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"
INNER_WINDOW = ("2026-11-10", "2026-11-20")


def _two_scheduled_residencies(api):
    """Two artists booked into the same eight-week session of one cycle."""
    cycle = setup_open_cycle(api)
    residencies = []
    for _ in range(2):
        residency = create_residency(api, cycle, create_applicant(api))
        schedule_residency(api, residency, SESSION_START, 8)
        residencies.append(residency)
    return cycle, residencies[0], residencies[1]


def _book_studio(api, studio, residency, window):
    """The raw booking call, so a refusal can be inspected instead of raised."""
    current = refresh_residency(api, residency)
    payload = make_studio_assignment_payload(
        residency.residency_id,
        window[0],
        window[1],
        current["version"],
        studio.studio_id,
    )
    return api.create_studio_assignment(payload, FACILITIES_HEADERS)


def _studio_pair_world(api):
    """One single-occupancy studio held all session, plus a suspended rival."""
    _cycle, resident_a, resident_b = _two_scheduled_residencies(api)
    studio = create_studio(api)
    held = assign_studio(api, resident_a, SESSION_START, SESSION_END, studio)
    assert held["occupied_days"] == 56
    assert held["status"] == "ACTIVE"

    complete_all_trainings(api, resident_b)
    suspended = suspend_compliance(
        api, resident_b, "kiln interlock bypassed without authorisation"
    )
    assert suspended["compliance_status"] == "SUSPENDED"
    assert suspended["status"] == "SCHEDULED"
    return studio, resident_a, resident_b, held


def test_a_suspended_resident_hears_about_the_suspension_not_the_clash(api):
    """The safety rule answers even though the window was never bookable.

    PRD: "The residency's `compliance_status` must not be `SUSPENDED`, or
    `ERR_COMPLIANCE_SUSPENDED` (HTTP 422). As §2.9 records, this check is
    deliberately placed **ahead** of the interval-conflict check, so a suspended
    resident hears about the suspension even when the window they asked for was
    never bookable."

    Design: Difficulty/priority_pair_validation_conflict/compliance_suspension_beats_studio_interval_conflict
    """
    studio, _resident_a, resident_b, _held = _studio_pair_world(api)

    validate_error(
        _book_studio(api, studio, resident_b, INNER_WINDOW), ERR_COMPLIANCE_SUSPENDED
    )

    assert studio_assignments_for(api, resident_b.residency_id) == []


def test_clearing_the_suspension_uncovers_the_interval_conflict(api):
    """The identical window is refused again, this time on the calendar.

    PRD: "On a **single-occupancy** studio, where `max_concurrent_residents` is
    exactly 1, the requested window must not overlap any `ACTIVE` assignment of
    that studio under closed-interval semantics **extended by a two-day
    turnaround buffer** on each existing assignment".

    Design: Difficulty/priority_pair_validation_conflict/compliance_suspension_beats_studio_interval_conflict
    """
    studio, _resident_a, resident_b, _held = _studio_pair_world(api)
    validate_error(
        _book_studio(api, studio, resident_b, INNER_WINDOW), ERR_COMPLIANCE_SUSPENDED
    )

    restored = reinstate_compliance(api, resident_b)
    assert restored["compliance_status"] == "CLEARED"

    validate_error(
        _book_studio(api, studio, resident_b, INNER_WINDOW), ERR_STUDIO_INTERVAL_CONFLICT
    )


def test_neither_refusal_disturbs_the_incumbent_booking(api):
    """The studio ledger and the sitting tenant survive both rejections.

    PRD: "The server recomputes the studio's `reserved_resident_days` and
    `active_assignment_count`, sets the residency's `assigned_studio_code` to the
    chosen studio's `code`, and advances the studio's and the residency's
    `version` by 1 each."

    Design: Difficulty/priority_pair_validation_conflict/compliance_suspension_beats_studio_interval_conflict
    """
    studio, resident_a, resident_b, held = _studio_pair_world(api)
    booked = refresh_studio(api, studio)
    assert booked["active_assignment_count"] == 1
    assert booked["reserved_resident_days"] == 56

    validate_error(
        _book_studio(api, studio, resident_b, INNER_WINDOW), ERR_COMPLIANCE_SUSPENDED
    )
    reinstate_compliance(api, resident_b)
    validate_error(
        _book_studio(api, studio, resident_b, INNER_WINDOW), ERR_STUDIO_INTERVAL_CONFLICT
    )

    after = refresh_studio(api, studio)
    assert after["active_assignment_count"] == 1
    assert after["reserved_resident_days"] == 56
    incumbent = studio_assignments_for(api, resident_a.residency_id)
    assert [row["id"] for row in incumbent] == [held["id"]]
    assert incumbent[0]["status"] == "ACTIVE"
    assert incumbent[0]["occupied_days"] == 56
    assert read_residency(api, resident_a.residency_id)["assigned_studio_code"] == (
        studio.code
    )


HOUSING_WINDOW = ("2026-11-02", "2026-12-28")
NO_MEAL_TWO_BED = {"bed_count": 2, "meal_plan_included": False}


def _book_housing(api, unit, residency, meal_plan_selected=None):
    """The raw bed booking, so a refusal can be inspected instead of raised."""
    current = refresh_housing_unit(api, unit)
    payload = make_housing_assignment_payload(
        unit.housing_unit_id,
        residency.residency_id,
        HOUSING_WINDOW[0],
        HOUSING_WINDOW[1],
        current["version"],
    )
    if meal_plan_selected is not None:
        payload["meal_plan_selected"] = meal_plan_selected
    return api.create_housing_assignment(payload, ADMIN_HEADERS)


def _housing_pair_world(api):
    """A checked-in artist, a still-scheduled artist, and a no-meal double room."""
    _cycle, resident_a, resident_b = _two_scheduled_residencies(api)
    unit = create_housing_unit(api, **NO_MEAL_TWO_BED)
    assert unit.unit["meal_plan_included"] is False
    assert unit.unit["bed_count"] == 2
    assert unit.unit["occupied_bed_nights"] == 0

    complete_all_trainings(api, resident_a)
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    entered = check_in(api, resident_a)
    assert entered["status"] == "IN_RESIDENCE"
    assert read_residency(api, resident_b.residency_id)["status"] == "SCHEDULED"
    return unit, resident_a, resident_b


def test_a_checked_in_artist_hears_about_the_lifecycle_not_the_meal_plan(api):
    """The state rule answers a request that also asked for absent meals.

    PRD: "As §2.9 records, this check beats the meal-plan check, so a request
    naming a no-meal unit for an already `IN_RESIDENCE` residency is reported as
    a residency-state problem, not a meal-plan problem."

    Design: Difficulty/priority_pair_validation_conflict/residency_state_check_beats_meal_plan_unavailable
    """
    unit, resident_a, _resident_b = _housing_pair_world(api)

    validate_error(
        _book_housing(api, unit, resident_a, meal_plan_selected=True),
        ERR_RESIDENCY_NOT_SCHEDULED,
    )

    assert housing_assignments_for(api, resident_a.residency_id) == []
    assert refresh_housing_unit(api, unit)["occupied_bed_nights"] == 0


def test_the_same_payload_reports_the_meal_plan_once_the_state_is_right(api):
    """Aimed at a still-scheduled residency, the paired rule fires alone.

    PRD: "`meal_plan_selected` may be true only when the named unit's
    `meal_plan_included` is true, or `ERR_MEAL_PLAN_NOT_AVAILABLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/residency_state_check_beats_meal_plan_unavailable
    """
    unit, resident_a, resident_b = _housing_pair_world(api)

    validate_error(
        _book_housing(api, unit, resident_a, meal_plan_selected=True),
        ERR_RESIDENCY_NOT_SCHEDULED,
    )
    validate_error(
        _book_housing(api, unit, resident_b, meal_plan_selected=True),
        ERR_MEAL_PLAN_NOT_AVAILABLE,
    )

    assert housing_assignments_for(api, resident_b.residency_id) == []
    assert refresh_housing_unit(api, unit)["occupied_bed_nights"] == 0


def test_dropping_the_meal_request_lets_the_booking_through(api):
    """Both refusals were genuine and each was independently removable.

    PRD: "An assignment from the 2nd of one month to the 28th of the next
    occupies fifty-six bed-nights, the nights of the 2nd through the 27th."

    Design: Difficulty/priority_pair_validation_conflict/residency_state_check_beats_meal_plan_unavailable
    """
    unit, _resident_a, resident_b = _housing_pair_world(api)
    validate_error(
        _book_housing(api, unit, resident_b, meal_plan_selected=True),
        ERR_MEAL_PLAN_NOT_AVAILABLE,
    )

    booked = get_success_data(_book_housing(api, unit, resident_b), 201)

    assert booked["status"] == "ACTIVE"
    assert booked["meal_plan_selected"] is False
    assert booked["bed_nights"] == 56
    assert booked["check_in_date"] == HOUSING_WINDOW[0]
    assert booked["check_out_date"] == HOUSING_WINDOW[1]
    assert refresh_housing_unit(api, unit)["occupied_bed_nights"] == 56
