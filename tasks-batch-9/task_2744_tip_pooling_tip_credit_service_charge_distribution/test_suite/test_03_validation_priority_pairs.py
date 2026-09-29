"""Queue A — single requests that break two rungs of the §2.10 ladder at once."""
from test_helpers import (
    ApiErrorId,
    PREPARER,
    create_shift_payload,
    declare_tips_payload,
    make_employee_headers,
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
    void_shift,
)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict /
# declare_tips_on_voided_shift_with_excess_charged_tips_returns_state_error
# ---------------------------------------------------------------------------
def _setup_voided_shift_with_card_sales() -> dict:
    """One Texas unit, one assigned SERVER, and one shift carrying 5000 cents of
    card sales that has been VOIDED straight from OPEN."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    employee = new_employee(location["id"])
    new_role_assignment(employee["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])
    shift = new_shift(
        employee["id"],
        location["id"],
        role_server["id"],
        pay_period["id"],
        gross_sales_cents=8000,
        charged_sales_cents=5000,
    )
    void_shift(shift["id"], reason="clocked in on the wrong terminal")
    return {
        "location": location,
        "employee": employee,
        "pay_period": pay_period,
        "shift": shift,
    }


def test_declaring_on_a_voided_shift_raises_the_lifecycle_error_not_the_fiscal_one(api):
    """The 409 at rung 9 is reached before the 422 at rung 50.

    PRD §2.10 rung 9: "The target shift's `time_status` is `CLOSED` —
    `ERR_SHIFT_NOT_CLOSED`, 409, on `POST /shifts/{shift_id}/declare-tips`."
    PRD §2.10 rung 50: "`declared_charged_tips_cents` does not exceed the shift's
    `charged_sales_cents` — `ERR_DECLARED_CHARGED_TIPS_EXCEED_CHARGED_SALES`, 422,
    on `POST /shifts/{shift_id}/declare-tips`."
    PRD §2.10: "Every rule in the system occupies a fixed rung on a single
    precedence ladder, and the rule on the lowest-numbered rung that the request
    violates is the rule that produces the response; every rule below it on the
    ladder is never reached."

    Design: Difficulty/priority_pair_validation_conflict/declare_tips_on_voided_shift_with_excess_charged_tips_returns_state_error
    """
    world = _setup_voided_shift_with_card_sales()

    response = api.declare_tips(
        world["shift"]["id"],
        declare_tips_payload(0, 9000),
        make_employee_headers(world["employee"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SHIFT_NOT_CLOSED.value)


def test_rejected_declaration_on_a_voided_shift_leaves_the_shift_untouched(api):
    """Nothing is written: the shift stays VOIDED and UNDECLARED with a zero count.

    PRD §3.5: "Each of the three transitions writes the two declared amounts,
    overwriting whatever was there before, increments `declaration_count` by 1 — so
    a `declaration_count` of 1 marks an original declaration and 2 or more marks
    amendments — and recomputes `retained_tips_cents`."
    PRD §3.4: "A newly recorded shift starts with `time_status` `OPEN` and
    `declaration_status` `UNDECLARED`, with `shift_tip_pool_id` null and with
    `declared_cash_tips_cents`, `declared_charged_tips_cents`, `declaration_count`,
    `non_tip_credit_minutes`, `tip_credit_eligible_minutes`,
    `pool_contribution_cents`, `retained_tips_cents` and `shift_tip_credit_cents`
    all at 0."

    Design: Difficulty/priority_pair_validation_conflict/declare_tips_on_voided_shift_with_excess_charged_tips_returns_state_error
    """
    world = _setup_voided_shift_with_card_sales()

    validate_error(
        api.declare_tips(
            world["shift"]["id"],
            declare_tips_payload(0, 9000),
            make_employee_headers(world["employee"]["id"]),
        ),
        ApiErrorId.ERR_SHIFT_NOT_CLOSED.value,
    )

    shift = read_shift(world["shift"]["id"])
    assert shift["time_status"] == "VOIDED"
    assert shift["declaration_status"] == "UNDECLARED"
    assert shift["declared_cash_tips_cents"] == 0
    assert shift["declared_charged_tips_cents"] == 0
    assert shift["declaration_count"] == 0


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict /
# create_shift_without_assignment_and_overlapping_interval_returns_referential_error
# ---------------------------------------------------------------------------
def _setup_server_only_employee_with_one_shift() -> dict:
    """Two real job roles, an employee assigned only to SERVER, and one existing
    16:00-to-midnight shift on 2026-08-04."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    role_bartender = new_job_role(
        code="BARTENDER",
        title="Bartender",
        pool_contribution_pct_bps=1000,
        pool_share_points=8,
    )
    employee = new_employee(location["id"])
    new_role_assignment(employee["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])
    first_shift = new_shift(
        employee["id"], location["id"], role_server["id"], pay_period["id"]
    )
    return {
        "location": location,
        "role_server": role_server,
        "role_bartender": role_bartender,
        "employee": employee,
        "pay_period": pay_period,
        "first_shift": first_shift,
    }


def _unassigned_overlapping_payload(world: dict) -> dict:
    return create_shift_payload(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_bartender"]["id"],
        world["pay_period"]["id"],
        business_date="2026-08-04T00:00:00Z",
        start_at="2026-08-04T20:00:00Z",
        end_at="2026-08-04T23:00:00Z",
    )


def test_missing_role_assignment_beats_the_interval_overlap_on_shift_creation(api):
    """The 422 at rung 31 wins over the 409 at rung 38, so status alone cannot order them.

    PRD §2.10 rung 31: "The shift's employee holds a role assignment for the
    requested `job_role_id` whose date interval contains `business_date` —
    `ERR_NO_ACTIVE_ROLE_ASSIGNMENT`, 422, on `POST /shifts`."
    PRD §3.4: "Then the employee must hold a role assignment for the requested
    `job_role_id` whose date interval contains `business_date`, failing which
    `ERR_NO_ACTIVE_ROLE_ASSIGNMENT`."
    PRD §3.2: "An employee cannot work a shift in a role they do not hold."

    Design: Difficulty/priority_pair_validation_conflict/create_shift_without_assignment_and_overlapping_interval_returns_referential_error
    """
    world = _setup_server_only_employee_with_one_shift()

    response = api.create_shift(_unassigned_overlapping_payload(world), PREPARER)
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_ROLE_ASSIGNMENT.value)


def test_rejected_bartender_shift_persists_nothing_although_the_role_exists(api):
    """The BARTENDER role is real, so no 404 is in play and no second shift is stored.

    PRD §2.10 rung 4: "a `job_role_id`, `role_assignment_id`, `service_charge_id`
    or `allocation_id` that names no stored JobRole, EmployeeRoleAssignment,
    ServiceChargeEvent or PoolAllocation respectively raises
    `ERR_RECORD_NOT_FOUND`."
    PRD §2.11: "shifts by `employee_id`, `location_id`, `job_role_id`,
    `pay_period_id`, `shift_tip_pool_id`, `business_date`, `time_status` and
    `declaration_status`"

    Design: Difficulty/priority_pair_validation_conflict/create_shift_without_assignment_and_overlapping_interval_returns_referential_error
    """
    world = _setup_server_only_employee_with_one_shift()

    # The role really exists and is readable, which rules out the 404 family.
    role = validate_success(api.get_job_role(world["role_bartender"]["id"], PREPARER))
    assert role["code"] == "BARTENDER"

    validate_error(
        api.create_shift(_unassigned_overlapping_payload(world), PREPARER),
        ApiErrorId.ERR_NO_ACTIVE_ROLE_ASSIGNMENT.value,
    )

    rows, _meta = validate_paginated(
        api.list_shifts(PREPARER, params={"employee_id": world["employee"]["id"]})
    )
    assert [row["id"] for row in rows] == [world["first_shift"]["id"]]
