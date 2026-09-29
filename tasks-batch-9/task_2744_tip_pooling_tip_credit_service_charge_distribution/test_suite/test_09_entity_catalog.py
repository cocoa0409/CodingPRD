"""Queue B — §1.1 entities: creation, computed fields, declared defaults,
system-field rejection, retrieval, listing, typed 404s and the immutable ledger row."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    NON_EXISTENT_UUID,
    PREPARER,
    ApiErrorId,
    assert_common_fields,
    assert_instant_equals,
    assert_pay_period_rollups_zero,
    close_shift,
    create_employee_payload,
    create_location_payload,
    create_shift_payload,
    declare_shift_tips,
    is_valid_uuid,
    list_allocations_of,
    new_active_policy,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_pool,
    new_role_assignment,
    new_shift,
    set_logical_clock,
    setup_texas_wage_world,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"


# ---------------------------------------------------------------------------
# creation
# ---------------------------------------------------------------------------
def test_registering_a_unit_derives_both_wage_ceilings_and_seeds_the_rollup(api):
    """One POST returns 725, 512, 0 and version 1, none of them supplied.

    PRD §3.1: "Registration derives three further figures on the unit and nothing
    else: `applicable_min_wage_cents` and `max_tip_credit_per_hour_cents` per §2.4,
    and `pending_pool_cents`, which is set to 0 and whose `version` therefore begins
    at 1."
    PRD §2.6: "Every resource the API stores carries an `id`: a server-minted UUID
    string with no type prefix of any kind. Clients never supply an `id`."
    PRD §3.1: "Supplying `cc_fee_cap_bps` under either of the other two policies is
    just as wrong as omitting it under `CAPPED_BPS`, and both mistakes surface as
    `ERR_CC_FEE_CAP_REQUIRED`."

    Design: Corner/entities/create_location_derives_wage_ceilings_and_starts_at_version_one
    """
    set_logical_clock()

    created = validate_success(
        api.create_location(create_location_payload(), ADMIN), 201
    )

    assert created["name"] == "Dallas Unit"
    assert created["state_code"] == "TX"
    assert created["state_min_wage_cents"] == 725
    assert created["cash_wage_cents"] == 213
    assert created["tip_credit_enabled"] is True
    assert created["cc_fee_policy"] == "ACTUAL_ONLY"
    assert created["service_charge_treatment"] == "WAGES"

    assert created["applicable_min_wage_cents"] == 725
    assert created["max_tip_credit_per_hour_cents"] == 512
    assert created["pending_pool_cents"] == 0
    assert created["cc_fee_cap_bps"] is None, (
        "the cap is omitted under ACTUAL_ONLY, so it must not be invented"
    )

    assert_common_fields(created, expected_version=1)
    assert is_valid_uuid(created["id"]), "a bare UUID with no type prefix"
    assert_instant_equals(created["created_at"], CLOCK, "created_at")
    assert_instant_equals(created["updated_at"], CLOCK, "updated_at")


# ---------------------------------------------------------------------------
# computed_fields
# ---------------------------------------------------------------------------
def test_three_units_separate_the_two_wage_ceilings_from_their_inputs(api):
    """A 700 state wage loses to the federal floor and a no-credit unit gets a 0 ceiling.

    PRD §2.4: "From those two inputs the server derives `applicable_min_wage_cents`
    as the greater of the federal minimum wage of 725 cents and the unit's
    `state_min_wage_cents`."
    PRD §2.4: "Where the unit claims a tip credit, that claim is capped per hour:
    the server derives `max_tip_credit_per_hour_cents` as
    `applicable_min_wage_cents` minus `cash_wage_cents`."
    PRD §2.4: "Where `tip_credit_enabled` is false,
    `max_tip_credit_per_hour_cents` is 0 and no tip credit is ever available at that
    unit, whatever its cash wage happens to be."

    Design: Corner/entities/location_applicable_min_wage_takes_the_federal_floor
    """
    set_logical_clock()

    below_floor = validate_success(
        api.create_location(
            create_location_payload(name="Below Floor Unit", state_min_wage_cents=725),
            ADMIN,
        ),
        201,
    )
    manhattan = validate_success(
        api.create_location(
            create_location_payload(
                name="Manhattan Unit",
                state_code="NY",
                state_min_wage_cents=1500,
                cash_wage_cents=1000,
            ),
            ADMIN,
        ),
        201,
    )
    oakland = validate_success(
        api.create_location(
            create_location_payload(
                name="Oakland Unit",
                state_code="CA",
                state_min_wage_cents=1650,
                cash_wage_cents=1650,
                tip_credit_enabled=False,
                cc_fee_policy="PROHIBITED",
                service_charge_treatment="TIPS",
            ),
            ADMIN,
        ),
        201,
    )

    assert below_floor["applicable_min_wage_cents"] == 725, (
        "a state wage at the federal floor ties, so the derived ceiling is 725"
    )
    assert below_floor["max_tip_credit_per_hour_cents"] == 512
    assert manhattan["applicable_min_wage_cents"] == 1500
    assert manhattan["max_tip_credit_per_hour_cents"] == 500
    assert oakland["applicable_min_wage_cents"] == 1650
    assert oakland["max_tip_credit_per_hour_cents"] == 0, (
        "the flag, not the arithmetic, is what zeroes the ceiling"
    )

    for unit in (below_floor, manhattan, oakland):
        assert unit["pending_pool_cents"] == 0
        assert unit["version"] == 1


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------
def test_omitting_every_optional_flag_takes_the_declared_defaults(api):
    """A role created bare is non-management, non-contributing, non-sharing and side-work-ineligible.

    PRD §3.1: "The `is_management` flag, false unless supplied, marks managers and
    supervisors, who are excluded from every mandatory tip pool in both directions —
    they may neither contribute to one nor receive from one."
    PRD §3.1: "`pool_contribution_pct_bps` is the mandatory contribution rate in
    basis points, defaulting to 0 and constrained to the inclusive range 0 through
    5000; `pool_share_points` is the relative weight the role carries when the net
    pool is split, defaulting to 0 and constrained to the inclusive range 0 through
    100."
    PRD §3.2: "Hiring also sets `trailing_pool_receipts_cents` to 0; thereafter it
    is the running sum of `allocated_cents` over every pool-allocation ledger row
    naming this employee, counting both `DISTRIBUTION` rows and `REVERSAL` rows, so
    that a reversed pool leaves it back where it started."

    Design: Corner/entities/create_job_role_and_employee_omitted_flags_take_declared_defaults
    """
    set_logical_clock()
    location = new_location()

    role = validate_success(
        api.create_job_role(
            {"code": "DISHWASHER", "title": "Dishwasher", "tip_status": "NON_TIPPED"},
            ADMIN,
        ),
        201,
    )
    employee = validate_success(
        api.create_employee(
            {
                "location_id": location["id"],
                "full_name": "Sam Ortiz",
                "external_payroll_ref": "E-DISH-1",
            },
            ADMIN,
        ),
        201,
    )

    assert role["is_management"] is False
    assert role["pool_contribution_pct_bps"] == 0
    assert role["pool_share_points"] == 0
    assert role["side_work_eligible"] is False
    assert role["version"] == 1

    assert employee["monthly_tip_baseline_cents"] == 0
    assert employee["separation_date"] is None
    assert employee["trailing_pool_receipts_cents"] == 0
    assert employee["version"] == 1


# ---------------------------------------------------------------------------
# system_fields
# ---------------------------------------------------------------------------
def test_injecting_system_fields_into_a_hire_is_rejected_not_silently_dropped(api):
    """id, created_at, version and a computed rollup are unknown keys, so the body is a 400.

    PRD §2.10 rung 3: "The request body and query string are structurally valid:
    every required input present, no unknown key, every enum value inside its
    declared domain, every field whose name ends in `_cents`, `_minutes` or `_bps` a
    non-negative integer, every field whose name ends in `_at` an ISO 8601 UTC
    instant, `end_at` strictly after `start_at`, `end_date` not before `start_date`,
    `limit` within the inclusive range 1 to 100 and `offset` not negative —
    `ERR_INVALID_REQUEST`, 400, on every endpoint."
    PRD §2.6: "**`version`** (integer): a monotonically increasing counter that
    starts at 1 when the row is created and increases by exactly 1 on each
    subsequent mutation of the row."

    Design: Corner/entities/create_employee_with_injected_system_fields_returns_invalid_request
    """
    set_logical_clock()
    location = new_location()
    injected_id = "11111111-2222-3333-4444-555555555555"

    validate_error(
        api.create_employee(
            create_employee_payload(
                location["id"],
                id=injected_id,
                created_at="2020-01-01T00:00:00Z",
                version=9,
                trailing_pool_receipts_cents=5000,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    accepted = validate_success(
        api.create_employee(create_employee_payload(location["id"]), ADMIN), 201
    )
    assert accepted["id"] != injected_id
    assert accepted["version"] == 1
    assert accepted["trailing_pool_receipts_cents"] == 0
    assert_instant_equals(accepted["created_at"], CLOCK, "created_at")

    rows, meta = validate_paginated(
        api.list_employees(ADMIN, params={"location_id": location["id"]})
    )
    assert meta["total_count"] == 1, "the rejected body created nothing"
    assert [row["id"] for row in rows] == [accepted["id"]]


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------
def test_reading_back_a_fresh_period_shows_every_rollup_still_at_zero(api):
    """Nothing is populated speculatively before a compute.

    PRD §3.4: "A newly opened period has `status` `OPEN`, `compute_variant` null,
    `computed_by_user_id` null, `approved_by_user_id` null, and every rollup at 0."
    PRD §2.6: "Date-valued fields that identify a calendar day rather than an
    instant — `business_date`, `start_date`, `end_date`, `effective_from`,
    `effective_to` and `separation_date` — are supplied and returned as ISO 8601 UTC
    instants at midnight, that is with a time component of `00:00:00.000`."

    Design: Corner/entities/get_pay_period_returns_stored_rollups_unchanged
    """
    set_logical_clock()
    location = new_location()
    created = new_pay_period(location["id"])

    period = validate_success(api.get_pay_period(created["id"], COMPLIANCE))

    assert period["id"] == created["id"]
    assert period["status"] == "OPEN"
    assert period["compute_variant"] is None
    assert period["computed_by_user_id"] is None
    assert period["approved_by_user_id"] is None
    assert_instant_equals(period["start_date"], "2026-08-03T00:00:00Z", "start_date")
    assert_instant_equals(period["end_date"], "2026-08-09T00:00:00Z", "end_date")
    assert_pay_period_rollups_zero(period)
    assert period["version"] == 1


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------
def test_shift_listing_pages_with_total_count_and_rejects_a_zero_limit(api):
    """Three shifts over two pages, then limit 0 as a 400 rather than a clamp.

    PRD §2.3: "`total_count` counts every row matching the request's filters, not
    merely the rows on the current page, and `has_more` is true exactly when rows
    matching the filters remain beyond the current page."
    PRD §2.3: "A `limit` outside the inclusive range from 1 to 100, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/list_shifts_paginates_with_total_count_and_has_more
    """
    world = setup_texas_wage_world()
    made = []
    for business_date, start_at, end_at in (
        ("2026-08-04T00:00:00Z", "2026-08-04T16:00:00Z", "2026-08-05T00:00:00Z"),
        ("2026-08-05T00:00:00Z", "2026-08-05T16:00:00Z", "2026-08-06T00:00:00Z"),
        ("2026-08-06T00:00:00Z", "2026-08-06T16:00:00Z", "2026-08-07T00:00:00Z"),
    ):
        made.append(
            new_shift(
                world["employee"]["id"],
                world["location"]["id"],
                world["role_server"]["id"],
                world["pay_period"]["id"],
                business_date=business_date,
                start_at=start_at,
                end_at=end_at,
            )["id"]
        )

    params = {"pay_period_id": world["pay_period"]["id"], "limit": 2, "offset": 0}
    first_rows, first_meta = validate_paginated(api.list_shifts(ADMIN, params=params))
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    params = {"pay_period_id": world["pay_period"]["id"], "limit": 2, "offset": 2}
    second_rows, second_meta = validate_paginated(api.list_shifts(ADMIN, params=params))
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    seen = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(set(seen)) == 3, "no row appears on both pages"
    assert set(seen) == set(made)

    validate_error(
        api.list_shifts(
            ADMIN, params={"pay_period_id": world["pay_period"]["id"], "limit": 0}
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# ---------------------------------------------------------------------------
# not_found
# ---------------------------------------------------------------------------
def test_unknown_shift_id_in_the_path_is_a_typed_404(api):
    """A well-formed UUID naming no Shift gets the shift-specific code.

    PRD §2.10 rung 4: "a `shift_id` that names no stored Shift raises
    `ERR_SHIFT_NOT_FOUND`"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/get_shift_with_unknown_id_returns_shift_not_found
    """
    set_logical_clock()

    response = api.get_shift(NON_EXISTENT_UUID, PREPARER)
    validate_error(response, ApiErrorId.ERR_SHIFT_NOT_FOUND.value)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


# ---------------------------------------------------------------------------
# required_fields
# ---------------------------------------------------------------------------
def test_shift_creation_without_a_pay_period_id_is_a_structural_400(api):
    """A required input with no default is a priority-3 rejection, not a business error.

    PRD §2.10 rung 3: "The request body and query string are structurally valid:
    every required input present, no unknown key, every enum value inside its
    declared domain, every field whose name ends in `_cents`, `_minutes` or `_bps` a
    non-negative integer, every field whose name ends in `_at` an ISO 8601 UTC
    instant, `end_at` strictly after `start_at`, `end_date` not before `start_date`,
    `limit` within the inclusive range 1 to 100 and `offset` not negative —
    `ERR_INVALID_REQUEST`, 400, on every endpoint."
    PRD §3.4: "The shift is bound to four records at once — `employee_id`,
    `location_id`, `job_role_id` and `pay_period_id` — and the role named by
    `job_role_id` is what decides the shift's tipped classification, its
    contribution rate and its share points."

    Design: Corner/entities/create_shift_missing_required_pay_period_id_returns_invalid_request
    """
    world = setup_texas_wage_world()

    payload = create_shift_payload(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
    )
    del payload["pay_period_id"]

    validate_error(
        api.create_shift(payload, PREPARER), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    _rows, meta = validate_paginated(
        api.list_shifts(PREPARER, params={"pay_period_id": world["pay_period"]["id"]})
    )
    assert meta["total_count"] == 0
    period = validate_success(api.get_pay_period(world["pay_period"]["id"], PREPARER))
    assert period["total_credited_minutes"] == 0
    assert period["version"] == 1


# ---------------------------------------------------------------------------
# type_constraints
# ---------------------------------------------------------------------------
def test_out_of_domain_enum_and_negative_money_both_fail_before_the_wage_rule(api):
    """Priority 3 pre-empts the priority-28 cash-wage rule on the very same body.

    PRD §2.10 rung 3: "every enum value inside its declared domain, every field
    whose name ends in `_cents`, `_minutes` or `_bps` a non-negative integer"
    PRD §2.4: "Each restaurant unit declares the state whose wage and card-fee rules
    govern it through `state_code`, which must be one of `CA`, `NY`, `TX` or `MA`"
    PRD §2.10 rung 28: "A unit whose `tip_credit_enabled` is true must set
    `cash_wage_cents` to at least 213 and strictly below
    `applicable_min_wage_cents` — `ERR_CASH_WAGE_BELOW_FLOOR`, 422, on
    `POST /locations`."

    Design: Corner/entities/create_location_with_out_of_domain_state_code_returns_invalid_request
    """
    set_logical_clock()

    validate_error(
        api.create_location(
            create_location_payload(name="Nowhere Unit", state_code="ZZ"), ADMIN
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.create_location(
            create_location_payload(name="Negative Unit", cash_wage_cents=-50), ADMIN
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _rows, meta = validate_paginated(api.list_locations(ADMIN))
    assert meta["total_count"] == 0, "neither malformed registration was stored"


# ---------------------------------------------------------------------------
# parent_relationships
# ---------------------------------------------------------------------------
def test_hiring_into_an_unknown_unit_is_a_typed_body_level_404(api):
    """The body foreign key is checked at priority 5, ahead of every business rule.

    PRD §2.10 rung 5: "Every foreign key supplied in the request body resolves to a
    stored row, checked in the order in which those fields are declared on the
    entity being created — the same 404 family (`ERR_LOCATION_NOT_FOUND`,
    `ERR_EMPLOYEE_NOT_FOUND`, `ERR_PAY_PERIOD_NOT_FOUND`, `ERR_PAY_LINE_NOT_FOUND`,
    `ERR_DISPUTE_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`) —
    on `POST /employees`, `POST /role-assignments`, `POST /tip-pool-policies`,
    `POST /pay-periods`, `POST /shifts`, `POST /service-charges`,
    `POST /shift-tip-pools`, `POST /disputes` and `POST /back-wage-corrections`."
    PRD §3.2: "A `PayrollAdmin` hires an employee into a unit by supplying that
    unit's `location_id` together with the employee's `full_name` and
    `external_payroll_ref`, the identifier by which the upstream payroll system
    knows this person."

    Design: Corner/entities/create_employee_under_unknown_location_returns_location_not_found
    """
    set_logical_clock()

    validate_error(
        api.create_employee(
            create_employee_payload(
                NON_EXISTENT_UUID,
                full_name="Ghost Worker",
                external_payroll_ref="E-GHOST",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_LOCATION_NOT_FOUND.value,
    )

    _rows, meta = validate_paginated(api.list_employees(ADMIN))
    assert meta["total_count"] == 0


def test_shift_whose_three_parents_disagree_on_a_unit_is_refused(api):
    """Every foreign key resolves and the assignment exists, yet the units disagree.

    PRD §2.10 rung 32: "The shift's `location_id` equals both the employee's
    `location_id` and the pay period's `location_id`; and a dispute's
    `raised_by_employee_id` matches the disputed pay line's `employee_id` —
    `ERR_EMPLOYEE_LOCATION_MISMATCH`, 422, on `POST /shifts` and `POST /disputes`."
    PRD §3.4: "Then the shift's `location_id` must equal both the employee's own
    `location_id` and the period's `location_id`, failing which
    `ERR_EMPLOYEE_LOCATION_MISMATCH`."

    Design: Corner/entities/create_shift_for_an_employee_of_another_unit_returns_location_mismatch
    """
    set_logical_clock()
    unit_a = new_location(name="Unit A")
    unit_b = new_location(name="Unit B")
    role_server = new_job_role()
    employee_b = new_employee(
        unit_b["id"], full_name="Beto Nunez", external_payroll_ref="E-B1"
    )
    new_role_assignment(employee_b["id"], role_server["id"])
    period_a = new_pay_period(unit_a["id"])

    validate_error(
        api.create_shift(
            create_shift_payload(
                employee_b["id"], unit_a["id"], role_server["id"], period_a["id"]
            ),
            PREPARER,
        ),
        ApiErrorId.ERR_EMPLOYEE_LOCATION_MISMATCH.value,
    )

    _rows, meta = validate_paginated(
        api.list_shifts(PREPARER, params={"pay_period_id": period_a["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# immutability
# ---------------------------------------------------------------------------
def test_pool_allocation_row_carries_only_id_and_created_at(api):
    """The ledger row exposes no version and no updated_at at all.

    PRD §2.6: "One resource is deliberately different. A pool-allocation ledger row
    is immutable once written: it carries only `id` and `created_at`."
    PRD §2.6: "It has no `updated_at` field and no `version` field at all, and
    neither field appears in its response payload."
    PRD §3.7: "Under `POINTS_ONLY` a participant's `share_weight` is simply its
    role's `pool_share_points`."

    Design: Corner/entities/pool_allocation_rows_carry_no_version_and_no_write_endpoint
    """
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    employee = new_employee(location["id"])
    new_role_assignment(employee["id"], role_server["id"])
    new_active_policy(
        location["id"],
        location["version"],
        share_basis="POINTS_ONLY",
        cc_fee_pass_through=False,
    )
    pay_period = new_pay_period(location["id"])
    shift = new_shift(
        employee["id"],
        location["id"],
        role_server["id"],
        pay_period["id"],
        gross_sales_cents=0,
        charged_sales_cents=0,
        cc_processing_fee_bps=0,
    )
    close_shift(shift["id"])
    declare_shift_tips(shift["id"], employee["id"], 4000, 0)
    pool = new_pool(location["id"])
    validate_success(api.distribute_shift_tip_pool(pool["id"], PREPARER))

    rows = list_allocations_of(pool["id"])
    assert len(rows) == 1
    row = validate_success(api.get_pool_allocation(rows[0]["id"], ADMIN))

    assert row["shift_tip_pool_id"] == pool["id"]
    assert row["employee_id"] == employee["id"]
    assert row["shift_id"] == shift["id"]
    assert row["entry_type"] == "DISTRIBUTION"
    assert row["share_weight"] == 10, "POINTS_ONLY weights by pool_share_points alone"
    assert row["allocated_cents"] == 600, "1500 bps of the 4000 cash tips declared"
    assert row["remainder_cent_awarded"] is False
    assert_instant_equals(row["business_date"], "2026-08-04T00:00:00Z", "business_date")

    assert "version" not in row
    assert "updated_at" not in row
    assert is_valid_uuid(row["id"])
    assert_instant_equals(row["created_at"], CLOCK, "created_at")
