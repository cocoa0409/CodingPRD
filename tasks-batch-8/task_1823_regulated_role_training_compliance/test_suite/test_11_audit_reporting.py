"""Audit reports: compliance-rate variants, weighted pass rate, effectiveness."""
from test_helpers import (
    TEST_USERS,
    add_requirement,
    assert_instant_equal,
    assert_pct_equal,
    create_active_curriculum,
    create_audit_report,
    create_employee,
    create_regulator,
    create_role,
    find_assignment,
    reject_completion,
    set_clock,
    setup_curriculum_stack,
    setup_employee_with_assignment,
    submit_completion,
    validate_paginated,
    validate_success,
    verify_assignment,
)

ADMIN = TEST_USERS["compliance_admin_headers"]


def _setup_strict_lenient_population():
    """E1 fully verified; E2 submitted but still PENDING_REVIEW; the manager
    holds no assignments under the regulator and is excluded from the population."""
    set_clock("2026-08-03T09:00:00Z")
    stack = setup_curriculum_stack("POP", due_in_days=30)
    mgr_role = create_role(code="R-MGMT", name="Management")
    mgr = create_employee("M-001", mgr_role["id"], full_name="Mgr One")
    e1 = create_employee("E-001", stack["role"]["id"], full_name="Emp One",
                         manager_id=mgr["id"])
    e2 = create_employee("E-002", stack["role"]["id"], full_name="Emp Two",
                         manager_id=mgr["id"])
    a1 = find_assignment(e1["id"], curriculum_id=stack["curriculum"]["id"])
    verify_assignment(a1["id"], e1["id"], score_pct=90)
    a2 = find_assignment(e2["id"], curriculum_id=stack["curriculum"]["id"])
    submit_completion(a2["id"], e2["id"], score_pct=90)
    return stack["regulator"]


class TestComplianceRateVariants:
    def test_strict_variant_counts_submitted_as_open(self, api):
        """PRD §3.7: "An employee is compliant when their *open set* is empty,
        where the variant defines the open set: under `STRICT` it is the
        employee's assignments in `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, or
        `FAILED`; under `AUDIT_LENIENT` it is `ASSIGNED`, `IN_PROGRESS`, or
        `FAILED`, so a submission awaiting review already counts toward
        compliance."
        PRD §3.7: "The population is the set of employees whose `status` is
        `ACTIVE` or `ON_LEAVE`, who match every supplied filter in the
        `population_spec`, and who hold at least one assignment with progress
        other than `CANCELLED` whose curriculum belongs to the scope regulator —
        reported as `population_size`."

        Design: Difficulty/dual_variant_calc/compliance_rate_strict_vs_audit_lenient
        """
        reg = _setup_strict_lenient_population()
        report = create_audit_report(reg["id"], metric_variant="STRICT")
        metrics = report["metrics"]
        assert metrics["population_size"] == 2, "manager excluded: no scoped assignments"
        assert metrics["compliant_count"] == 1, "SUBMITTED counts as open under STRICT"
        assert_pct_equal(metrics["compliance_rate_pct"], 50.00, "strict rate")

    def test_audit_lenient_variant_counts_submitted_as_compliant(self, api):
        """PRD §3.7: "An employee is compliant when their *open set* is empty,
        where the variant defines the open set: under `STRICT` it is the
        employee's assignments in `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, or
        `FAILED`; under `AUDIT_LENIENT` it is `ASSIGNED`, `IN_PROGRESS`, or
        `FAILED`, so a submission awaiting review already counts toward
        compliance."

        Design: Difficulty/dual_variant_calc/compliance_rate_strict_vs_audit_lenient
        """
        reg = _setup_strict_lenient_population()
        report = create_audit_report(reg["id"], metric_variant="AUDIT_LENIENT")
        metrics = report["metrics"]
        assert metrics["population_size"] == 2
        assert metrics["compliant_count"] == 2, (
            "SUBMITTED excluded from the open set under AUDIT_LENIENT"
        )
        assert_pct_equal(metrics["compliance_rate_pct"], 100.00, "lenient rate")


def _setup_weighted_population():
    """CUR-W1 attempt-1 reviewed: accept(90), accept(90), reject(90) -> 66.67;
    CUR-W2 attempt-1 reviewed: 4 x accept(95) -> 100.00."""
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-W", name="Weighted Regulator")
    stack_role = create_role(code="R-W", name="Weighted Role")
    cur1 = create_active_curriculum(reg["id"], code="CUR-W1", title="Weighted One")
    cur2 = create_active_curriculum(reg["id"], code="CUR-W2", title="Weighted Two")
    add_requirement(stack_role["id"], cur1["id"], due_in_days=30)
    add_requirement(stack_role["id"], cur2["id"], due_in_days=30)
    emps = [
        create_employee(f"E-0{i}", stack_role["id"], full_name=f"Emp 0{i}")
        for i in range(1, 8)
    ]
    for emp in emps[:2]:  # E-01, E-02: CUR-W1 accept(90)
        a = find_assignment(emp["id"], curriculum_id=cur1["id"])
        verify_assignment(a["id"], emp["id"], score_pct=90)
    a3 = find_assignment(emps[2]["id"], curriculum_id=cur1["id"])  # E-03: reject(90)
    c3 = submit_completion(a3["id"], emps[2]["id"], score_pct=90)
    reject_completion(c3["id"], review_note="evidence unreadable")
    for emp in emps[3:]:  # E-04..E-07: CUR-W2 accept(95)
        a = find_assignment(emp["id"], curriculum_id=cur2["id"])
        verify_assignment(a["id"], emp["id"], score_pct=95)
    return reg


class TestWeightedFirstAttemptPassRate:
    def test_per_curriculum_rounding_precedes_weighted_mean(self, api):
        """PRD §3.7: "The rounding order is pinned: per-curriculum rates are
        rounded *before* the weighted mean, and pooling raw counts before
        rounding is non-conformant — the two methods can differ by a cent."
        PRD §3.7: "For each curriculum under the scope regulator that has at
        least one reviewed first attempt — a completion record with `attempt_no`
        1 whose `review_status` is `ACCEPTED` or `REJECTED` — the system
        computes that curriculum's first-attempt pass rate as one hundred times
        the accepted count divided by the reviewed total, rounded half up to 2
        decimal places *first*."

        Design: Difficulty/combinatorial_formula/audit_weighted_pass_rate_nested_rounding
        """
        reg = _setup_weighted_population()
        report = create_audit_report(reg["id"], metric_variant="STRICT")
        metrics = report["metrics"]
        assert metrics["population_size"] == 7
        assert_pct_equal(
            metrics["weighted_first_attempt_pass_rate_pct"], 85.72, "weighted rate",
        )
        # (66.67*3 + 100.00*4)/7 = 600.01/7 = 85.715714 -> 85.72; the pooled
        # order 6/7 = 85.714286 -> 85.71 would be non-conformant.
        assert float(metrics["weighted_first_attempt_pass_rate_pct"]) != 85.71

    def test_weighted_rate_is_independent_of_metric_variant(self, api):
        """PRD §3.7: "The request carries a `population_spec` object — a
        required `regulator_id`, with optional `role_id` and `manager_id`
        filters — and a `metric_variant` of `STRICT` or `AUDIT_LENIENT`."
        PRD §3.7: "the variant defines the open set"
        PRD §3.7: "The rounding order is pinned: per-curriculum rates are
        rounded *before* the weighted mean, and pooling raw counts before
        rounding is non-conformant — the two methods can differ by a cent."

        Design: Difficulty/combinatorial_formula/audit_weighted_pass_rate_nested_rounding
        """
        reg = _setup_weighted_population()
        report = create_audit_report(reg["id"], metric_variant="AUDIT_LENIENT")
        assert_pct_equal(
            report["metrics"]["weighted_first_attempt_pass_rate_pct"], 85.72,
            "weighted rate",
        )


def test_audit_report_empty_population_returns_zero_metrics(api):
    """PRD §3.7: "an empty population reports 0.00"
    PRD §3.7: "When no qualifying records exist at all, the metric reports 0.00."
    PRD §3.7: "Every report also carries `recordkeeping_expires_at`, computed as
    `generated_at` plus the scope regulator's `recordkeeping_years` calendar
    years — the regulator's default governs the report's retention regardless of
    any per-curriculum override."
    PRD §3.7: "Generation stamps `created_by` with the auditor's opaque operator
    id and `generated_at` with the logical clock."

    Design: Corner/calculations/audit_report_empty_population_returns_zero_metrics
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-NIL", name="NIL Regulator", recordkeeping_years=7)
    report = create_audit_report(reg["id"], metric_variant="STRICT")
    metrics = report["metrics"]
    assert metrics["population_size"] == 0
    assert metrics["compliant_count"] == 0
    assert_pct_equal(metrics["compliance_rate_pct"], 0.00, "compliance_rate_pct")
    assert metrics["overdue_count"] == 0
    assert_pct_equal(
        metrics["weighted_first_attempt_pass_rate_pct"], 0.00, "weighted rate",
    )
    assert_instant_equal(report["generated_at"], "2026-08-03T09:00:00Z", "generated_at")
    assert_instant_equal(
        report["recordkeeping_expires_at"], "2033-08-03T09:00:00Z",
        "recordkeeping_expires_at (+7 calendar years)",
    )


def test_effectiveness_aggregates_reviewed_first_attempts_only(api):
    """PRD §3.7: "It considers the completion records of that curriculum's
    assignments that are first attempts (`attempt_no` 1) and reviewed
    (`ACCEPTED` or `REJECTED`; `PENDING_REVIEW` and `VOIDED` are excluded), and
    returns the `curriculum_id` alongside `first_attempt_count` (the number of
    such records), `first_attempt_pass_count` (how many were accepted),
    `first_attempt_pass_rate_pct` (one hundred times passes divided by attempts,
    rounded half up to 2 decimal places, or 0.00 when there are no qualifying
    records), and `average_score_pct` (the mean of `score_pct` over the same
    records, rounded half up to 2 decimal places, or 0.00 when empty)."

    Design: Corner/calculations/effectiveness_aggregates_reviewed_first_attempts_only
    """
    ctx = setup_employee_with_assignment("EFF", due_in_days=30)
    cur, role = ctx["curriculum"], ctx["role"]
    e2 = create_employee("E-E2", role["id"], full_name="Eff Two")
    e3 = create_employee("E-E3", role["id"], full_name="Eff Three")
    e4 = create_employee("E-E4", role["id"], full_name="Eff Four")

    a1 = find_assignment(ctx["employee"]["id"], curriculum_id=cur["id"])
    verify_assignment(a1["id"], ctx["employee"]["id"], score_pct=90)
    a2 = find_assignment(e2["id"], curriculum_id=cur["id"])
    verify_assignment(a2["id"], e2["id"], score_pct=95)
    a3 = find_assignment(e3["id"], curriculum_id=cur["id"])
    c3 = submit_completion(a3["id"], e3["id"], score_pct=80)
    reject_completion(c3["id"], review_note="stale evidence")
    a4 = find_assignment(e4["id"], curriculum_id=cur["id"])
    submit_completion(a4["id"], e4["id"], score_pct=88)  # stays PENDING_REVIEW

    resp = api.get_curriculum_effectiveness(cur["id"], TEST_USERS["auditor_headers"])
    data = validate_success(resp, 200)
    assert data["first_attempt_count"] == 3, "PENDING_REVIEW record excluded"
    assert data["first_attempt_pass_count"] == 2
    assert_pct_equal(data["first_attempt_pass_rate_pct"], 66.67, "pass rate")
    assert_pct_equal(data["average_score_pct"], 88.33, "average score")


def test_assignment_list_filters_and_pagination_interaction(api):
    """PRD §3.4: "The assignment listing supports filters on `employee_id`,
    `role_requirement_id`, `curriculum_id`, `source_role_change_id`,
    `progress_status`, and `deadline_status`, alongside the standard `limit` and
    `offset` pagination parameters."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and maximum
    of 100. The `offset` parameter specifies the number of items to skip and
    defaults to 0."

    Design: Corner/endpoints/assignment_list_filters_and_pagination_interaction
    """
    ctx = setup_employee_with_assignment("PG", due_in_days=30)
    role = ctx["role"]
    e1 = ctx["employee"]
    create_employee("E-P2", role["id"], full_name="Pg Two")
    create_employee("E-P3", role["id"], full_name="Pg Three")

    filtered, meta = validate_paginated(
        api.list_assignments(ADMIN, params={"employee_id": e1["id"]})
    )
    assert meta["total_count"] == 1 and len(filtered) == 1

    page1, meta1 = validate_paginated(
        api.list_assignments(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_assignments(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
