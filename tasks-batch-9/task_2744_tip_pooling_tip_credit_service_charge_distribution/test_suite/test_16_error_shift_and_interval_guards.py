"""Queue B — §1.6 error corners on the busiest write and on the intervals around it:
the ten-check shift ladder, the card-tip ceiling that only a declaration can break, the
exact seven-day week, the role-scoped assignment overlap and the separation date."""
from test_helpers import (
    ADMIN,
    PREPARER,
    ApiErrorId,
    ApiClient,
    assert_instant_equals,
    close_shift,
    create_pay_period_payload,
    create_role_assignment_payload,
    create_shift_payload,
    declare_tips_payload,
    make_employee_headers,
    make_shift_manager_headers,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_role_assignment,
    new_shift,
    read_shift,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"


def _shift_guard_world() -> dict:
    """A Texas unit with a side-work-eligible SERVER role and an ineligible DISH role,
    Ana assigned to both, and two consecutive weeks P1 and P2."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    role_dish = new_job_role(
        code="DISH",
        title="Dishwasher",
        tip_status="NON_TIPPED",
        pool_contribution_pct_bps=0,
        pool_share_points=5,
        side_work_eligible=False,
    )
    ana = new_employee(location["id"])
    new_role_assignment(ana["id"], role_server["id"])
    new_role_assignment(ana["id"], role_dish["id"], is_primary=False)
    return {
        "location": location,
        "role_server": role_server,
        "role_dish": role_dish,
        "ana": ana,
        "p1": new_pay_period(location["id"]),
        "p2": new_pay_period(
            location["id"],
            start_date="2026-08-10T00:00:00Z",
            end_date="2026-08-16T00:00:00Z",
        ),
    }


def _shift_attempt(api: ApiClient, world: dict, **overrides):
    """One POST /shifts by the front-of-house supervisor, defaults on the SERVER role in
    P1 on 2026-08-04."""
    payload = create_shift_payload(
        world["ana"]["id"],
        world["location"]["id"],
        overrides.pop("job_role_id", world["role_server"]["id"]),
        overrides.pop("pay_period_id", world["p1"]["id"]),
        **overrides,
    )
    return api.create_shift(payload, make_shift_manager_headers(world["ana"]["id"]))


# ---------------------------------------------------------------------------
# errors / shift_side_work_date_and_sales_guards_rejected
# ---------------------------------------------------------------------------
def test_seven_refusals_walk_the_shift_ladder_in_its_pinned_order(api):
    """Each probe names the earliest rule it breaks, and only the eighth shift is stored.

    PRD §3.4: "Ten checks guard a shift creation, and their relative order matters
    whenever a single request breaks more than one. The governing period named by
    `pay_period_id` must be `OPEN`, failing which `ERR_PAY_PERIOD_NOT_OPEN`. Then, if
    `side_work_minutes` is greater than 0, the shift's job role must have
    `side_work_eligible` true, failing which `ERR_SIDE_WORK_NOT_ELIGIBLE`."
    PRD §3.4: "Then neither `business_date` may be after the logical clock's date nor
    `end_at` after the logical clock's instant, failing which `ERR_SHIFT_FUTURE_DATE`.
    Then `business_date` must fall inside the period's inclusive date interval and both
    `start_at` and `end_at` must fall on `business_date` itself or on the calendar day
    immediately after it — an overnight close is expected, a shift two days long is not —
    failing which `ERR_BUSINESS_DATE_OUT_OF_PERIOD`."
    PRD §3.4: "Then `side_work_minutes` may not exceed the shift's whole minutes and
    `max_continuous_side_work_minutes` may not exceed `side_work_minutes`, failing which
    `ERR_SIDE_WORK_EXCEEDS_SHIFT`. Finally `charged_sales_cents` may not exceed
    `gross_sales_cents`, failing which `ERR_CHARGED_SALES_EXCEED_GROSS_SALES`."
    PRD §3.4: "A newly recorded shift starts with `time_status` `OPEN` and
    `declaration_status` `UNDECLARED`, with `shift_tip_pool_id` null and with
    `declared_cash_tips_cents`, `declared_charged_tips_cents`, `declaration_count`,
    `non_tip_credit_minutes`, `tip_credit_eligible_minutes`, `pool_contribution_cents`,
    `retained_tips_cents` and `shift_tip_credit_cents` all at 0."
    PRD §3.4: "From that interval the server derives `scheduled_minutes`, the whole number
    of minutes between the two instants."

    Design: Corner/errors/shift_side_work_date_and_sales_guards_rejected
    """
    world = _shift_guard_world()

    validate_error(
        _shift_attempt(
            api,
            world,
            job_role_id=world["role_dish"]["id"],
            side_work_minutes=60,
            max_continuous_side_work_minutes=20,
        ),
        ApiErrorId.ERR_SIDE_WORK_NOT_ELIGIBLE.value,
    )
    validate_error(
        _shift_attempt(
            api, world, side_work_minutes=500, max_continuous_side_work_minutes=20
        ),
        ApiErrorId.ERR_SIDE_WORK_EXCEEDS_SHIFT.value,
    )
    validate_error(
        _shift_attempt(
            api, world, side_work_minutes=60, max_continuous_side_work_minutes=90
        ),
        ApiErrorId.ERR_SIDE_WORK_EXCEEDS_SHIFT.value,
    )
    validate_error(
        _shift_attempt(
            api,
            world,
            pay_period_id=world["p2"]["id"],
            business_date="2026-08-12T00:00:00Z",
            start_at="2026-08-12T16:00:00Z",
            end_at="2026-08-13T00:00:00Z",
        ),
        ApiErrorId.ERR_SHIFT_FUTURE_DATE.value,
    )
    validate_error(
        _shift_attempt(
            api,
            world,
            business_date="2026-08-02T00:00:00Z",
            start_at="2026-08-02T16:00:00Z",
            end_at="2026-08-03T00:00:00Z",
        ),
        ApiErrorId.ERR_BUSINESS_DATE_OUT_OF_PERIOD.value,
    )
    validate_error(
        _shift_attempt(
            api,
            world,
            business_date="2026-08-20T00:00:00Z",
            start_at="2026-08-20T16:00:00Z",
            end_at="2026-08-21T00:00:00Z",
        ),
        ApiErrorId.ERR_SHIFT_FUTURE_DATE.value,
    )
    validate_error(
        _shift_attempt(api, world, gross_sales_cents=50000, charged_sales_cents=60000),
        ApiErrorId.ERR_CHARGED_SALES_EXCEED_GROSS_SALES.value,
    )

    stored = validate_success(
        _shift_attempt(
            api,
            world,
            side_work_minutes=96,
            max_continuous_side_work_minutes=30,
            gross_sales_cents=50000,
            charged_sales_cents=40000,
        ),
        expected_status=201,
    )
    assert stored["scheduled_minutes"] == 480
    assert stored["side_work_minutes"] == 96
    assert stored["max_continuous_side_work_minutes"] == 30
    assert stored["time_status"] == "OPEN"
    assert stored["declaration_status"] == "UNDECLARED"
    assert stored["non_tip_credit_minutes"] == 0
    assert stored["tip_credit_eligible_minutes"] == 0, (
        "a newly recorded shift carries no classified minutes; close does that"
    )

    _rows, meta = validate_paginated(api.list_shifts(PREPARER))
    assert meta["total_count"] == 1, "every rejection persisted nothing"


def test_a_card_tip_may_not_exceed_the_card_sale_that_carried_it(api):
    """The sales guard runs at creation and the tips guard at declaration, so a valid
    shift can still hold an invalid declaration.

    PRD §3.5: "Each of the three transitions requires the same two situational
    preconditions — the shift's `time_status` must be `CLOSED`, failing which
    `ERR_SHIFT_NOT_CLOSED`, and the shift's period must be `OPEN`, failing which
    `ERR_PAY_PERIOD_NOT_OPEN` — and each requires that `declared_charged_tips_cents` not
    exceed the shift's `charged_sales_cents`, since a card tip cannot exceed the card sale
    that carried it; a breach is `ERR_DECLARED_CHARGED_TIPS_EXCEED_CHARGED_SALES`."
    PRD §3.5: "Each of the three transitions writes the two declared amounts, overwriting
    whatever was there before, increments `declaration_count` by 1 — so a
    `declaration_count` of 1 marks an original declaration and 2 or more marks amendments
    — and recomputes `retained_tips_cents`."
    PRD §3.5: "`retained_tips_cents` is the shift's own money after pooling:
    `declared_cash_tips_cents` plus `declared_charged_tips_cents`, less whatever
    `pool_contribution_cents` the shift has been debited."

    Design: Corner/errors/shift_side_work_date_and_sales_guards_rejected
    """
    world = _shift_guard_world()
    shift = new_shift(
        world["ana"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["p1"]["id"],
        headers=make_shift_manager_headers(world["ana"]["id"]),
        side_work_minutes=96,
        max_continuous_side_work_minutes=30,
        gross_sales_cents=50000,
        charged_sales_cents=40000,
    )
    close_shift(shift["id"], make_shift_manager_headers(world["ana"]["id"]))

    validate_error(
        api.declare_tips(
            shift["id"],
            declare_tips_payload(1000, 50000),
            make_employee_headers(world["ana"]["id"]),
        ),
        ApiErrorId.ERR_DECLARED_CHARGED_TIPS_EXCEED_CHARGED_SALES.value,
    )
    refused = read_shift(shift["id"])
    assert refused["declaration_status"] == "UNDECLARED"
    assert refused["declaration_count"] == 0

    declared = validate_success(
        api.declare_tips(
            shift["id"],
            declare_tips_payload(4000, 1000),
            make_employee_headers(world["ana"]["id"]),
        )
    )
    assert declared["declared_cash_tips_cents"] == 4000
    assert declared["declared_charged_tips_cents"] == 1000
    assert declared["declaration_status"] == "DECLARED"
    assert declared["declaration_count"] == 1
    assert declared["retained_tips_cents"] == 5000, "unpooled, so it keeps everything"


# ---------------------------------------------------------------------------
# errors / pay_period_assignment_and_separation_interval_guards_rejected
# ---------------------------------------------------------------------------
def _interval_world() -> dict:
    """A Texas unit with two tipped job roles, Ana holding an open-ended SERVER
    assignment from 2026-07-01, and Zed who left on 2026-08-05."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    role_bar = new_job_role(
        code="BAR",
        title="Bartender",
        tip_status="TIPPED",
        pool_contribution_pct_bps=1000,
        pool_share_points=8,
    )
    ana = new_employee(location["id"])
    zed = new_employee(
        location["id"],
        full_name="Zed Okafor",
        external_payroll_ref="E2",
        separation_date="2026-08-05T00:00:00Z",
    )
    new_role_assignment(ana["id"], role_server["id"])
    return {
        "location": location,
        "role_server": role_server,
        "role_bar": role_bar,
        "ana": ana,
        "zed": zed,
    }


def test_the_week_is_exactly_seven_calendar_days_and_neither_bound_is_soft(api):
    """One day long and one day short are the same error; only the seven-day week is stored.

    PRD §3.4: "The length rule is exact: `end_date` must equal `start_date` plus exactly
    six days, so that the closed inclusive interval covers seven calendar days; anything
    else is refused with `ERR_PAY_PERIOD_LENGTH`."
    PRD §3.4: "Payroll at a unit is organised into pay periods, each of which is exactly
    one seven-day workweek."
    PRD §3.4: "A newly opened period has `status` `OPEN`, `compute_variant` null,
    `computed_by_user_id` null, `approved_by_user_id` null, and every rollup at 0."

    Design: Corner/errors/pay_period_assignment_and_separation_interval_guards_rejected
    """
    world = _interval_world()

    validate_error(
        api.create_pay_period(
            create_pay_period_payload(
                world["location"]["id"],
                start_date="2026-08-03T00:00:00Z",
                end_date="2026-08-10T00:00:00Z",
            ),
            PREPARER,
        ),
        ApiErrorId.ERR_PAY_PERIOD_LENGTH.value,
    )
    validate_error(
        api.create_pay_period(
            create_pay_period_payload(
                world["location"]["id"],
                start_date="2026-08-03T00:00:00Z",
                end_date="2026-08-08T00:00:00Z",
            ),
            PREPARER,
        ),
        ApiErrorId.ERR_PAY_PERIOD_LENGTH.value,
    )

    period = validate_success(
        api.create_pay_period(
            create_pay_period_payload(
                world["location"]["id"],
                start_date="2026-08-03T00:00:00Z",
                end_date="2026-08-09T00:00:00Z",
            ),
            PREPARER,
        ),
        expected_status=201,
    )
    assert period["status"] == "OPEN"
    assert_instant_equals(period["start_date"], "2026-08-03T00:00:00Z", "start_date")
    assert_instant_equals(period["end_date"], "2026-08-09T00:00:00Z", "end_date")

    _rows, meta = validate_paginated(api.list_pay_periods(PREPARER))
    assert meta["total_count"] == 1, "eight days and six days both persisted nothing"


def test_the_overlap_key_is_the_employee_and_the_role_together(api):
    """The same unbounded interval collides on SERVER and is accepted on BAR.

    PRD §3.2: "First, the new assignment's date interval — treating a null `effective_to`
    as extending indefinitely — may not intersect the interval of any existing assignment
    for the same `employee_id` and the same `job_role_id`; an intersection is refused with
    `ERR_ASSIGNMENT_OVERLAP`."
    PRD §3.2: "`dual_job` is true on an assignment when the same employee holds another
    assignment whose date interval intersects this one and whose job role carries a
    different `tip_status` — a bartender who also works mornings as a prep cook, for
    instance."
    PRD §3.2: "`dual_job` is false by default and on an employee holding a single job it
    stays false."

    Design: Corner/errors/pay_period_assignment_and_separation_interval_guards_rejected
    """
    world = _interval_world()

    validate_error(
        api.create_role_assignment(
            create_role_assignment_payload(
                world["ana"]["id"],
                world["role_server"]["id"],
                effective_from="2026-08-01T00:00:00Z",
                is_primary=False,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_ASSIGNMENT_OVERLAP.value,
    )

    bar = validate_success(
        api.create_role_assignment(
            create_role_assignment_payload(
                world["ana"]["id"],
                world["role_bar"]["id"],
                effective_from="2026-08-01T00:00:00Z",
                tip_credit_notice_acknowledged_at="2026-08-01T00:00:00Z",
                is_primary=False,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert bar["job_role_id"] == world["role_bar"]["id"]

    rows, meta = validate_paginated(
        api.list_role_assignments(ADMIN, params={"employee_id": world["ana"]["id"]})
    )
    assert meta["total_count"] == 2, "the refused SERVER duplicate was never stored"
    for row in rows:
        assert row["dual_job"] is False, (
            "SERVER and BAR are both TIPPED, and dual_job needs a differing tip_status"
        )


def test_a_separation_date_closes_the_future_and_leaves_the_past_recordable(api):
    """Zed may be assigned and paid before 2026-08-05 and for nothing dated after it.

    PRD §3.2: "Second, if the employee carries a `separation_date`, the new assignment's
    `effective_from` may not be after it, and a breach is refused with
    `ERR_EMPLOYEE_SEPARATED`."
    PRD §3.4: "Then, if the employee carries a `separation_date`, `business_date` may not
    be after it, failing which `ERR_EMPLOYEE_SEPARATED`; a terminated employee's
    pre-separation history may still be recorded, but no work may be dated past the
    separation."
    PRD §3.4: "Then the employee must hold a role assignment for the requested
    `job_role_id` whose date interval contains `business_date`, failing which
    `ERR_NO_ACTIVE_ROLE_ASSIGNMENT`."
    PRD §3.4: "From that interval the server derives `scheduled_minutes`, the whole number
    of minutes between the two instants."

    Design: Corner/errors/pay_period_assignment_and_separation_interval_guards_rejected
    """
    world = _interval_world()
    period = new_pay_period(world["location"]["id"])
    manager = make_shift_manager_headers(world["ana"]["id"])

    validate_error(
        api.create_role_assignment(
            create_role_assignment_payload(
                world["zed"]["id"],
                world["role_server"]["id"],
                effective_from="2026-08-10T00:00:00Z",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_EMPLOYEE_SEPARATED.value,
    )
    granted = validate_success(
        api.create_role_assignment(
            create_role_assignment_payload(
                world["zed"]["id"], world["role_server"]["id"]
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert granted["effective_to"] is None, "open-ended, so it does cover 2026-08-06"

    validate_error(
        api.create_shift(
            create_shift_payload(
                world["zed"]["id"],
                world["location"]["id"],
                world["role_server"]["id"],
                period["id"],
                business_date="2026-08-06T00:00:00Z",
                start_at="2026-08-06T16:00:00Z",
                end_at="2026-08-07T00:00:00Z",
            ),
            manager,
        ),
        ApiErrorId.ERR_EMPLOYEE_SEPARATED.value,
    )

    final_shift = validate_success(
        api.create_shift(
            create_shift_payload(
                world["zed"]["id"],
                world["location"]["id"],
                world["role_server"]["id"],
                period["id"],
            ),
            manager,
        ),
        expected_status=201,
    )
    assert final_shift["scheduled_minutes"] == 480, (
        "the guard is scoped to the date worked, not to the employee"
    )

    _rows, meta = validate_paginated(api.list_shifts(PREPARER))
    assert meta["total_count"] == 1
