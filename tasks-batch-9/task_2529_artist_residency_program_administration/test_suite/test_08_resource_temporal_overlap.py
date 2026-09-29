"""Two calendars for two resources, and the day each boundary changes hands."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_HOUSING_INTERVAL_CONFLICT,
    ERR_STUDIO_CAPACITY_EXCEEDED,
    ERR_STUDIO_INTERVAL_CONFLICT,
    FACILITIES_HEADERS,
    assign_housing,
    assign_studio,
    create_applicant,
    create_housing_unit,
    create_residency,
    create_studio,
    get_success_data,
    housing_assignments_for,
    make_housing_assignment_payload,
    make_studio_assignment_payload,
    read_residency,
    refresh_housing_unit,
    refresh_residency,
    refresh_studio,
    schedule_residency,
    setup_open_cycle,
    studio_assignments_for,
    validate_error,
)

SESSION_A = ("2026-11-02", "2026-12-27")
INNER_WINDOW = ("2026-11-10", "2026-11-20")


def _two_residencies(api, second_start, second_weeks):
    """One eight-week residency from the 2nd, plus a second on its own calendar."""
    cycle = setup_open_cycle(api)
    sitting = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, sitting, SESSION_A[0], 8)
    waiting = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, waiting, second_start, second_weeks)
    return sitting, waiting


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


def _single_occupancy_world(api):
    """A private studio held for a whole session, and a follow-on tenant."""
    sitting, waiting = _two_residencies(api, "2026-12-28", 4)
    studio = create_studio(api)
    assert studio.studio["max_concurrent_residents"] == 1
    held = assign_studio(api, sitting, SESSION_A[0], SESSION_A[1], studio)
    assert held["status"] == "ACTIVE"
    assert held["occupied_days"] == 56
    assert refresh_residency(api, waiting)["session_end_date"] == "2027-01-24"
    return studio, waiting, held


def test_the_turnaround_buffer_blocks_the_day_after_the_last_occupied_day(api):
    """The requested window starts after the incumbent ends and still collides.

    PRD: "an existing assignment blocks from its own `start_date` through its
    `end_date` plus two days, and the requested window is likewise treated as
    extending two days past its `end_date`"

    Design: Difficulty/resource_temporal_overlap/studio_single_occupancy_closed_interval_plus_turnaround_buffer
    """
    studio, waiting, held = _single_occupancy_world(api)
    before = refresh_residency(api, waiting)

    validate_error(
        _book_studio(api, studio, waiting, ("2026-12-29", "2027-01-20")),
        ERR_STUDIO_INTERVAL_CONFLICT,
    )

    assert studio_assignments_for(api, waiting.residency_id) == []
    unmoved = refresh_residency(api, waiting)
    assert unmoved["version"] == before["version"]
    assert unmoved["assigned_studio_code"] is None
    ledger = refresh_studio(api, studio)
    assert ledger["active_assignment_count"] == 1
    assert ledger["reserved_resident_days"] == 56
    assert held["end_date"] == SESSION_A[1]


def test_the_buffer_is_exactly_two_days_wide_and_no_wider(api):
    """One day later the identical request is accepted, so the buffer ends there.

    PRD: "Concretely, a studio holding an active assignment ending on the 27th of
    a month is blocked through the 29th, so a request starting on the 29th
    conflicts while an otherwise identical request starting on the 30th does
    not."

    Design: Difficulty/resource_temporal_overlap/studio_single_occupancy_closed_interval_plus_turnaround_buffer
    """
    studio, waiting, _held = _single_occupancy_world(api)
    validate_error(
        _book_studio(api, studio, waiting, ("2026-12-29", "2027-01-20")),
        ERR_STUDIO_INTERVAL_CONFLICT,
    )

    accepted = get_success_data(
        _book_studio(api, studio, waiting, ("2026-12-30", "2027-01-20")), 201
    )

    assert accepted["status"] == "ACTIVE"
    assert accepted["selection_mode"] == "EXPLICIT"
    assert accepted["occupied_days"] == 22
    assert read_residency(api, waiting.residency_id)["assigned_studio_code"] == (
        studio.code
    )
    # Two disjoint windows on a private studio: the limit is a per-day headcount.
    shared_ledger = refresh_studio(api, studio)
    assert shared_ledger["active_assignment_count"] == 2
    assert shared_ledger["reserved_resident_days"] == 78


def test_the_buffer_also_extends_the_window_being_requested(api):
    """A window ending two days before the incumbent starts collides as well.

    PRD: "On a **single-occupancy** studio, where `max_concurrent_residents` is
    exactly 1, the requested window must not overlap any `ACTIVE` assignment of
    that studio under closed-interval semantics **extended by a two-day
    turnaround buffer** on each existing assignment"

    Design: Difficulty/resource_temporal_overlap/studio_single_occupancy_closed_interval_plus_turnaround_buffer
    """
    sitting, waiting = _two_residencies(api, SESSION_A[0], 8)
    studio = create_studio(api)
    held = assign_studio(api, sitting, INNER_WINDOW[0], INNER_WINDOW[1], studio)
    assert held["occupied_days"] == 11

    validate_error(
        _book_studio(api, studio, waiting, ("2026-11-02", "2026-11-08")),
        ERR_STUDIO_INTERVAL_CONFLICT,
    )
    accepted = get_success_data(
        _book_studio(api, studio, waiting, ("2026-11-02", "2026-11-07")), 201
    )

    assert accepted["occupied_days"] == 6
    assert refresh_studio(api, studio)["reserved_resident_days"] == 17


BED_WINDOW = ("2026-11-02", "2026-12-28")
NO_MEAL_SINGLE_BED = {"bed_count": 1, "meal_plan_included": False}


def _book_housing(api, unit, residency, check_in, check_out):
    """The raw bed booking, so a refusal can be inspected instead of raised."""
    current = refresh_housing_unit(api, unit)
    payload = make_housing_assignment_payload(
        unit.housing_unit_id,
        residency.residency_id,
        check_in,
        check_out,
        current["version"],
    )
    return api.create_housing_assignment(payload, ADMIN_HEADERS)


def _single_bed_world(api):
    """One bed held for every night of a session, and the next artist waiting."""
    sitting, waiting = _two_residencies(api, "2026-12-20", 4)
    unit = create_housing_unit(api, **NO_MEAL_SINGLE_BED)
    assert unit.unit["bed_count"] == 1
    assert unit.unit["meal_plan_included"] is False

    held = assign_housing(api, unit, sitting, BED_WINDOW[0], BED_WINDOW[1])
    assert held["status"] == "ACTIVE"
    assert held["bed_nights"] == 56
    assert refresh_housing_unit(api, unit)["occupied_bed_nights"] == 56
    assert refresh_residency(api, waiting)["session_end_date"] == "2027-01-16"
    return unit, waiting, held


def test_a_night_shared_with_the_sitting_resident_is_a_conflict(api):
    """Checking in the day before the bed is vacated shares one night.

    PRD: "On a **single-bed** unit, where `bed_count` is exactly 1, the requested
    window must share no night with any `ACTIVE` assignment of that unit: two
    half-open intervals overlap exactly when each one's check-in date falls
    strictly before the other's check-out date."

    Design: Difficulty/resource_temporal_overlap/housing_half_open_interval_permits_adjacent_check_in
    """
    unit, waiting, held = _single_bed_world(api)
    before = refresh_housing_unit(api, unit)

    validate_error(
        _book_housing(api, unit, waiting, "2026-12-27", "2027-01-17"),
        ERR_HOUSING_INTERVAL_CONFLICT,
    )

    assert housing_assignments_for(api, waiting.residency_id) == []
    unchanged = refresh_housing_unit(api, unit)
    assert unchanged["occupied_bed_nights"] == 56
    assert unchanged["version"] == before["version"]
    assert read_residency(api, waiting.residency_id)["assigned_housing_unit_code"] is None
    assert held["check_out_date"] == BED_WINDOW[1]


def test_checking_in_on_the_check_out_date_shares_no_night(api):
    """One day later the same request is accepted with no buffer in the way.

    PRD: "Adjacency is explicitly **not** a conflict — one resident checking out
    on a date and another checking in on the same date share no night — and a
    genuine overlap is `ERR_HOUSING_INTERVAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/housing_half_open_interval_permits_adjacent_check_in
    """
    unit, waiting, held = _single_bed_world(api)
    validate_error(
        _book_housing(api, unit, waiting, "2026-12-27", "2027-01-17"),
        ERR_HOUSING_INTERVAL_CONFLICT,
    )

    accepted = get_success_data(
        _book_housing(api, unit, waiting, "2026-12-28", "2027-01-17"), 201
    )

    assert accepted["status"] == "ACTIVE"
    assert accepted["check_in_date"] == held["check_out_date"]
    assert accepted["meal_plan_selected"] is False
    assert read_residency(api, waiting.residency_id)["assigned_housing_unit_code"] == (
        unit.code
    )


def test_the_check_out_night_is_never_counted_on_either_booking(api):
    """Two adjacent stays on one bed add up with the shared date counted once.

    PRD: "Housing intervals are **half-open**, written `[check_in_date,
    check_out_date)`: the resident occupies a bed on the check-in night and every
    night up to but **not** including the check-out date, so `bed_nights` is
    simply the check-out date minus the check-in date."

    Design: Difficulty/resource_temporal_overlap/housing_half_open_interval_permits_adjacent_check_in
    """
    unit, waiting, held = _single_bed_world(api)

    accepted = get_success_data(
        _book_housing(api, unit, waiting, "2026-12-28", "2027-01-17"), 201
    )

    assert accepted["bed_nights"] == 20
    assert refresh_housing_unit(api, unit)["occupied_bed_nights"] == 76
    rows = housing_assignments_for(api, waiting.residency_id)
    assert [row["bed_nights"] for row in rows] == [20]
    assert held["bed_nights"] == 56


SHARED_STUDIO = {"max_concurrent_residents": 2}
CROWDED_WINDOW = ("2026-11-15", "2026-11-18")
QUIET_WINDOW = ("2026-12-01", "2026-12-10")


def _three_residencies(api):
    """Three artists sharing one eight-week session in the same cycle."""
    cycle = setup_open_cycle(api)
    residencies = []
    for _ in range(3):
        residency = create_residency(api, cycle, create_applicant(api))
        schedule_residency(api, residency, SESSION_A[0], 8)
        residencies.append(residency)
    return residencies


def _crowded_shared_studio(api):
    """A two-person studio already carrying two tenants over the middle weeks."""
    first, second, third = _three_residencies(api)
    studio = create_studio(api, **SHARED_STUDIO)
    assert studio.studio["max_concurrent_residents"] == 2

    whole = assign_studio(api, first, SESSION_A[0], SESSION_A[1], studio)
    inner = assign_studio(api, second, INNER_WINDOW[0], INNER_WINDOW[1], studio)
    return studio, third, whole, inner


def test_a_shared_studio_admits_a_tenant_whose_window_sits_inside_another(api):
    """Full overlap on a shared studio is not an interval problem at all.

    PRD: "On a **shared** studio, where `max_concurrent_residents` is greater
    than 1, the interval-conflict rule does not apply at all and overlapping
    tenants are permitted; instead, for every single calendar date of the
    requested window, the number of `ACTIVE` assignments of that studio covering
    that date, counting the request itself, must not exceed
    `max_concurrent_residents`."

    Design: Difficulty/resource_temporal_overlap/studio_shared_headcount_aggregate_capacity_exceeded
    """
    studio, _third, whole, inner = _crowded_shared_studio(api)

    assert whole["status"] == "ACTIVE"
    assert whole["occupied_days"] == 56
    assert inner["status"] == "ACTIVE"
    assert inner["occupied_days"] == 11
    assert inner["start_date"] == INNER_WINDOW[0]
    ledger = refresh_studio(api, studio)
    assert ledger["active_assignment_count"] == 2
    assert ledger["reserved_resident_days"] == 67


def test_a_third_body_on_a_two_person_day_exceeds_the_headcount(api):
    """Legal against each incumbent alone, refused against the pair together.

    PRD: "Each individual overlap may be legal while the collection is not, and
    the excess is `ERR_STUDIO_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/studio_shared_headcount_aggregate_capacity_exceeded
    """
    studio, third, _whole, _inner = _crowded_shared_studio(api)

    validate_error(
        _book_studio(api, studio, third, CROWDED_WINDOW), ERR_STUDIO_CAPACITY_EXCEEDED
    )

    assert studio_assignments_for(api, third.residency_id) == []
    ledger = refresh_studio(api, studio)
    assert ledger["active_assignment_count"] == 2
    assert ledger["reserved_resident_days"] == 67
    assert read_residency(api, third.residency_id)["assigned_studio_code"] is None


def test_a_quieter_stretch_of_the_same_studio_takes_the_same_artist(api):
    """Where the census is one, a third row is written on a two-person studio.

    PRD: "The server recomputes the studio's `reserved_resident_days` and
    `active_assignment_count`, sets the residency's `assigned_studio_code` to the
    chosen studio's `code`, and advances the studio's and the residency's
    `version` by 1 each."

    Design: Difficulty/resource_temporal_overlap/studio_shared_headcount_aggregate_capacity_exceeded
    """
    studio, third, _whole, _inner = _crowded_shared_studio(api)
    validate_error(
        _book_studio(api, studio, third, CROWDED_WINDOW), ERR_STUDIO_CAPACITY_EXCEEDED
    )

    accepted = get_success_data(_book_studio(api, studio, third, QUIET_WINDOW), 201)

    assert accepted["status"] == "ACTIVE"
    assert accepted["occupied_days"] == 10
    ledger = refresh_studio(api, studio)
    # More rows than the studio's headcount, because the limit is taken per day.
    assert ledger["active_assignment_count"] == 3
    assert ledger["reserved_resident_days"] == 77
    assert read_residency(api, third.residency_id)["assigned_studio_code"] == studio.code


def test_the_census_is_taken_per_day_and_one_shared_day_is_enough(api):
    """Overlapping the departing tenant by a single date decides the request.

    PRD: "for every single calendar date of the requested window, the number of
    `ACTIVE` assignments of that studio covering that date, counting the request
    itself, must not exceed `max_concurrent_residents`"

    Design: Difficulty/resource_temporal_overlap/studio_shared_headcount_aggregate_capacity_exceeded
    """
    studio, third, _whole, inner = _crowded_shared_studio(api)
    assert inner["end_date"] == INNER_WINDOW[1]

    validate_error(
        _book_studio(api, studio, third, (INNER_WINDOW[1], QUIET_WINDOW[1])),
        ERR_STUDIO_CAPACITY_EXCEEDED,
    )
    accepted = get_success_data(
        _book_studio(api, studio, third, ("2026-11-21", QUIET_WINDOW[1])), 201
    )

    assert accepted["occupied_days"] == 20
    assert refresh_studio(api, studio)["reserved_resident_days"] == 87
