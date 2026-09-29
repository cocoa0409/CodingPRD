"""Booking a studio or a bed against a picture of the world that has already moved."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_STALE_VERSION,
    ERR_STUDIO_CAPABILITY_MISMATCH,
    ERR_VALIDATION,
    FACILITIES_HEADERS,
    assert_housing_bed_night_ledger,
    assert_studio_day_ledger,
    create_applicant,
    create_housing_unit,
    create_residency,
    create_studio,
    get_success_data,
    housing_assignments_for,
    make_housing_assignment_payload,
    make_studio_assignment_payload,
    record_training,
    refresh_housing_unit,
    refresh_residency,
    refresh_studio,
    release_housing_assignment,
    schedule_residency,
    setup_scheduled_residency,
    studio_assignments_for,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"
SESSION_WEEKS = 8
OCCUPIED_DAYS = 56
SOLE_STUDIO = {
    "code": "S-A",
    "capability_tags": ["WELDING"],
    "ventilation_class": "LOCAL",
    "max_concurrent_residents": 1,
}
UNFIT_STUDIO = {
    "code": "S-Z",
    "capability_tags": ["CLEAN_ONLY"],
    "ventilation_class": "NONE",
    "max_concurrent_residents": 4,
}


def _residency_studio_and_a_token_left_behind(api):
    """A scheduled resident, one eligible studio, and a token a training moved on."""
    _cycle, _applicant, residency = setup_scheduled_residency(
        api,
        clock=CLOCK,
        session_start_date=SESSION_START,
        session_length_weeks=SESSION_WEEKS,
    )
    captured = refresh_residency(api, residency)["version"]
    studio = create_studio(api, **SOLE_STUDIO)
    moved = record_training(api, residency, "SAFETY_ORIENTATION")
    return residency, studio, captured, moved["version"]


def _book_studio(api, residency, expected_version, studio=None):
    """The booking call as the facilities desk issues it, returning the response."""
    return api.create_studio_assignment(
        make_studio_assignment_payload(
            residency.residency_id,
            SESSION_START,
            SESSION_END,
            expected_version,
            studio.studio_id if studio else None,
        ),
        FACILITIES_HEADERS,
    )


def test_a_studio_booking_replaying_an_old_residency_version_is_refused(api):
    """The request is faultless apart from the number it carries.

    PRD: "Creating a studio assignment requires the non-optional field
    `expected_residency_version`, carrying the `version` of the target `Residency`
    as the client last observed it."

    Design: Corner/cross_cutting_complexity_layers/studio_assignment_rejects_a_residency_version_that_moved_under_it
    """
    residency, _studio, captured, current = _residency_studio_and_a_token_left_behind(api)
    assert captured != current

    validate_error(_book_studio(api, residency, captured), ERR_STALE_VERSION)


def test_any_write_on_the_guarded_residency_invalidates_the_token(api):
    """A safety record on an unrelated axis is enough to move the guard.

    PRD: "A release, a compliance suspension or another reassignment performed by
    someone else since the client's last read will all have advanced the residency's
    `version` and will all therefore be caught here."

    Design: Corner/cross_cutting_complexity_layers/studio_assignment_rejects_a_residency_version_that_moved_under_it
    """
    residency, _studio, captured, current = _residency_studio_and_a_token_left_behind(api)

    assert current == captured + 1

    validate_error(_book_studio(api, residency, captured), ERR_STALE_VERSION)
    assert refresh_residency(api, residency)["version"] == current


def test_the_refused_studio_booking_wrote_nothing(api):
    """No row, no reserved days, no name on the residency.

    PRD: "If that value does not equal the residency's current `version`, the create
    is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/studio_assignment_rejects_a_residency_version_that_moved_under_it
    """
    residency, studio, captured, _current = _residency_studio_and_a_token_left_behind(api)

    validate_error(_book_studio(api, residency, captured), ERR_STALE_VERSION)

    assert studio_assignments_for(api, residency.residency_id) == []
    assert_studio_day_ledger(refresh_studio(api, studio), 0, 0)
    assert refresh_residency(api, residency)["assigned_studio_code"] is None


def test_the_current_studio_token_succeeds_and_the_selector_runs(api):
    """The identical call, one number later, books the only studio that fits.

    PRD: "When `studio_id` is omitted the server chooses the studio itself, and
    `selection_mode` on the created assignment is recorded as `AUTO_SELECTED` rather
    than `EXPLICIT`."

    Design: Corner/cross_cutting_complexity_layers/studio_assignment_rejects_a_residency_version_that_moved_under_it
    """
    residency, studio, captured, current = _residency_studio_and_a_token_left_behind(api)
    validate_error(_book_studio(api, residency, captured), ERR_STALE_VERSION)

    booked = get_success_data(_book_studio(api, residency, current), 201)

    assert booked["selection_mode"] == "AUTO_SELECTED"
    assert booked["studio_id"] == studio.studio_id
    assert booked["status"] == "ACTIVE"
    assert booked["occupied_days"] == OCCUPIED_DAYS


def test_the_successful_studio_write_moves_the_guard_again(api):
    """A retry of the very call that just worked is refused on the token.

    PRD: "The server recomputes the studio's `reserved_resident_days` and
    `active_assignment_count`, sets the residency's `assigned_studio_code` to the
    chosen studio's `code`, and advances the studio's and the residency's `version`
    by 1 each."

    Design: Corner/cross_cutting_complexity_layers/studio_assignment_rejects_a_residency_version_that_moved_under_it
    """
    residency, studio, _captured, current = _residency_studio_and_a_token_left_behind(api)
    get_success_data(_book_studio(api, residency, current), 201)

    validate_error(_book_studio(api, residency, current), ERR_STALE_VERSION)

    assert refresh_residency(api, residency)["version"] == current + 1
    assert_studio_day_ledger(refresh_studio(api, studio), OCCUPIED_DAYS, 1)
    assert len(studio_assignments_for(api, residency.residency_id)) == 1


def test_the_version_check_outranks_the_facility_checks(api):
    """Two faults at once, and the caller hears about the stale number.

    PRD: "The stale-version comparison itself is evaluated early — after path and
    foreign-key resolution and after the request body has been checked for shape and
    range, but before any domain state, safety, temporal, capacity or fiscal rule is
    consulted."

    Design: Corner/cross_cutting_complexity_layers/studio_assignment_rejects_a_residency_version_that_moved_under_it
    """
    residency, _studio, captured, current = _residency_studio_and_a_token_left_behind(api)
    unfit = create_studio(api, **UNFIT_STUDIO)

    validate_error(_book_studio(api, residency, captured, unfit), ERR_STALE_VERSION)

    validate_error(
        _book_studio(api, residency, current, unfit), ERR_STUDIO_CAPABILITY_MISMATCH
    )


def test_an_absent_studio_token_is_a_shape_error_and_not_a_conflict(api):
    """Leaving the field out is a different complaint from getting it wrong.

    PRD: "Where a version field is required it is a required field: omitting it is a
    shape violation reported as `ERR_VALIDATION` (HTTP 400), not a stale-version
    rejection."

    Design: Corner/cross_cutting_complexity_layers/studio_assignment_rejects_a_residency_version_that_moved_under_it
    """
    residency, _studio, _captured, _current = _residency_studio_and_a_token_left_behind(
        api
    )

    validate_error(_book_studio(api, residency, None), ERR_VALIDATION)

    assert studio_assignments_for(api, residency.residency_id) == []


CHECK_IN = "2026-11-02"
CHECK_OUT = "2026-12-28"
BED_NIGHTS = 56
WIDER_ACCESS = {"accessibility_features": ["STEP_FREE", "ROLL_IN_SHOWER"]}
LONGER_SESSION_WEEKS = 9


def _unit_and_a_token_left_behind(api):
    """A scheduled resident and a single-bed unit whose version a revision moved on."""
    cycle, _applicant, residency = setup_scheduled_residency(
        api,
        clock=CLOCK,
        session_start_date=SESSION_START,
        session_length_weeks=SESSION_WEEKS,
    )
    unit = create_housing_unit(api, code="H-01")
    captured = unit.version
    moved = get_success_data(
        api.update_housing_unit(
            unit.housing_unit_id, dict(WIDER_ACCESS), ADMIN_HEADERS
        )
    )
    return cycle, residency, unit, captured, moved["version"]


def _book_bed(api, unit, residency, expected_version):
    """The bed booking as program staff records it, returning the raw response."""
    return api.create_housing_assignment(
        make_housing_assignment_payload(
            unit.housing_unit_id,
            residency.residency_id,
            CHECK_IN,
            CHECK_OUT,
            expected_version,
            meal_plan_selected=True,
        ),
        ADMIN_HEADERS,
    )


def test_a_bed_booking_replaying_an_old_unit_version_is_refused(api):
    """The accessibility revision left the caller's number behind.

    PRD: "Creating a housing assignment requires the non-optional field
    `expected_housing_unit_version`, carrying the `version` of the target
    `HousingUnit` as the client last observed it."

    Design: Corner/cross_cutting_complexity_layers/housing_assignment_rejects_a_unit_version_that_moved_under_it
    """
    _cycle, residency, unit, captured, current = _unit_and_a_token_left_behind(api)
    assert current == captured + 1

    validate_error(_book_bed(api, unit, residency, captured), ERR_STALE_VERSION)

    assert refresh_housing_unit(api, unit)["version"] == current


def test_the_refused_bed_booking_left_the_unit_empty(api):
    """No night was taken and no row was written.

    PRD: "This is what prevents a bed from being booked against an occupancy picture
    — the unit's bed-night ledger, its released rows — that has already moved on."

    Design: Corner/cross_cutting_complexity_layers/housing_assignment_rejects_a_unit_version_that_moved_under_it
    """
    _cycle, residency, unit, captured, _current = _unit_and_a_token_left_behind(api)

    validate_error(_book_bed(api, unit, residency, captured), ERR_STALE_VERSION)

    assert_housing_bed_night_ledger(refresh_housing_unit(api, unit), 0)
    assert housing_assignments_for(api, residency.residency_id) == []
    _rows, meta = validate_paginated(
        api.list_housing_assignments(
            ADMIN_HEADERS, {"housing_unit_id": unit.housing_unit_id}
        )
    )
    assert meta["total_count"] == 0
    assert refresh_residency(api, residency)["assigned_housing_unit_code"] is None


def test_the_current_unit_token_succeeds_with_the_half_open_night_count(api):
    """Fifty-six nights from the second to the twenty-eighth, exclusive at the end.

    PRD: "Housing intervals are **half-open**, written `[check_in_date,
    check_out_date)`: the resident occupies a bed on the check-in night and every
    night up to but **not** including the check-out date, so `bed_nights` is simply
    the check-out date minus the check-in date."

    Design: Corner/cross_cutting_complexity_layers/housing_assignment_rejects_a_unit_version_that_moved_under_it
    """
    _cycle, residency, unit, captured, current = _unit_and_a_token_left_behind(api)
    validate_error(_book_bed(api, unit, residency, captured), ERR_STALE_VERSION)

    booked = get_success_data(_book_bed(api, unit, residency, current), 201)

    assert booked["status"] == "ACTIVE"
    assert booked["bed_nights"] == BED_NIGHTS
    assert booked["meal_plan_selected"] is True
    assert_housing_bed_night_ledger(refresh_housing_unit(api, unit), BED_NIGHTS)


def test_a_successful_booking_invalidates_every_outstanding_token_on_the_unit(api):
    """The second caller loses the race on the version, not on the calendar.

    PRD: "The server recomputes the unit's `occupied_bed_nights`, sets the
    residency's `assigned_housing_unit_code` to the unit's `code`, and advances the
    unit's and the residency's `version` by 1 each."

    Design: Corner/cross_cutting_complexity_layers/housing_assignment_rejects_a_unit_version_that_moved_under_it
    """
    cycle, residency, unit, _captured, current = _unit_and_a_token_left_behind(api)
    get_success_data(_book_bed(api, unit, residency, current), 201)
    rival = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, rival, SESSION_START, SESSION_WEEKS)

    validate_error(_book_bed(api, unit, rival, current), ERR_STALE_VERSION)

    assert refresh_housing_unit(api, unit)["version"] == current + 1
    assert refresh_residency(api, residency)["assigned_housing_unit_code"] == unit.code
    assert housing_assignments_for(api, rival.residency_id) == []


def test_the_guarded_parent_is_the_unit_and_not_the_residency(api):
    """Moving the residency's own version does not spoil a freshly read unit token.

    PRD: "Note that the housing OCC guard is taken on the **unit**, not on the
    residency — the opposite parent from the studio booking's guard."

    Design: Corner/cross_cutting_complexity_layers/housing_assignment_rejects_a_unit_version_that_moved_under_it
    """
    _cycle, residency, unit, _captured, current = _unit_and_a_token_left_behind(api)
    before = refresh_residency(api, residency)["version"]
    rescheduled = schedule_residency(api, residency, SESSION_START, LONGER_SESSION_WEEKS)
    assert rescheduled["version"] > before

    booked = get_success_data(_book_bed(api, unit, residency, current), 201)

    assert booked["bed_nights"] == BED_NIGHTS


def test_each_unit_carries_its_own_counter(api):
    """A number read from the unit next door is simply the wrong number.

    PRD: "The service therefore guards all three with optimistic concurrency control
    on the **parent** resource's `version`."

    Design: Corner/cross_cutting_complexity_layers/housing_assignment_rejects_a_unit_version_that_moved_under_it
    """
    _cycle, residency, unit, _captured, current = _unit_and_a_token_left_behind(api)
    neighbour = create_housing_unit(api, code="H-02")
    for features in (["STEP_FREE"], ["STEP_FREE", "ROLL_IN_SHOWER"]):
        get_success_data(
            api.update_housing_unit(
                neighbour.housing_unit_id,
                {"accessibility_features": features},
                ADMIN_HEADERS,
            )
        )
    borrowed = refresh_housing_unit(api, neighbour)["version"]
    assert borrowed != current

    validate_error(_book_bed(api, unit, residency, borrowed), ERR_STALE_VERSION)

    booked = get_success_data(_book_bed(api, unit, residency, current), 201)
    assert booked["housing_unit_id"] == unit.housing_unit_id


def test_the_release_path_is_not_version_guarded(api):
    """Handing the bed back takes no token at all, and still moves the unit on.

    PRD: "No other endpoint in this system takes a version field, and no other
    endpoint may reject a request with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/housing_assignment_rejects_a_unit_version_that_moved_under_it
    """
    _cycle, residency, unit, _captured, current = _unit_and_a_token_left_behind(api)
    booked = get_success_data(_book_bed(api, unit, residency, current), 201)

    freed = release_housing_assignment(api, booked["id"], "the resident found a sublet")

    assert freed["status"] == "RELEASED"
    assert freed["released_reason"] == "the resident found a sublet"
    settled = refresh_housing_unit(api, unit)
    assert_housing_bed_night_ledger(settled, 0)
    assert settled["version"] == current + 2
    assert refresh_residency(api, residency)["assigned_housing_unit_code"] is None
