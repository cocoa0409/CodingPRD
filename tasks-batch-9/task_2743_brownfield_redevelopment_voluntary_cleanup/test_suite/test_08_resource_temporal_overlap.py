"""
Two reservation rules on the same file that use opposite interval conventions.

Physical controls hold a sub-area over a closed inclusive interval and must be separated
by a changeover buffer, so touching intervals — and even intervals thirty days apart —
collide. Laboratory windows are half-open and only their simultaneous count matters, so a
window that starts exactly where another ends is free. Each rule is exercised at the exact
date where its own convention flips.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    ERR_CONTROL_COVERAGE_CONFLICT,
    ERR_LAB_CAPACITY_EXCEEDED,
    add_event,
    add_laboratory,
    add_plan,
    assert_fields,
    assert_pagination_meta,
    ids_of,
    monitoring_event_payload,
    site_control_payload,
    stage_assessed,
    stage_enrolled,
    stage_goals,
)

# ─── engineering_control_coverage_buffer_rejects_thirty_day_gap ─────────────────

SUB_AREA = "BLDG-B-SLAB"

BASE_FROM = "2027-01-01"
BASE_TO = "2027-06-30"

BACK_TO_BACK_FROM = "2027-07-01"
THIRTY_DAY_GAP_FROM = "2027-07-30"
THIRTY_ONE_DAY_GAP_FROM = "2027-07-31"
SUCCESSOR_TO = "2027-12-31"


def _parcel_with_one_physical_control(api):
    """
    A draft remedy holding a single vapour-mitigation installation over one sub-area.

    The installation is in `PROPOSED`, which is one of the four statuses the exclusivity
    comparison looks at, so every later proposal on the same sub-area has to clear it.
    """
    world = stage_enrolled(api)
    world.plan = add_plan(world)
    base = _propose(
        world,
        control_type="VAPOR_MITIGATION",
        coverage_from=BASE_FROM,
        coverage_to=BASE_TO,
        inspection_interval_days=90,
    )
    world.control = get_success_data(base, 201)
    return world


def _propose(world, **overrides):
    """Ask the consultant to propose one control over the shared sub-area."""
    payload = site_control_payload(
        world.site["id"],
        world.plan["id"],
        sub_area_code=SUB_AREA,
        **overrides,
    )
    return world.api.create_site_control(payload, world.consult_headers)


def test_the_base_installation_is_an_engineering_control(api):
    """
    The type alone decides whether the exclusivity rule applies at all.

    "`control_type` is one of `VAPOR_MITIGATION`, `ENGINEERED_CAP`, `GW_USE_RESTRICTION`
    or `DEED_RESTRICTION`, and from it the server derives `control_class`: `ENGINEERING`
    for `VAPOR_MITIGATION` and `ENGINEERED_CAP`, `INSTITUTIONAL` for `GW_USE_RESTRICTION`
    and `DEED_RESTRICTION`."

    Design: Difficulty/resource_temporal_overlap/engineering_control_coverage_buffer_rejects_thirty_day_gap
    """
    world = _parcel_with_one_physical_control(api)

    assert_fields(
        world.read_control(),
        control_class="ENGINEERING",
        status="PROPOSED",
        sub_area_code=SUB_AREA,
        coverage_from=BASE_FROM,
        coverage_to=BASE_TO,
        next_certification_due_on="2027-04-01",
        impairment_count=0,
        last_certified_on=None,
        impaired_since=None,
    )


def test_back_to_back_coverage_is_refused(api):
    """
    Starting the day after the incumbent ends is the case the buffer exists to reject.

    "The practical consequence is that back-to-back coverage — where one interval starts
    the day after the other ends — is rejected, and a gap of 31 days is the first
    separation the rule accepts."

    Design: Difficulty/resource_temporal_overlap/engineering_control_coverage_buffer_rejects_thirty_day_gap
    """
    world = _parcel_with_one_physical_control(api)

    response = _propose(
        world,
        control_type="VAPOR_MITIGATION",
        coverage_from=BACK_TO_BACK_FROM,
        coverage_to=SUCCESSOR_TO,
        inspection_interval_days=90,
    )
    validate_error(response, ERR_CONTROL_COVERAGE_CONFLICT, 409)


def test_a_thirty_day_gap_still_conflicts_and_thirty_one_days_is_accepted(api):
    """
    The buffer is inclusive at its far edge, so the flip is between two adjacent days.

    "Two intervals conflict when the new `coverage_from` falls on or before the existing
    `coverage_to` advanced by 30 days **and** the existing `coverage_from` falls on or
    before the new `coverage_to` advanced by 30 days."

    Design: Difficulty/resource_temporal_overlap/engineering_control_coverage_buffer_rejects_thirty_day_gap
    """
    world = _parcel_with_one_physical_control(api)

    refused = _propose(
        world,
        control_type="VAPOR_MITIGATION",
        coverage_from=THIRTY_DAY_GAP_FROM,
        coverage_to=SUCCESSOR_TO,
        inspection_interval_days=90,
    )
    validate_error(refused, ERR_CONTROL_COVERAGE_CONFLICT, 409)

    accepted = get_success_data(
        _propose(
            world,
            control_type="VAPOR_MITIGATION",
            coverage_from=THIRTY_ONE_DAY_GAP_FROM,
            coverage_to=SUCCESSOR_TO,
            inspection_interval_days=90,
        ),
        201,
    )
    assert_fields(
        accepted,
        status="PROPOSED",
        control_class="ENGINEERING",
        sub_area_code=SUB_AREA,
        coverage_from=THIRTY_ONE_DAY_GAP_FROM,
        coverage_to=SUCCESSOR_TO,
        next_certification_due_on="2027-10-29",
    )


def test_a_legal_restriction_may_cover_the_same_sub_area_at_the_same_time(api):
    """
    A recorded restriction occupies no ground, so it is outside the rule entirely.

    "`INSTITUTIONAL` controls are exempt from this rule entirely: a groundwater use
    restriction and a deed restriction can coexist over the same sub-area and the same
    dates."

    Design: Difficulty/resource_temporal_overlap/engineering_control_coverage_buffer_rejects_thirty_day_gap
    """
    world = _parcel_with_one_physical_control(api)

    restriction = get_success_data(
        _propose(
            world,
            control_type="DEED_RESTRICTION",
            coverage_from=BASE_FROM,
            coverage_to=SUCCESSOR_TO,
            inspection_interval_days=365,
        ),
        201,
    )
    assert_fields(
        restriction,
        status="PROPOSED",
        control_class="INSTITUTIONAL",
        sub_area_code=SUB_AREA,
        coverage_from=BASE_FROM,
        coverage_to=SUCCESSOR_TO,
        next_certification_due_on="2028-01-01",
    )


def test_the_sub_area_holds_only_the_three_controls_the_rule_allowed(api):
    """
    Every refusal left nothing behind, so the sub-area listing is the ledger of survivors.

    "Controls can be listed with filters on `site_id`, `remedial_action_plan_id`,
    `sub_area_code`, `status` and `control_class`, and read individually with their
    coverage interval and impairment counters."

    Design: Difficulty/resource_temporal_overlap/engineering_control_coverage_buffer_rejects_thirty_day_gap
    """
    world = _parcel_with_one_physical_control(api)
    _propose(
        world,
        control_type="VAPOR_MITIGATION",
        coverage_from=BACK_TO_BACK_FROM,
        coverage_to=SUCCESSOR_TO,
        inspection_interval_days=90,
    )
    _propose(
        world,
        control_type="VAPOR_MITIGATION",
        coverage_from=THIRTY_DAY_GAP_FROM,
        coverage_to=SUCCESSOR_TO,
        inspection_interval_days=90,
    )
    successor = get_success_data(
        _propose(
            world,
            control_type="VAPOR_MITIGATION",
            coverage_from=THIRTY_ONE_DAY_GAP_FROM,
            coverage_to=SUCCESSOR_TO,
            inspection_interval_days=90,
        ),
        201,
    )
    restriction = get_success_data(
        _propose(
            world,
            control_type="DEED_RESTRICTION",
            coverage_from=BASE_FROM,
            coverage_to=SUCCESSOR_TO,
            inspection_interval_days=365,
        ),
        201,
    )

    rows, meta = validate_paginated(
        world.api.list_site_controls(
            world.consult_headers, site_id=world.site["id"], sub_area_code=SUB_AREA
        )
    )
    assert len(rows) == 3, "only the base control, the 31-day successor and the restriction"
    assert_pagination_meta(meta, expected_total=3)
    assert set(ids_of(rows)) == {
        world.control["id"],
        successor["id"],
        restriction["id"],
    }


# ─── laboratory_half_open_window_capacity_counts_touching_as_free ────────────────

BUSY_LAB_NAME = "Cuyahoga Trace Labs"
BUSY_LAB_CODE = "NELAP-OH-204"
BUSY_LAB_CAPACITY = 2

FIRST_WINDOW = ("2027-03-01T00:00:00Z", "2027-03-10T00:00:00Z")
SECOND_WINDOW = ("2027-03-05T00:00:00Z", "2027-03-15T00:00:00Z")
OVERLAPPING_WINDOW = ("2027-03-09T00:00:00Z", "2027-03-12T00:00:00Z")
TOUCHING_WINDOW = ("2027-03-15T00:00:00Z", "2027-03-20T00:00:00Z")
TOUCH_AND_ONE_WINDOW = ("2027-03-10T00:00:00Z", "2027-03-14T00:00:00Z")


def _a_laboratory_at_exactly_its_capacity(api):
    """
    A two-slot bench carrying two intersecting reservations, plus a decoy elsewhere.

    The two reservations overlap each other across 5 to 9 March, so the bench is at its
    stated capacity for those days while each booking is individually lawful. The decoy
    holds the identical first window at the ten-slot laboratory, which is what makes the
    per-laboratory scoping observable.
    """
    world = stage_assessed(api)
    stage_goals(world)
    world.busy_lab = add_laboratory(
        world,
        lab_name=BUSY_LAB_NAME,
        certification_code=BUSY_LAB_CODE,
        concurrent_capacity=BUSY_LAB_CAPACITY,
    )

    world.decoy = add_event(
        world,
        cleanup_goal_id=world.goal_restricted["id"],
        monitoring_period_code="2027-M03-DECOY",
        sample_date="2027-03-02",
        window_start=FIRST_WINDOW[0],
        window_end=FIRST_WINDOW[1],
    )
    world.first = _schedule(
        world, "2027-M03-A", "2027-03-02", FIRST_WINDOW, world.goal_restricted
    )
    world.second = _schedule(
        world, "2027-M03-B", "2027-03-06", SECOND_WINDOW, world.goal_unrestricted
    )
    return world


def _request(world, code, sample_date, window, goal):
    """Ask the consultant to reserve one analysis window at the two-slot bench."""
    payload = monitoring_event_payload(
        world.site["id"],
        world.busy_lab["id"],
        goal["id"],
        monitoring_period_code=code,
        sample_date=sample_date,
        window_start=window[0],
        window_end=window[1],
    )
    return world.api.create_monitoring_event(payload, world.consult_headers)


def _schedule(world, code, sample_date, window, goal):
    """The same reservation, insisting that it be accepted."""
    return get_success_data(_request(world, code, sample_date, window, goal), 201)


def test_the_two_standing_reservations_are_each_individually_lawful(api):
    """
    Nothing is wrong with either booking on its own; only their count can fail.

    "A laboratory can only run so many analyses at once, and the check is an aggregate one
    — each existing reservation is individually legal, and it is their simultaneous count
    that fails."

    Design: Difficulty/resource_temporal_overlap/laboratory_half_open_window_capacity_counts_touching_as_free
    """
    world = _a_laboratory_at_exactly_its_capacity(api)

    for reservation in (world.first, world.second):
        assert_fields(
            reservation,
            status="SCHEDULED",
            result_status="PENDING",
            result_value_ugl=None,
            control_condition=None,
            laboratory_id=world.busy_lab["id"],
        )
    assert_fields(
        world.decoy,
        status="SCHEDULED",
        result_status="PENDING",
        laboratory_id=world.laboratory["id"],
    )


def test_a_window_intersecting_both_reservations_is_refused(api):
    """
    Two simultaneous analyses is what the bench declared, and a third one arrives.

    "If that count already equals or exceeds the laboratory's `concurrent_capacity`, the
    request is refused with `ERR_LAB_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/laboratory_half_open_window_capacity_counts_touching_as_free
    """
    world = _a_laboratory_at_exactly_its_capacity(api)

    response = _request(
        world, "2027-M03-C", "2027-03-10", OVERLAPPING_WINDOW, world.goal_restricted
    )
    validate_error(response, ERR_LAB_CAPACITY_EXCEEDED, 409)


def test_a_window_that_merely_touches_is_free(api):
    """
    Starting exactly where the later reservation ends intersects nothing at all.

    "Two half-open windows intersect when the new `window_start` is strictly before the
    existing `window_end` **and** the existing `window_start` is strictly before the new
    `window_end`; windows that merely touch — where one ends exactly when the next begins
    — do **not** conflict."

    Design: Difficulty/resource_temporal_overlap/laboratory_half_open_window_capacity_counts_touching_as_free
    """
    world = _a_laboratory_at_exactly_its_capacity(api)
    _request(world, "2027-M03-C", "2027-03-10", OVERLAPPING_WINDOW, world.goal_restricted)

    touching = _schedule(
        world, "2027-M03-D", "2027-03-16", TOUCHING_WINDOW, world.goal_restricted
    )
    assert_fields(
        touching,
        status="SCHEDULED",
        result_status="PENDING",
        result_value_ugl=None,
    )

    counted_once = _schedule(
        world, "2027-M03-E", "2027-03-11", TOUCH_AND_ONE_WINDOW, world.goal_restricted
    )
    assert_fields(counted_once, status="SCHEDULED", result_status="PENDING")


def test_the_bench_holds_four_reservations_and_the_decoy_is_not_among_them(api):
    """
    The refused window left nothing behind, and the other laboratory's booking is separate.

    "Events can be listed with filters on `site_id`, `laboratory_id`, `cleanup_goal_id`,
    `site_control_id`, `event_type` and `status`, and read individually with the reported
    result and derived `result_status` exposed."

    Design: Difficulty/resource_temporal_overlap/laboratory_half_open_window_capacity_counts_touching_as_free
    """
    world = _a_laboratory_at_exactly_its_capacity(api)
    _request(world, "2027-M03-C", "2027-03-10", OVERLAPPING_WINDOW, world.goal_restricted)
    touching = _schedule(
        world, "2027-M03-D", "2027-03-16", TOUCHING_WINDOW, world.goal_restricted
    )
    counted_once = _schedule(
        world, "2027-M03-E", "2027-03-11", TOUCH_AND_ONE_WINDOW, world.goal_restricted
    )

    rows, meta = validate_paginated(
        world.api.list_monitoring_events(
            world.consult_headers, laboratory_id=world.busy_lab["id"]
        )
    )
    assert len(rows) == 4, "the two standing reservations plus the two accepted windows"
    assert_pagination_meta(meta, expected_total=4)
    assert set(ids_of(rows)) == {
        world.first["id"],
        world.second["id"],
        touching["id"],
        counted_once["id"],
    }
    assert world.decoy["id"] not in ids_of(rows), (
        "the ten-slot laboratory's booking belongs to a different bench"
    )
