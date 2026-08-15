"""Exception requests: finance branch fork, salary cap evaluation order,
rolling capacity cap, segregation of duties, rescind conservation (PRD §2.6,
§2.8, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_approved_profile,
    create_department_payload,
    create_employee,
    create_employee_payload,
    create_exception,
    create_mapping_decision_payload,
    get_success_data,
    make_department_manager_headers,
    set_clock,
    setup_framework,
    setup_published_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]
HRBP = TEST_USERS["hrbp_headers"]
FINANCE = TEST_USERS["finance_partner_headers"]


def _program_with_employee(salary=14_000_000, ref="E1"):
    """PUBLISHED program, P1/P2 bands (mid 10m/13m, spread 0.30), dept DA
    pool 5m, one employee on the P2 profile."""
    ctx = setup_published_program()
    emp = create_employee(ctx, profile_rank=2, base_salary_cents=salary,
                          hire_date="2019-05-01", employee_ref=ref)
    return ctx, emp


def test_above_max_hire_routes_through_finance(api):
    """PRD §3.8: "For an `ABOVE_MAX_HIRE` request the gate passes the request
    into `FINANCE_REVIEW`, records the gatekeeper in `comp_gate_by_user_id`,
    and applies no salary yet."

    Design: Difficulty/non_linear_state_machine/exception_request_finance_branch_divergence
    """
    ctx, emp = _program_with_employee(salary=14_000_000)
    xr = create_exception(ctx, emp, ctx["band2"], 15_500_000,
                          ex_type="ABOVE_MAX_HIRE", justification="hire above max")
    assert xr["finance_required"] is True
    get_success_data(api_client.hrbp_pass_exception_request(xr["id"], HRBP))
    mid = validate_success(api_client.comp_pass_exception_request(xr["id"], MANAGER), 200)
    assert mid["status"] == "FINANCE_REVIEW"
    assert mid["comp_gate_by_user_id"] == MANAGER["X-User-ID"]
    # Salary NOT yet applied.
    emp_mid = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_mid["base_salary_cents"] == 14_000_000
    final = validate_success(
        api_client.finance_pass_exception_request(xr["id"], FINANCE), 200)
    assert final["status"] == "APPROVED"
    emp_after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_after["base_salary_cents"] == 15_500_000


def test_below_min_retention_skips_finance_branch(api):
    """PRD §3.8: "For every other type the gate decides final approval
    directly: the salary cap is re-evaluated, the fiscal check requires the
    positive part of the delta — the `requested_salary_cents` minus the
    employee's current `base_salary_cents`, or zero when that difference is
    negative — to fit within the department's pool headroom
    (`ERR_DEPARTMENT_POOL_EXHAUSTED`), and passage moves the request to
    `APPROVED` and applies the salary."
    PRD §3.8: "The request opens in `SUBMITTED` status with `finance_required`
    computed at creation — true exactly when the `type` is `ABOVE_MAX_HIRE`,
    which is what routes the request through the finance branch — and the
    creator's header recorded in `created_by_user_id`, a field that carries
    the literal value `system` for the refresh-auto-created requests of §3.9."

    Design: Difficulty/non_linear_state_machine/exception_request_finance_branch_divergence
    """
    ctx = setup_published_program()
    dept = ctx["department"]
    emp1 = create_employee(ctx, profile_rank=2, base_salary_cents=14_000_000,
                           hire_date="2019-05-01", employee_ref="E1")
    emp2 = create_employee(ctx, profile_rank=2, base_salary_cents=11_200_000,
                           hire_date="2021-02-01", employee_ref="E2")
    # Fork 1: ABOVE_MAX_HIRE (finance branch).
    xr1 = create_exception(ctx, emp1, ctx["band2"], 15_500_000,
                           ex_type="ABOVE_MAX_HIRE", justification="hire above max")
    get_success_data(api_client.hrbp_pass_exception_request(xr1["id"], HRBP))
    mid1 = validate_success(api_client.comp_pass_exception_request(xr1["id"], MANAGER), 200)
    assert mid1["status"] == "FINANCE_REVIEW"
    # Fork 2: BELOW_MIN_RETENTION (direct approval). Pre-ratio 0.8615 -> tier
    # LOW -> cap 16445000; delta +800000.
    xr2 = create_exception(ctx, emp2, ctx["band2"], 12_000_000,
                           ex_type="BELOW_MIN_RETENTION", justification="retention")
    assert xr2["finance_required"] is False
    get_success_data(api_client.hrbp_pass_exception_request(xr2["id"], HRBP))
    mid2 = validate_success(api_client.comp_pass_exception_request(xr2["id"], MANAGER), 200)
    assert mid2["status"] == "APPROVED"
    emp2_after = validate_success(api.get_employee(emp2["id"], HRBP), 200)
    assert emp2_after["base_salary_cents"] == 12_000_000
    # Complete fork 1 through finance.
    final1 = validate_success(
        api_client.finance_pass_exception_request(xr1["id"], FINANCE), 200)
    assert final1["status"] == "APPROVED"
    emp1_after = validate_success(api.get_employee(emp1["id"], HRBP), 200)
    assert emp1_after["base_salary_cents"] == 15_500_000
    dept_after = validate_success(api.get_department(dept["id"], ADMIN), 200)
    assert dept_after["committed_pool_cents"] == 2_300_000  # 1500000 + 800000


def test_exception_cap_boundary_exact_passes(api):
    """PRD §3.8: "The salary cap pins its evaluation order because the request
    would change its own ratio: first, the pre-exception ratio is computed
    from the employee's current `base_salary_cents` divided by the referenced
    band's `midpoint_cents`, rounded half-up to four decimal places; second, a
    tier multiplier is chosen — one hundred ten percent when that ratio is
    below 1.0000, one hundred five percent when it is at least 1.0000 and
    below 1.2000, and one hundred percent when it is at least 1.2000; third,
    the cap is the band's `max_cents` multiplied by the tier multiplier,
    rounded half-up to whole cents; fourth, the request is rejected with
    `ERR_EXCEPTION_CAP_EXCEEDED` (HTTP 422) exactly when the
    `requested_salary_cents` exceeds the cap — a request equal to the cap
    passes."

    Design: Difficulty/combinatorial_formula/exception_cap_uses_pre_exception_ratio
    """
    ctx, emp = _program_with_employee(salary=14_000_000)
    # Pre-exception ratio 1.0769 -> MID tier -> cap round(14950000 * 1.05).
    res = api_client.create_exception_request(
        {
            "employee_id": emp["id"], "pay_band_id": ctx["band2"]["id"],
            "type": "OFF_CYCLE_INCREASE", "requested_salary_cents": 15_697_500,
            "justification": "retention",
        },
        make_department_manager_headers(ctx["department"]["id"]))
    xr = validate_success(res, 201)
    assert xr["finance_required"] is False
    assert xr["status"] == "SUBMITTED"


def test_exception_cap_one_cent_over_rejected(api):
    """PRD §3.8: "The salary cap pins its evaluation order because the request
    would change its own ratio: first, the pre-exception ratio is computed
    from the employee's current `base_salary_cents` divided by the referenced
    band's `midpoint_cents`, rounded half-up to four decimal places; second, a
    tier multiplier is chosen — one hundred ten percent when that ratio is
    below 1.0000, one hundred five percent when it is at least 1.0000 and
    below 1.2000, and one hundred percent when it is at least 1.2000; third,
    the cap is the band's `max_cents` multiplied by the tier multiplier,
    rounded half-up to whole cents; fourth, the request is rejected with
    `ERR_EXCEPTION_CAP_EXCEEDED` (HTTP 422) exactly when the
    `requested_salary_cents` exceeds the cap — a request equal to the cap
    passes."

    Design: Difficulty/combinatorial_formula/exception_cap_uses_pre_exception_ratio
    """
    ctx, emp = _program_with_employee(salary=14_000_000)
    res = api_client.create_exception_request(
        {
            "employee_id": emp["id"], "pay_band_id": ctx["band2"]["id"],
            "type": "OFF_CYCLE_INCREASE", "requested_salary_cents": 15_697_501,
            "justification": "over cap",
        },
        make_department_manager_headers(ctx["department"]["id"]))
    validate_error(res, ApiErrorId.ERR_EXCEPTION_CAP_EXCEEDED, expected_status=422)


def test_sod_blocks_self_gate(api):
    """PRD §3.8: "A `CompManager` then staffs the compensation gate, where
    segregation of duties forbids the caller's `X-User-ID` from equalling the
    request's `created_by_user_id` — violations rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and the gate forks on `type`."
    PRD §2.1: "When `X-User-Role` is `DepartmentManager`, `X-User-ID` is the
    `id` of the acting `Department`; ownership checks on any resource that
    references an employee compare the employee's `department_id` field to
    `X-User-ID`."

    Design: Corner/validations/sod_blocks_self_gate
    """
    ctx, emp = _program_with_employee(salary=14_000_000)
    dept_id = ctx["department"]["id"]
    xr = create_exception(ctx, emp, ctx["band2"], 15_000_000)
    assert xr["created_by_user_id"] == dept_id
    get_success_data(api_client.hrbp_pass_exception_request(xr["id"], HRBP))
    # CompManager role carrying the creator's id (the department id).
    res = api_client.comp_pass_exception_request(
        xr["id"], {"X-User-ID": dept_id, "X-User-Role": "CompManager",
                   "Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    after = validate_success(api.get_exception_request(xr["id"], MANAGER), 200)
    assert after["status"] == "HRBP_PASSED"


def test_ownership_mismatch_on_mapping_create(api):
    """PRD §2.1: "Six write operations enforce this ownership scope — creating
    a mapping decision, submitting it, resubmitting it, withdrawing it,
    creating an exception request, and resubmitting an exception request — and
    a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/ownership_mismatch_on_mapping_create
    """
    fw = setup_framework()
    from test_helpers import create_approved_profile
    p1 = create_approved_profile(fw["family"]["id"], fw["levels"][0]["id"],
                                 title="SWE I")
    p2 = create_approved_profile(fw["family"]["id"], fw["levels"][1]["id"],
                                 title="SWE II")
    dept_a = get_success_data(api_client.create_department(
        create_department_payload(name="Dept A", code="DA"), ADMIN))
    dept_b = get_success_data(api_client.create_department(
        create_department_payload(name="Dept B", code="DB"), ADMIN))
    emp = get_success_data(api_client.create_employee(
        create_employee_payload(dept_a["id"], p1["id"], fw["zone"]["id"],
                                employee_ref="E1"),
        HRBP))
    res = api.create_mapping_decision(
        create_mapping_decision_payload(emp["id"], p2["id"]),
        make_department_manager_headers(dept_b["id"]))
    validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)


def test_exception_rolling_cap_blocks_third_in_window(api):
    """PRD §2.6: "Fourth, intake spacing and frequency caps: two market cuts
    for the same job profile and geo zone pairing must be dated at least
    thirty days apart, and an employee may carry fewer than two
    in-flight-or-approved exception requests whose `created_at` falls within
    the trailing 365 days; violations surface as `ERR_CUT_TOO_CLOSE` and
    `ERR_EXCEPTION_ROLLING_CAP` respectively (both HTTP 422)."
    PRD §3.8: "The rolling cap forbids an employee from carrying two or more
    in-flight-or-approved exception requests — those in `SUBMITTED`,
    `HRBP_PASSED`, `FINANCE_REVIEW`, or `RETURNED`, plus those in `APPROVED` —
    whose `created_at` falls within the trailing 365 days; a creation that
    would breach it is rejected with `ERR_EXCEPTION_ROLLING_CAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/exception_rolling_capacity_window
    """
    from test_helpers import approve_exception_via_comp_gate
    ctx, emp = _program_with_employee(salary=14_000_000)
    x1 = approve_exception_via_comp_gate(ctx, emp, ctx["band2"], 15_000_000)
    assert x1["status"] == "APPROVED"
    x2 = approve_exception_via_comp_gate(ctx, emp, ctx["band2"], 15_500_000)
    assert x2["status"] == "APPROVED"
    res = api_client.create_exception_request(
        {
            "employee_id": emp["id"], "pay_band_id": ctx["band2"]["id"],
            "type": "OFF_CYCLE_INCREASE", "requested_salary_cents": 15_600_000,
            "justification": "x3 blocked",
        },
        make_department_manager_headers(ctx["department"]["id"]))
    validate_error(res, ApiErrorId.ERR_EXCEPTION_ROLLING_CAP, expected_status=422)


def test_exception_rolling_cap_slides_after_366_days(api):
    """PRD §3.8: "The rolling cap forbids an employee from carrying two or more
    in-flight-or-approved exception requests — those in `SUBMITTED`,
    `HRBP_PASSED`, `FINANCE_REVIEW`, or `RETURNED`, plus those in `APPROVED` —
    whose `created_at` falls within the trailing 365 days; a creation that
    would breach it is rejected with `ERR_EXCEPTION_ROLLING_CAP` (HTTP 422)."
    PRD §2.6: "The server owns a logical clock, and every date-sensitive rule
    in this document reads that clock — never the wall clock."

    Design: Difficulty/resource_temporal_overlap/exception_rolling_capacity_window
    """
    from test_helpers import approve_exception_via_comp_gate
    ctx, emp = _program_with_employee(salary=14_000_000)
    approve_exception_via_comp_gate(ctx, emp, ctx["band2"], 15_000_000)
    approve_exception_via_comp_gate(ctx, emp, ctx["band2"], 15_500_000)
    res = api_client.create_exception_request(
        {
            "employee_id": emp["id"], "pay_band_id": ctx["band2"]["id"],
            "type": "OFF_CYCLE_INCREASE", "requested_salary_cents": 15_600_000,
            "justification": "x3 blocked",
        },
        make_department_manager_headers(ctx["department"]["id"]))
    validate_error(res, ApiErrorId.ERR_EXCEPTION_ROLLING_CAP, expected_status=422)
    set_clock("2027-08-02T00:00:00Z")  # 366 days past the 2026-08-01 creates.
    ok = api_client.create_exception_request(
        {
            "employee_id": emp["id"], "pay_band_id": ctx["band2"]["id"],
            "type": "OFF_CYCLE_INCREASE", "requested_salary_cents": 15_600_000,
            "justification": "x4 after window",
        },
        make_department_manager_headers(ctx["department"]["id"]))
    x4 = validate_success(ok, 201)
    assert x4["status"] == "SUBMITTED"
    assert x4["finance_required"] is False


def test_exception_approve_then_rescind_conserves_pool(api):
    """PRD §2.10: "Approving an exception request and later rescinding it must
    leave the department's committed pool and the employee's salary exactly as
    they stood before the approval."
    PRD §3.8: "Rescission compensates an approval: a `CompManager` may move an
    `APPROVED` request to the terminal `RESCINDED` state while the logical
    clock is no later than thirty days after `applied_at`, with later attempts
    rejected as `ERR_REVERSE_WINDOW_EXPIRED`; rescission restores the
    employee's `base_salary_cents` from `pre_exception_salary_cents`, credits
    the department's `committed_pool_cents` by the positive part of the
    `applied_delta_cents`, and recomputes the payroll rollups and the
    employee's standing fields, leaving pool and salary exactly as they stood
    before approval."

    Design: Difficulty/compensating_invariant/exception_approve_rescind_conserves_pool
    """
    ctx, emp = _program_with_employee(salary=14_000_000)
    xr = create_exception(ctx, emp, ctx["band2"], 15_697_500,
                          ex_type="OFF_CYCLE_INCREASE", justification="at cap")
    get_success_data(api_client.hrbp_pass_exception_request(xr["id"], HRBP))
    approved = validate_success(
        api_client.comp_pass_exception_request(xr["id"], MANAGER), 200)
    assert approved["status"] == "APPROVED"
    assert approved["applied_delta_cents"] == 1_697_500
    emp_mid = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_mid["base_salary_cents"] == 15_697_500
    dept_mid = validate_success(api.get_department(ctx["department"]["id"], ADMIN), 200)
    assert dept_mid["committed_pool_cents"] == 1_697_500
    rescinded = validate_success(
        api_client.rescind_exception_request(xr["id"], MANAGER), 200)
    assert rescinded["status"] == "RESCINDED"
    dept_after = validate_success(api.get_department(ctx["department"]["id"], ADMIN), 200)
    assert dept_after["committed_pool_cents"] == 0
    emp_after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_after["base_salary_cents"] == 14_000_000
    assert emp_after["compa_ratio"] == pytest.approx(1.0769, abs=1e-9)


def test_exception_rescind_restores_within_window(api):
    """PRD §3.8: "Rescission compensates an approval: a `CompManager` may move
    an `APPROVED` request to the terminal `RESCINDED` state while the logical
    clock is no later than thirty days after `applied_at`, with later attempts
    rejected as `ERR_REVERSE_WINDOW_EXPIRED`; rescission restores the
    employee's `base_salary_cents` from `pre_exception_salary_cents`, credits
    the department's `committed_pool_cents` by the positive part of the
    `applied_delta_cents`, and recomputes the payroll rollups and the
    employee's standing fields, leaving pool and salary exactly as they stood
    before approval."

    Design: Difficulty/compensating_invariant/exception_approve_rescind_conserves_pool
    """
    from test_helpers import approve_exception_via_comp_gate
    ctx, emp = _program_with_employee(salary=14_000_000)
    xr = approve_exception_via_comp_gate(ctx, emp, ctx["band2"], 15_697_500)
    assert xr["status"] == "APPROVED"
    assert xr["pre_exception_salary_cents"] == 14_000_000
    rescinded = validate_success(
        api_client.rescind_exception_request(xr["id"], MANAGER), 200)
    assert rescinded["status"] == "RESCINDED"
    emp_after = validate_success(api.get_employee(emp["id"], HRBP), 200)
    assert emp_after["base_salary_cents"] == 14_000_000
    dept_after = validate_success(api.get_department(ctx["department"]["id"], ADMIN), 200)
    assert dept_after["committed_pool_cents"] == 0
