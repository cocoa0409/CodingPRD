"""Entity-level claims: absence creation defaults, long-term approval birth,
substitute system-managed status, per-resource 404 routing, school budget
initialization, and immediate read-after-write consistency."""
from test_helpers import (
    ApiErrorId,
    assert_absence,
    assert_school,
    assert_substitute,
    basic_world,
    create_absence_payload,
    create_school_payload,
    create_substitute_payload,
    make_district,
    make_teacher_headers,
    report_absence,
    validate_error,
    validate_success,
)


def test_absence_creation_defaults_and_required_fields(api):
    """PRD 3.3: "The system then computes `total_days` — the count of
    Monday-through-Friday dates inside the inclusive range, weekends never
    counting — and stamps `fill_status` `REPORTED`."
    PRD 3.3: "At creation it computes to `NOT_REQUIRED` when `total_days` is at
    most the district's `long_term_approval_days`, and to `PENDING` when
    strictly greater"
    PRD 3.3: "The absence's `school_id` is denormalized from the staff member's
    record at creation and never drifts."
    PRD 2.8: "Required fields present, types valid, enum values within their
    declared sets, `hours_worked` between 0.5 and 12.0 in half-hour steps, and
    `periods` at least 1; any violation yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/absence_creation_defaults_and_required_fields
    """
    ctx = basic_world()
    teacher = ctx["teacher"]

    payload = create_absence_payload(
        teacher["id"], start_date="2026-08-03", end_date="2026-08-05"
    )
    absence = validate_success(
        api.create_absence(payload, make_teacher_headers(teacher["id"])), 201
    )
    assert_absence(absence)
    assert absence["fill_status"] == "REPORTED"
    assert absence["approval_status"] == "NOT_REQUIRED", (
        "3 weekdays <= long_term_approval_days 5, so approval is NOT_REQUIRED"
    )
    assert absence["total_days"] == 3, "Mon 2026-08-03..Wed 2026-08-05 is 3 weekdays"
    assert absence["school_id"] == ctx["school"]["id"], (
        "school_id is denormalized from the staff member's record"
    )

    bad = create_absence_payload(teacher["id"], start_date="2026-08-10")
    del bad["end_date"]
    res = api.create_absence(bad, make_teacher_headers(teacher["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_absence_long_term_requires_approval_at_creation(api):
    """PRD 3.3: "Long absences need district blessing, tracked on a second,
    parallel state machine: `approval_status`. At creation it computes to
    `NOT_REQUIRED` when `total_days` is at most the district's
    `long_term_approval_days`, and to `PENDING` when strictly greater"

    Design: Corner/entities/absence_long_term_requires_approval_at_creation
    """
    ctx = basic_world()
    absence = report_absence(
        ctx["teacher"], start_date="2026-08-03", end_date="2026-08-10"
    )
    assert_absence(absence)
    assert absence["total_days"] == 6, (
        "2026-08-03..2026-08-10 spans Mon-Fri + Mon = 6 weekdays"
    )
    assert absence["approval_status"] == "PENDING", "6 > 5 requires district approval"
    assert absence["fill_status"] == "REPORTED", (
        "the two state dimensions are independent at birth"
    )


def test_substitute_system_status_input_ignored(api, district_admin_headers):
    """PRD 3.2: "A `DistrictAdmin` registers a substitute with a `full_name`
    and a `base_daily_rate_cents` — the daily pay before any premium. The new
    record starts in `PENDING_CLEARANCE` status with the pristine reliability
    profile of §2.10"
    PRD 2.10: "a newly registered substitute starts with both scores at 100,
    both counters at 0, and an empty event log."

    Design: Corner/entities/substitute_system_status_input_ignored
    """
    make_district()
    payload = create_substitute_payload(full_name="Sub A", base_daily_rate_cents=20000)
    payload["status"] = "ACTIVE"  # not a registration input; must not stick
    sub = validate_success(api.create_substitute(payload, district_admin_headers), 201)
    assert_substitute(sub)
    assert sub["status"] == "PENDING_CLEARANCE"
    assert sub["reliability_lifetime_score"] == 100
    assert sub["reliability_trailing_score"] == 100
    assert sub["completions_lifetime"] == 0
    assert sub["completions_trailing"] == 0
    assert sub["reliability_events"] == []


def test_not_found_for_every_path_resource(api, district_admin_headers):
    """PRD 2.8: "Each identifier in the URL is validated in order, and the
    request is rejected with the per-entity not-found error — one of
    `ERR_DISTRICT_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`,
    `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_SUBSTITUTE_NOT_FOUND`,
    `ERR_ABSENCE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_CLEARANCE_NOT_FOUND`, `ERR_MARK_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`,
    `ERR_TIMESHEET_NOT_FOUND`, `ERR_PAYROLL_PERIOD_NOT_FOUND`,
    `ERR_PERFORMANCE_FLAG_NOT_FOUND`, or `ERR_DISPATCH_BATCH_NOT_FOUND` — at
    the first identifier that does not exist (404)."

    Design: Corner/entities/not_found_for_every_path_resource
    """
    cases = [
        (api.get_absence("11111111-1111-4111-8111-111111111111", district_admin_headers),
         ApiErrorId.ERR_ABSENCE_NOT_FOUND),
        (api.get_substitute("22222222-2222-4222-8222-222222222222", district_admin_headers),
         ApiErrorId.ERR_SUBSTITUTE_NOT_FOUND),
        (api.get_dispatch_batch("33333333-3333-4333-8333-333333333333", district_admin_headers),
         ApiErrorId.ERR_DISPATCH_BATCH_NOT_FOUND),
        (api.get_payroll_period("44444444-4444-4444-8444-444444444444", district_admin_headers),
         ApiErrorId.ERR_PAYROLL_PERIOD_NOT_FOUND),
    ]
    for res, error_id in cases:
        validate_error(res, error_id, expected_status=404)


def test_school_budget_fields_initialized(api, district_admin_headers):
    """PRD 2.9: "`coverage_budget_committed_cents` is the provisional reserve:
    the sum of `provisional_pay_cents` over the school's assignments currently
    in `ACCEPTED`, `WORKED`, or `VERIFIED` status, initialized to zero."
    PRD 2.9: "`coverage_budget_spent_cents` accumulates real charges — payouts
    charged at payroll export and compensation for internal coverage that has
    reached `COMPENSATED` — likewise initialized to zero. The derived
    `coverage_budget_available_cents` is the total minus committed minus
    spent, and the system guarantees it never goes negative"

    Design: Corner/entities/school_budget_fields_initialized
    """
    district = make_district()
    school = validate_success(
        api.create_school(
            create_school_payload(district["id"], coverage_budget_total_cents=500000),
            district_admin_headers,
        ),
        201,
    )
    assert_school(school)
    assert school["coverage_budget_committed_cents"] == 0
    assert school["coverage_budget_spent_cents"] == 0
    assert school["coverage_budget_available_cents"] == 500000


def test_immediate_read_after_write_consistency(api, district_admin_headers):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD 3.6: "`days_covered_internal` counts the distinct coverage dates whose
    coverage stands in `APPROVED`, `WORKED`, or `COMPENSATED`;
    `days_covered_sub` is the verified assignment's `worked_days_count`, or
    zero while no assignment has reached `VERIFIED`; and `days_uncovered` is
    whatever remains."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    ctx = basic_world()
    absence = report_absence(
        ctx["teacher"],
        start_date="2026-08-03",
        end_date="2026-08-07",
        absence_type="JURY_DUTY",
    )
    fetched = validate_success(api.get_absence(absence["id"], district_admin_headers), 200)
    assert_absence(fetched)
    assert fetched["fill_status"] == "REPORTED"
    assert fetched["total_days"] == 5
    assert fetched["approval_status"] == "NOT_REQUIRED"
    assert fetched["days_covered_internal"] == 0
    assert fetched["days_covered_sub"] == 0
    assert fetched["days_uncovered"] == 5
    assert fetched["school_id"] == ctx["school"]["id"]
