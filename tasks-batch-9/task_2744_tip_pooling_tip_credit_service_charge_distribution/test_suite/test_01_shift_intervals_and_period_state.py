"""Queue A — interval conventions on shifts and pay periods, and the
period-state gate that gets in the way of an otherwise perfect shift."""
from test_helpers import (
    ApiErrorId,
    PREPARER,
    assert_pay_period_rollups_zero,
    close_shift,
    compute_period,
    create_pay_period_payload,
    create_shift_payload,
    declare_shift_tips,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_role_assignment,
    new_shift,
    read_pay_period,
    reopen_period,
    set_logical_clock,
    setup_texas_wage_world,
    validate_error,
    validate_paginated,
    validate_success,
    void_shift,
)

EXISTING_START = "2026-08-04T16:00:00Z"
EXISTING_END = "2026-08-05T00:00:00Z"


def _setup_one_existing_shift() -> dict:
    """The Texas wage world plus one OPEN shift running 16:00 to midnight."""
    world = setup_texas_wage_world()
    world["shift_1"] = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
        business_date="2026-08-04T00:00:00Z",
        start_at=EXISTING_START,
        end_at=EXISTING_END,
    )
    return world


def _adjacent_payload(world: dict) -> dict:
    """A shift starting exactly when the existing one ends."""
    return create_shift_payload(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
        business_date="2026-08-05T00:00:00Z",
        start_at="2026-08-05T00:00:00Z",
        end_at="2026-08-05T04:00:00Z",
    )


def _intersecting_payload(world: dict) -> dict:
    """A shift starting one hour before the existing one ends."""
    return create_shift_payload(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
        business_date="2026-08-04T00:00:00Z",
        start_at="2026-08-04T23:00:00Z",
        end_at="2026-08-05T02:00:00Z",
    )


# ---------------------------------------------------------------------------
# resource_temporal_overlap / shift_half_open_interval_allows_adjacency_rejects_intersection
# ---------------------------------------------------------------------------
def test_shift_starting_exactly_when_the_previous_one_ends_is_accepted(api):
    """A shift whose start_at equals the incumbent's end_at only touches it.

    PRD §3.4: "A shift occupies the half-open interval that begins at `start_at`
    and runs up to but does not include `end_at`, and `end_at` must be strictly
    after `start_at`."
    PRD §3.4: "Then the shift's half-open interval must not intersect the
    interval of any non-`VOIDED` shift of the same `employee_id`, though
    intervals that merely touch at an endpoint are permitted; an intersection is
    `ERR_SHIFT_OVERLAP`."
    PRD §3.4: "From that interval the server derives `scheduled_minutes`, the
    whole number of minutes between the two instants."

    Design: Difficulty/resource_temporal_overlap/shift_half_open_interval_allows_adjacency_rejects_intersection
    """
    world = _setup_one_existing_shift()

    response = api.create_shift(_adjacent_payload(world), PREPARER)
    created = validate_success(response, 201)

    assert created["scheduled_minutes"] == 240, (
        "[16:00, 00:00) and [00:00, 04:00) only touch at the endpoint, so the "
        "four-hour shift must be accepted with 240 scheduled minutes"
    )
    assert created["time_status"] == "OPEN"

    rows, _meta = validate_paginated(
        api.list_shifts(PREPARER, params={"employee_id": world["employee"]["id"]})
    )
    assert len(rows) == 2, f"expected the incumbent plus the adjacent shift, got {len(rows)}"


def test_shift_intersecting_a_surviving_interval_is_rejected_even_after_voiding_the_other(api):
    """A one-hour intersection is refused, and voiding an unrelated shift does not cure it.

    PRD §2.10 rung 38: "The new shift's half-open interval from `start_at` up to
    but excluding `end_at` does not intersect the interval of any non-`VOIDED`
    shift of the same `employee_id`; touching endpoints are permitted —
    `ERR_SHIFT_OVERLAP`, 409, on `POST /shifts`."
    PRD §3.4: "A shift recorded in error is voided by a `PayrollPreparer`,
    optionally with a free-text `reason`."

    Design: Difficulty/resource_temporal_overlap/shift_half_open_interval_allows_adjacency_rejects_intersection
    """
    world = _setup_one_existing_shift()
    adjacent = validate_success(api.create_shift(_adjacent_payload(world), PREPARER), 201)

    validate_error(
        api.create_shift(_intersecting_payload(world), PREPARER),
        ApiErrorId.ERR_SHIFT_OVERLAP.value,
    )

    rows, _meta = validate_paginated(
        api.list_shifts(PREPARER, params={"employee_id": world["employee"]["id"]})
    )
    assert {row["id"] for row in rows} == {world["shift_1"]["id"], adjacent["id"]}, (
        "the rejected creation must not have persisted a third shift"
    )

    void_shift(adjacent["id"], reason="scheduled against the wrong employee")
    validate_error(
        api.create_shift(_intersecting_payload(world), PREPARER),
        ApiErrorId.ERR_SHIFT_OVERLAP.value,
    )


# ---------------------------------------------------------------------------
# resource_temporal_overlap / pay_period_inclusive_date_interval_rejects_any_shared_day
# ---------------------------------------------------------------------------
def test_pay_period_sharing_a_single_day_is_rejected_as_an_overlap(api):
    """One shared calendar day is enough, and the length rule stays silent.

    PRD §3.4: "Periods at a single unit may not overlap — the new period's
    inclusive interval from `start_date` through `end_date` may not intersect the
    interval of any existing period of the same `location_id` — and an
    intersection is refused with `ERR_PAY_PERIOD_OVERLAP`, evaluated before the
    length rule."
    PRD §3.4: "The length rule is exact: `end_date` must equal `start_date` plus
    exactly six days, so that the closed inclusive interval covers seven calendar
    days; anything else is refused with `ERR_PAY_PERIOD_LENGTH`."

    Design: Difficulty/resource_temporal_overlap/pay_period_inclusive_date_interval_rejects_any_shared_day
    """
    set_logical_clock()
    location = new_location()
    new_pay_period(location["id"])

    response = api.create_pay_period(
        create_pay_period_payload(
            location["id"],
            start_date="2026-08-09T00:00:00Z",
            end_date="2026-08-15T00:00:00Z",
        ),
        PREPARER,
    )
    validate_error(response, ApiErrorId.ERR_PAY_PERIOD_OVERLAP.value)


def test_pay_period_starting_the_day_after_the_incumbent_ends_is_accepted(api):
    """The very next start date is lawful and opens with every rollup at zero.

    PRD §3.4: "A newly opened period has `status` `OPEN`, `compute_variant` null,
    `computed_by_user_id` null, `approved_by_user_id` null, and every rollup at
    0."
    PRD §2.11: "All filters are optional, all are exact-match equality on the
    named field, and multiple filters combine conjunctively — a row must satisfy
    every supplied filter to appear."

    Design: Difficulty/resource_temporal_overlap/pay_period_inclusive_date_interval_rejects_any_shared_day
    """
    set_logical_clock()
    location = new_location()
    first = new_pay_period(location["id"])

    response = api.create_pay_period(
        create_pay_period_payload(
            location["id"],
            start_date="2026-08-10T00:00:00Z",
            end_date="2026-08-16T00:00:00Z",
        ),
        PREPARER,
    )
    second = validate_success(response, 201)

    assert second["status"] == "OPEN"
    assert second["compute_variant"] is None
    assert second["computed_by_user_id"] is None
    assert second["approved_by_user_id"] is None
    assert_pay_period_rollups_zero(second)

    rows, _meta = validate_paginated(
        api.list_pay_periods(PREPARER, params={"location_id": location["id"]})
    )
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / create_shift_into_computed_pay_period_returns_period_not_open
# ---------------------------------------------------------------------------
def _setup_computed_period_with_a_second_server() -> dict:
    """One Texas unit, two assigned SERVER employees, the first employee's
    480-minute shift CLOSED and DECLARED, and the period COMPUTED."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    employee_first = new_employee(
        location["id"], full_name="First Server", external_payroll_ref="C1"
    )
    employee_second = new_employee(
        location["id"], full_name="Late Server", external_payroll_ref="C2"
    )
    new_role_assignment(employee_first["id"], role_server["id"])
    new_role_assignment(employee_second["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])

    shift_first = new_shift(
        employee_first["id"], location["id"], role_server["id"], pay_period["id"]
    )
    close_shift(shift_first["id"])
    declare_shift_tips(shift_first["id"], employee_first["id"], 4000, 0)
    compute_period(pay_period["id"])

    return {
        "location": location,
        "role_server": role_server,
        "employee_first": employee_first,
        "employee_second": employee_second,
        "pay_period": pay_period,
        "shift_first": shift_first,
    }


def _late_shift_payload(world: dict) -> dict:
    return create_shift_payload(
        world["employee_second"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
        business_date="2026-08-05T00:00:00Z",
        start_at="2026-08-05T16:00:00Z",
        end_at="2026-08-06T00:00:00Z",
    )


def test_shift_creation_into_a_computed_period_is_refused_by_the_period_state(api):
    """The shift is well formed; only the period's COMPUTED state stops it.

    PRD §3.4: "The governing period named by `pay_period_id` must be `OPEN`,
    failing which `ERR_PAY_PERIOD_NOT_OPEN`."
    PRD §3.8: "It sets the period's `compute_variant` to `WEEKLY_AGGREGATE` and
    its `computed_by_user_id` to the acting `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/create_shift_into_computed_pay_period_returns_period_not_open
    """
    world = _setup_computed_period_with_a_second_server()

    validate_error(
        api.create_shift(_late_shift_payload(world), PREPARER),
        ApiErrorId.ERR_PAY_PERIOD_NOT_OPEN.value,
    )

    rows, _meta = validate_paginated(
        api.list_shifts(PREPARER, params={"pay_period_id": world["pay_period"]["id"]})
    )
    assert len(rows) == 1, f"the rejected shift must not have been stored, got {len(rows)}"

    period = read_pay_period(world["pay_period"]["id"])
    assert period["status"] == "COMPUTED"
    assert period["total_credited_minutes"] == 480
    assert period["compute_variant"] == "WEEKLY_AGGREGATE"


def test_identical_shift_payload_succeeds_once_the_period_is_reopened(api):
    """Reopening the week is the only change needed for the same payload to pass.

    PRD §3.8: "Reopening is what makes the period machine cyclic — `OPEN →
    COMPUTED → APPROVED → OPEN` — and the second compute may legitimately produce
    different numbers, because the shift inputs changed in between."
    PRD §3.4: "The governing period named by `pay_period_id` must be `OPEN`,
    failing which `ERR_PAY_PERIOD_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/create_shift_into_computed_pay_period_returns_period_not_open
    """
    world = _setup_computed_period_with_a_second_server()
    payload = _late_shift_payload(world)

    validate_error(
        api.create_shift(payload, PREPARER), ApiErrorId.ERR_PAY_PERIOD_NOT_OPEN.value
    )

    reopen_period(world["pay_period"]["id"])
    created = validate_success(api.create_shift(payload, PREPARER), 201)

    assert created["employee_id"] == world["employee_second"]["id"]
    assert created["scheduled_minutes"] == 480
    assert created["time_status"] == "OPEN"
    assert created["declaration_status"] == "UNDECLARED"
