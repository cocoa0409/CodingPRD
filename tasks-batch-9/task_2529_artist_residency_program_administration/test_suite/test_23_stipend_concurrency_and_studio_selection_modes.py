"""Pricing a calendar that changed underneath, and how a studio came to be chosen."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_NO_STUDIO_AVAILABLE,
    ERR_STALE_VERSION,
    ERR_STIPEND_POOL_EXHAUSTED,
    ERR_STUDIO_CAPABILITY_MISMATCH,
    FACILITIES_HEADERS,
    FINANCE_SCHEDULER_HEADERS,
    assign_studio,
    create_applicant,
    create_residency,
    create_studio,
    disbursements_for,
    get_success_data,
    make_stipend_schedule_payload,
    make_studio_assignment_payload,
    refresh_residency,
    release_studio_assignment,
    schedule_residency,
    setup_scheduled_residency,
    studio_assignments_for,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"
LONG_WEEKS = 8
SHORT_WEEKS = 4
PERIOD_GROSS = 140000
SHORT_AWARD = 280000
EXTRAVAGANT_WEEKLY_RATE = 6000000


def _residency_rescheduled_shorter(api):
    """An eight-week calendar cut to four, leaving the finance officer's token behind."""
    _cycle, _applicant, residency = setup_scheduled_residency(
        api,
        clock=CLOCK,
        session_start_date=SESSION_START,
        session_length_weeks=LONG_WEEKS,
    )
    captured = refresh_residency(api, residency)["version"]
    shortened = schedule_residency(api, residency, SESSION_START, SHORT_WEEKS)
    assert shortened["session_length_weeks"] == SHORT_WEEKS
    return residency, captured, shortened["version"]


def _generate(api, residency, expected_version, **extra):
    """The generation call as the scheduling officer makes it."""
    return api.generate_stipend_schedule(
        residency.residency_id,
        make_stipend_schedule_payload(expected_version, **extra),
        FINANCE_SCHEDULER_HEADERS,
    )


def test_a_generation_replaying_an_old_residency_version_is_refused(api):
    """The officer never gets to price four periods for a four-week session.

    PRD: "Generating a residency's stipend schedule requires the non-optional field
    `expected_residency_version`, carrying the `version` of that `Residency` as the
    client last observed it."

    Design: Corner/cross_cutting_complexity_layers/stipend_schedule_generation_rejects_a_residency_version_that_moved_under_it
    """
    residency, captured, current = _residency_rescheduled_shorter(api)
    assert current == captured + 1

    validate_error(_generate(api, residency, captured), ERR_STALE_VERSION)


def test_the_refused_generation_created_no_rows(api):
    """The award on the residency is exactly what the reschedule left there.

    PRD: "A mismatch against the residency's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412), which stops a regeneration from being priced
    against an out-of-date session length, weekly rate or payment history."

    Design: Corner/cross_cutting_complexity_layers/stipend_schedule_generation_rejects_a_residency_version_that_moved_under_it
    """
    residency, captured, _current = _residency_rescheduled_shorter(api)
    before = refresh_residency(api, residency)

    validate_error(_generate(api, residency, captured), ERR_STALE_VERSION)

    assert disbursements_for(api, residency.residency_id) == []
    after = refresh_residency(api, residency)
    assert after["stipend_total_cents"] == before["stipend_total_cents"]
    assert after["version"] == before["version"]


def test_the_current_token_prices_the_new_session(api):
    """Four weeks buy two periods, not the four the stale caller expected.

    PRD: "The number of periods is the residency's `session_length_weeks` divided by
    two, rounded **up**."

    Design: Corner/cross_cutting_complexity_layers/stipend_schedule_generation_rejects_a_residency_version_that_moved_under_it
    """
    residency, captured, current = _residency_rescheduled_shorter(api)
    validate_error(_generate(api, residency, captured), ERR_STALE_VERSION)

    rows = get_success_data(_generate(api, residency, current), 201)

    assert [row["period_index"] for row in rows] == [1, 2]
    assert [row["gross_cents"] for row in rows] == [PERIOD_GROSS, PERIOD_GROSS]


def test_generation_itself_bumps_the_guard(api):
    """A duplicate schedule cannot be created by retrying the call that worked.

    PRD: "Generation also sets the residency's `stipend_weekly_rate_cents` to the
    effective rate, re-bases `stipend_total_cents` to the provisional award for that
    rate, recomputes the cycle's stipend ledger, and advances the residency's and the
    cycle's `version` by 1 each."

    Design: Corner/cross_cutting_complexity_layers/stipend_schedule_generation_rejects_a_residency_version_that_moved_under_it
    """
    residency, _captured, current = _residency_rescheduled_shorter(api)
    get_success_data(_generate(api, residency, current), 201)

    validate_error(_generate(api, residency, current), ERR_STALE_VERSION)

    settled = refresh_residency(api, residency)
    assert settled["version"] == current + 1
    assert settled["stipend_total_cents"] == SHORT_AWARD
    assert len(disbursements_for(api, residency.residency_id)) == 2


def test_regeneration_is_possible_but_must_re_read_the_version(api):
    """Lengthening the session again allows a fresh calendar over the old one.

    PRD: "On a regeneration every existing `SCHEDULED` row of the residency is first
    driven `SCHEDULED → VOIDED`, while rows in `PAID` and `REVERSED` are left
    completely untouched. The new rows then restart at `period_index` 1"

    Design: Corner/cross_cutting_complexity_layers/stipend_schedule_generation_rejects_a_residency_version_that_moved_under_it
    """
    residency, _captured, current = _residency_rescheduled_shorter(api)
    get_success_data(_generate(api, residency, current), 201)
    lengthened = schedule_residency(api, residency, SESSION_START, LONG_WEEKS)

    validate_error(_generate(api, residency, current), ERR_STALE_VERSION)

    fresh = get_success_data(_generate(api, residency, lengthened["version"]), 201)
    assert [row["period_index"] for row in fresh] == [1, 2, 3, 4]
    voided = [
        row
        for row in disbursements_for(api, residency.residency_id)
        if row["status"] == "VOIDED"
    ]
    assert len(voided) == 2


def test_the_stale_answer_arrives_before_the_budget_answer(api):
    """A rate the pool could never cover is still a second-order complaint.

    PRD: "The stale-version comparison itself is evaluated early — after path and
    foreign-key resolution and after the request body has been checked for shape and
    range, but before any domain state, safety, temporal, capacity or fiscal rule is
    consulted."

    Design: Corner/cross_cutting_complexity_layers/stipend_schedule_generation_rejects_a_residency_version_that_moved_under_it
    """
    residency, captured, current = _residency_rescheduled_shorter(api)

    validate_error(
        _generate(
            api,
            residency,
            captured,
            weekly_rate_override_cents=EXTRAVAGANT_WEEKLY_RATE,
        ),
        ERR_STALE_VERSION,
    )

    validate_error(
        _generate(
            api,
            residency,
            current,
            weekly_rate_override_cents=EXTRAVAGANT_WEEKLY_RATE,
        ),
        ERR_STIPEND_POOL_EXHAUSTED,
    )
    assert disbursements_for(api, residency.residency_id) == []


def test_the_token_is_not_interchangeable_across_residencies(api):
    """A number that is current somewhere else is not current here.

    PRD: "The service therefore guards all three with optimistic concurrency control
    on the **parent** resource's `version`."

    Design: Corner/cross_cutting_complexity_layers/stipend_schedule_generation_rejects_a_residency_version_that_moved_under_it
    """
    cycle, _applicant, neighbour = setup_scheduled_residency(
        api,
        clock=CLOCK,
        session_start_date=SESSION_START,
        session_length_weeks=LONG_WEEKS,
    )
    mine = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, mine, SESSION_START, LONG_WEEKS)
    schedule_residency(api, mine, SESSION_START, SHORT_WEEKS)
    borrowed = refresh_residency(api, neighbour)["version"]
    live = refresh_residency(api, mine)["version"]
    assert borrowed != live

    validate_error(_generate(api, mine, borrowed), ERR_STALE_VERSION)

    rows = get_success_data(_generate(api, mine, live), 201)
    assert len(rows) == 2
    assert disbursements_for(api, neighbour.residency_id) == []


STUDIO_A = {
    "code": "S-A",
    "capability_tags": ["WELDING"],
    "ventilation_class": "LOCAL",
    "max_concurrent_residents": 1,
}
STUDIO_B = {
    "code": "S-B",
    "capability_tags": ["WELDING", "KILN"],
    "ventilation_class": "FUME_HOOD",
    "max_concurrent_residents": 1,
}
STUDIO_Z = {
    "code": "S-Z",
    "capability_tags": ["CLEAN_ONLY"],
    "ventilation_class": "NONE",
    "max_concurrent_residents": 4,
}


def _two_residents_and_three_studios(api):
    """Two scheduled welders, one narrow studio, one lavish one, and one unusable one."""
    cycle, _applicant, first = setup_scheduled_residency(
        api,
        clock=CLOCK,
        session_start_date=SESSION_START,
        session_length_weeks=LONG_WEEKS,
    )
    second = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, second, SESSION_START, LONG_WEEKS)
    studios = {
        spec["code"]: create_studio(api, **spec)
        for spec in (STUDIO_A, STUDIO_B, STUDIO_Z)
    }
    return cycle, first, second, studios


def _book(api, residency, studio=None, expected_version=None):
    """The booking call, returning the raw response so refusals can be read."""
    current = refresh_residency(api, residency)["version"]
    return api.create_studio_assignment(
        make_studio_assignment_payload(
            residency.residency_id,
            SESSION_START,
            SESSION_END,
            current if expected_version is None else expected_version,
            studio.studio_id if studio else None,
        ),
        FACILITIES_HEADERS,
    )


def test_omitting_the_studio_runs_the_selector_and_records_the_mode(api):
    """The narrow local studio wins over the fume hood that would also have done.

    PRD: "The ranking is ascending on every key in turn, which means the selector
    deliberately prefers the **least** over-provisioned studio that will do the job:
    first by ventilation rank ascending, so a `LOCAL` studio is preferred over a
    `FUME_HOOD` studio when `LOCAL` suffices"

    Design: Corner/cross_cutting_complexity_layers/explicit_and_automatic_studio_selection_record_different_modes
    """
    _cycle, first, _second, studios = _two_residents_and_three_studios(api)

    booked = assign_studio(api, first, SESSION_START, SESSION_END)

    assert booked["selection_mode"] == "AUTO_SELECTED"
    assert booked["studio_id"] == studios["S-A"].studio_id
    assert refresh_residency(api, first)["assigned_studio_code"] == "S-A"


def test_naming_a_studio_skips_the_ranking_but_not_the_checks(api):
    """The desk may insist on the studio the selector would never have picked.

    PRD: "When `studio_id` is omitted the server chooses the studio itself, and
    `selection_mode` on the created assignment is recorded as `AUTO_SELECTED` rather
    than `EXPLICIT`."

    Design: Corner/cross_cutting_complexity_layers/explicit_and_automatic_studio_selection_record_different_modes
    """
    _cycle, _first, second, studios = _two_residents_and_three_studios(api)

    booked = assign_studio(api, second, SESSION_START, SESSION_END, studios["S-B"])

    assert booked["selection_mode"] == "EXPLICIT"
    assert booked["studio_id"] == studios["S-B"].studio_id
    assert refresh_residency(api, second)["assigned_studio_code"] == "S-B"


def test_the_two_modes_are_distinguishable_in_the_list_surface(api):
    """One booking of each kind, each findable by the mode it recorded.

    PRD: "Assignments may be listed filtered by `studio_id`, `residency_id`, `status`
    or `selection_mode`."

    Design: Corner/cross_cutting_complexity_layers/explicit_and_automatic_studio_selection_record_different_modes
    """
    _cycle, first, second, studios = _two_residents_and_three_studios(api)
    chosen = assign_studio(api, first, SESSION_START, SESSION_END)
    named = assign_studio(api, second, SESSION_START, SESSION_END, studios["S-B"])

    automatic, auto_meta = validate_paginated(
        api.list_studio_assignments(
            FACILITIES_HEADERS, {"selection_mode": "AUTO_SELECTED"}
        )
    )
    explicit, explicit_meta = validate_paginated(
        api.list_studio_assignments(FACILITIES_HEADERS, {"selection_mode": "EXPLICIT"})
    )

    assert auto_meta["total_count"] == 1
    assert explicit_meta["total_count"] == 1
    assert [row["id"] for row in automatic] == [chosen["id"]]
    assert [row["id"] for row in explicit] == [named["id"]]


def test_an_ineligible_explicit_choice_gets_its_own_error(api):
    """Naming an unusable studio is a capability complaint, not an empty-set one.

    PRD: "The named studio's `capability_tags` must be a superset of the
    `required_capability_tags` of the discipline whose `code` matches the residency's
    `discipline_code` within the residency's cycle, or
    `ERR_STUDIO_CAPABILITY_MISMATCH` (HTTP 422)."

    Design: Corner/cross_cutting_complexity_layers/explicit_and_automatic_studio_selection_record_different_modes
    """
    _cycle, _first, second, studios = _two_residents_and_three_studios(api)

    validate_error(
        _book(api, second, studios["S-Z"]), ERR_STUDIO_CAPABILITY_MISMATCH
    )

    assert studio_assignments_for(api, second.residency_id) == []


def test_only_the_automatic_path_can_exhaust_the_set(api):
    """With both welding studios taken, the selector has nothing left to offer.

    PRD: "If the eligibility filter retains nothing, the request is rejected with
    `ERR_NO_STUDIO_AVAILABLE` (HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/explicit_and_automatic_studio_selection_record_different_modes
    """
    cycle, first, second, studios = _two_residents_and_three_studios(api)
    assign_studio(api, first, SESSION_START, SESSION_END)
    assign_studio(api, second, SESSION_START, SESSION_END, studios["S-B"])
    third = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, third, SESSION_START, LONG_WEEKS)

    validate_error(_book(api, third), ERR_NO_STUDIO_AVAILABLE)

    assert studio_assignments_for(api, third.residency_id) == []


def test_the_selectors_input_set_is_state_filtered(api):
    """Closing the preferred studio for maintenance hands the booking to the other.

    PRD: "First an eligibility filter retains every studio that satisfies all of the
    following: its `status` is `AVAILABLE`, so studios in `MAINTENANCE` or
    `DECOMMISSIONED` are never candidates"

    Design: Corner/cross_cutting_complexity_layers/explicit_and_automatic_studio_selection_record_different_modes
    """
    _cycle, first, _second, studios = _two_residents_and_three_studios(api)
    closed = get_success_data(
        api.update_studio(
            studios["S-A"].studio_id, {"status": "MAINTENANCE"}, FACILITIES_HEADERS
        )
    )
    assert closed["status"] == "MAINTENANCE"

    booked = assign_studio(api, first, SESSION_START, SESSION_END)

    assert booked["selection_mode"] == "AUTO_SELECTED"
    assert booked["studio_id"] == studios["S-B"].studio_id


def test_the_mode_is_recorded_once_and_never_recomputed(api):
    """The released row keeps the story of how its studio was chosen.

    PRD: "it moves `ACTIVE → RELEASED`, records the `released_reason`, recomputes the
    studio's `reserved_resident_days` and `active_assignment_count`, clears the
    residency's `assigned_studio_code` to null, and advances the assignment's, the
    studio's and the residency's `version` by 1 each."

    Design: Corner/cross_cutting_complexity_layers/explicit_and_automatic_studio_selection_record_different_modes
    """
    _cycle, first, _second, studios = _two_residents_and_three_studios(api)
    chosen = assign_studio(api, first, SESSION_START, SESSION_END)
    assert chosen["selection_mode"] == "AUTO_SELECTED"

    release_studio_assignment(api, chosen["id"], "the kiln bay suits the work better")
    replacement = assign_studio(api, first, SESSION_START, SESSION_END, studios["S-B"])

    kept = get_success_data(api.get_studio_assignment(chosen["id"], ADMIN_HEADERS))
    assert kept["status"] == "RELEASED"
    assert kept["selection_mode"] == "AUTO_SELECTED"
    assert replacement["selection_mode"] == "EXPLICIT"
