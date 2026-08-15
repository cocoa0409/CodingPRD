"""Degree audits: FINAL vs CONDITIONAL projection, credit boundaries, the
waterfall allocation, min-grade filtering, what-if analysis, supersession, OCC,
and audit list filtering (PRD §2.10, §3.4).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_gpa,
    create_audit_payload,
    declare,
    enroll,
    get_student_program,
    make_course,
    make_program,
    make_requirement_group,
    make_student,
    run_audit,
    setup_graduation_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)


def _groups_by_code(audit):
    return {g["group_code"]: g for g in audit["groups_result"]}


class TestFinalVsConditionalProjection:
    def _setup(self):
        return setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-PROJ", "name": "BS Proj",
                "min_total_credits": 12, "min_gpa": 2.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            student_overrides={"student_number": "S-PROJ", "legal_name": "Pat Proj"},
            enrollment_specs=[
                {"course_code": "PRJ1", "term": "2024-FA", "grade": "A"},
                {"course_code": "PRJ1", "term": "2025-SP", "grade": "A"},
                {"course_code": "PRJ1", "term": "2025-FA", "grade": "A"},
                {"course_code": "PRJ1", "term": "2026-SP"},  # IN_PROGRESS, 3cr
            ],
            audit_kinds=(),  # audits run explicitly in each test
        )

    def test_final_audit_counts_completed_only(self, api, registrar_headers):
        """PRD §3.4: "`total_credits_applied` sums `credits_earned` over the
        student's `COMPLETED` enrollments, institutional and transfer combined."
        and "`outstanding_credits` is the shortfall of `total_credits_applied`
        below the target program's `min_total_credits`, floored at zero when the
        applied credits meet or exceed the minimum."
        PRD §3.4: "every other kind reports zero there and gives in-progress
        work no weight whatsoever"

        Design: Difficulty/dual_variant_calc/audit_final_vs_conditional_projection
        """
        sc = self._setup()
        audit = run_audit(sc.student_program["id"], "FINAL")
        assert audit["total_credits_applied"] == 9
        assert audit["outstanding_credits"] == 3
        assert audit["in_progress_credits_counted"] == 0
        assert audit["overall_satisfied"] is False
        # GPA snapshot covers completed work only: 3x3cr A -> 4.000.
        assert_gpa(audit["gpa_at_audit"], 4.000)

    def test_conditional_audit_projects_in_progress(self, api, registrar_headers):
        """PRD §3.4: "A `CONDITIONAL` audit additionally projects every
        `IN_PROGRESS` enrollment at its course's full `credits`, adds that
        projected sum into `total_credits_applied`, and reports the projected
        amount as `in_progress_credits_counted`; every other kind reports zero
        there and gives in-progress work no weight whatsoever — so identical
        records can satisfy under `CONDITIONAL` and fall short under `STANDARD`."
        PRD §3.4: "`gpa_at_audit`, a snapshot of the student's `institutional_gpa`
        at audit time — completed work only, even for a `CONDITIONAL` run."

        Design: Difficulty/dual_variant_calc/audit_final_vs_conditional_projection
        """
        sc = self._setup()
        final_audit = run_audit(sc.student_program["id"], "FINAL")
        assert final_audit["overall_satisfied"] is False

        conditional = run_audit(sc.student_program["id"], "CONDITIONAL")
        assert conditional["total_credits_applied"] == 12
        assert conditional["outstanding_credits"] == 0
        assert conditional["in_progress_credits_counted"] == 3
        assert conditional["overall_satisfied"] is True
        assert_gpa(conditional["gpa_at_audit"], 4.000)


class TestTotalCreditsExactBoundary:
    def test_applied_equals_min_total_outstanding_zero(self, api, registrar_headers):
        """PRD §3.4: "`outstanding_credits` is the shortfall of
        `total_credits_applied` below the target program's `min_total_credits`,
        floored at zero when the applied credits meet or exceed the minimum."
        At 9 applied vs min_total_credits 9 the shortfall floors to exactly 0.

        Design: Difficulty/boundary_precision_check/total_credits_exact_boundary
        """
        sc = setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-TC", "name": "BS TC",
                "min_total_credits": 9, "min_gpa": 2.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            student_overrides={"student_number": "S-TC", "legal_name": "Tess Count"},
            enrollment_specs=[
                {"course_code": "TC3", "term": "2024-FA", "grade": "A"},
                {"course_code": "TC3", "term": "2025-SP", "grade": "A"},
                {"course_code": "TC3", "term": "2025-FA", "grade": "A"},
            ],
            audit_kinds=(),
        )
        audit = run_audit(sc.student_program["id"], "STANDARD")
        assert audit["total_credits_applied"] == 9
        assert audit["outstanding_credits"] == 0

    def test_overall_satisfied_at_exact_credit_boundary(self, api, registrar_headers):
        """PRD §3.4: "The audit's verdict, `overall_satisfied`, requires three
        conjuncts: every group of the target program satisfied,
        `total_credits_applied` at least the program's `min_total_credits`, and
        `gpa_at_audit` at least the program's `min_gpa`." The comparison is
        inclusive, so 9 == 9 satisfies the credit conjunct (no groups, GPA 4.000
        >= 2.0).

        Design: Difficulty/boundary_precision_check/total_credits_exact_boundary
        """
        sc = setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-TC", "name": "BS TC",
                "min_total_credits": 9, "min_gpa": 2.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            student_overrides={"student_number": "S-TC", "legal_name": "Tess Count"},
            enrollment_specs=[
                {"course_code": "TC3", "term": "2024-FA", "grade": "A"},
                {"course_code": "TC3", "term": "2025-SP", "grade": "A"},
                {"course_code": "TC3", "term": "2025-FA", "grade": "A"},
            ],
            audit_kinds=(),
        )
        audit = run_audit(sc.student_program["id"], "STANDARD")
        assert audit["overall_satisfied"] is True


class TestWaterfallAllocation:
    def _audit(self):
        sc = setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-WF", "name": "BS WF",
                "min_total_credits": 6, "min_gpa": 2.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            groups=[
                {"group_code": "CORE", "required_credits": 6, "min_grade": "C",
                 "eligible_course_codes": ["CS101", "CS102"]},
                {"group_code": "GEN", "required_credits": 3, "min_grade": "D",
                 "eligible_course_codes": ["CS101"]},
            ],
            student_overrides={"student_number": "S-WF", "legal_name": "Wren Ford"},
            enrollment_specs=[
                {"course_code": "CS101", "term": "2024-FA", "grade": "A"},
                {"course_code": "CS102", "term": "2025-SP", "grade": "B"},
            ],
            audit_kinds=(),
        )
        return run_audit(sc.student_program["id"], "STANDARD")

    def test_largest_deficit_allocation_order(self, api, registrar_headers):
        """PRD §3.4: "A single enrollment may feed at most one group. Eligible
        enrollments are processed oldest first by `created_at`, with ties broken
        by course code ascending and then by `term` ascending; each enrollment is
        allocated to the eligible group with the largest remaining deficit —
        effective requirement minus credits already allocated — with ties broken
        by `group_code` ascending". CS101 (created first) is eligible for CORE
        (deficit 6) and GEN (deficit 3), so it feeds CORE; CS102 then completes
        CORE and GEN starves.

        Design: Difficulty/combinatorial_formula/waterfall_allocation_group_contention
        """
        audit = self._audit()
        groups = _groups_by_code(audit)
        assert groups["CORE"]["credits_applied"] == 6
        assert groups["CORE"]["effective_required_credits"] == 6
        assert groups["CORE"]["satisfied"] is True
        assert groups["GEN"]["credits_applied"] == 0
        assert groups["GEN"]["effective_required_credits"] == 3
        assert groups["GEN"]["satisfied"] is False

    def test_group_conjunct_fails_despite_total_credits_met(self, api, registrar_headers):
        """PRD §3.4: "The audit's verdict, `overall_satisfied`, requires three
        conjuncts: every group of the target program satisfied,
        `total_credits_applied` at least the program's `min_total_credits`, and
        `gpa_at_audit` at least the program's `min_gpa`." Here totals (6 >= 6)
        and GPA (3.500 >= 2.0) pass, yet the starved GEN group fails the verdict.

        Design: Difficulty/combinatorial_formula/waterfall_allocation_group_contention
        """
        audit = self._audit()
        assert audit["total_credits_applied"] == 6
        assert audit["overall_satisfied"] is False


class TestMinGradeFilter:
    def test_below_min_grade_earns_total_but_not_group_credit(self, api, registrar_headers):
        """PRD §3.4: "An enrollment is eligible for a group when it is
        `COMPLETED`, its grade is one of `A` through `D`, the grade's value
        (A=4, B=3, C=2, D=1) is at least the value of the group's `min_grade`" —
        D (1) is below the group's C (2), so the course earns credit toward
        totals yet feeds no group.

        Design: Corner/calculations/min_grade_filter_excludes_below_grade_credit
        """
        sc = setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-MG", "name": "BS MG",
                "min_total_credits": 3, "min_gpa": 1.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            groups=[
                {"group_code": "G", "required_credits": 3, "min_grade": "C",
                 "eligible_course_codes": ["MG1"]},
            ],
            student_overrides={"student_number": "S-MG", "legal_name": "Min Grade"},
            enrollment_specs=[{"course_code": "MG1", "term": "2024-FA", "grade": "D"}],
            audit_kinds=(),
        )
        assert sc.enrollments[0]["credits_earned"] == 3

        audit = run_audit(sc.student_program["id"], "STANDARD")
        assert audit["total_credits_applied"] == 3
        groups = _groups_by_code(audit)
        assert groups["G"]["credits_applied"] == 0
        assert groups["G"]["satisfied"] is False
        assert audit["overall_satisfied"] is False


class TestWhatIfAnalysis:
    def _setup(self):
        pa = make_program(program_code="BS-WI-A", name="PA",
                          min_total_credits=3, min_gpa=2.0,
                          catalog_year_start=2024, catalog_year_end=2028)
        pb = make_program(program_code="BS-WI-B", name="PB",
                          min_total_credits=3, min_gpa=2.0,
                          catalog_year_start=2024, catalog_year_end=2028)
        make_requirement_group(pb["id"], group_code="GB", required_credits=3,
                               min_grade="C", eligible_course_codes=["WX1"])
        pc = make_program(program_code="BS-WI-C", name="PC",
                          min_total_credits=3, min_gpa=2.0,
                          catalog_year_start=2026, catalog_year_end=2030)
        course = make_course(course_code="WX1", title="WX", credits=3)
        student = make_student(student_number="S-WI", legal_name="Whit If")
        enroll(student["id"], course["id"], "2024-FA", grade="B")
        sp = declare(student["id"], pa["id"], catalog_year=2024)
        return pa, pb, pc, student, sp

    def test_what_if_evaluates_target_program(self, api, registrar_headers):
        """PRD §3.4: "A `WHAT_IF` audit evaluates a *different* program as-if the
        student were changing majors" and "Each audit records `catalog_year_used`,
        the declaration's governing catalog year". PRD §3.4: "`WHAT_IF` audits
        never touch the flag."

        Against PB the student's WX1 B (3.00 >= C) satisfies group GB and totals.

        Design: Corner/calculations/what_if_major_change_evaluation
        """
        _pa, pb, _pc, _student, sp = self._setup()
        audit = run_audit(sp["id"], "WHAT_IF", target_program_id=pb["id"])
        assert audit["overall_satisfied"] is True
        assert audit["catalog_year_used"] == 2024

        after = get_student_program(sp["id"])
        assert after["latest_audit_satisfied"] is False

    def test_what_if_target_catalog_range_mismatch_rejected(self, api, registrar_headers):
        """PRD §3.4: "the what-if target must itself be `ACTIVE` (else
        `ERR_PROGRAM_RETIRED`) and must cover the declaration's `catalog_year`
        within its own half-open catalog range (else
        `ERR_CATALOG_YEAR_OUT_OF_RANGE`)." PC covers [2026,2030); the
        declaration's 2024 falls outside it.

        Design: Corner/calculations/what_if_major_change_evaluation
        """
        _pa, _pb, pc, _student, sp = self._setup()
        res = api.create_audit(
            sp["id"],
            create_audit_payload("WHAT_IF", sp["version"], target_program_id=pc["id"]),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_CATALOG_YEAR_OUT_OF_RANGE.value, expected_status=422)

    def test_what_if_requires_target_program(self, api, registrar_headers):
        """PRD §3.4: "A `WHAT_IF` audit evaluates a *different* program as-if the
        student were changing majors, and therefore requires `target_program_id`
        naming the hypothetical program — omitting it is `ERR_INVALID_REQUEST`"

        Design: Corner/errors/what_if_audit_requires_target_program
        """
        program = make_program(program_code="BS-WT", name="BS WT")
        student = make_student(student_number="S-WT", legal_name="Watt If")
        sp = declare(student["id"], program["id"], catalog_year=2024)
        res = api.create_audit(
            sp["id"], create_audit_payload("WHAT_IF", sp["version"]), registrar_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


class TestAuditSupersession:
    def test_same_kind_recreate_supersedes_prior_current(self, api, registrar_headers):
        """PRD §3.4: "A successful run creates the audit in `CURRENT` status and
        supersedes the prior `CURRENT` audit of the same kind on that declaration
        — for `WHAT_IF`, the same kind *and* the same `target_program_id` —
        moving the predecessor to `SUPERSEDED`."
        PRD §3.4: "Audit history can be reviewed filtered by `audit_kind`,
        `status`, and `target_program_id`."

        Design: Corner/state_machines/audit_supersede_on_same_kind_recreate
        """
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": "BS-SU", "name": "BS SU"},
            student_overrides={"student_number": "S-SU", "legal_name": "Sue Per"},
            audit_kinds=(),
        )
        sp_id = sc.student_program["id"]
        first = run_audit(sp_id, "STANDARD")
        second = run_audit(sp_id, "STANDARD")
        assert second["id"] != first["id"]
        assert second["status"] == "CURRENT"

        current, meta = validate_paginated(api.list_audits(
            sp_id, registrar_headers,
            params={"audit_kind": "STANDARD", "status": "CURRENT"}))
        assert [a["id"] for a in current] == [second["id"]]
        assert meta["total_count"] == 1

        superseded, _ = validate_paginated(api.list_audits(
            sp_id, registrar_headers,
            params={"audit_kind": "STANDARD", "status": "SUPERSEDED"}))
        assert [a["id"] for a in superseded] == [first["id"]]


class TestAuditOptimisticConcurrency:
    def test_stale_expected_version_rejected(self, api, registrar_headers):
        """PRD §2.10: "The request must include `expected_student_program_version`,
        carrying the `version` of the declaration as the client last observed it.
        If the declaration's current `version` no longer matches, the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.10: "a new audit supersedes the previous `CURRENT` audit of the
        same kind, and the act of creation itself advances the declaration's
        `version`."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_audit_create
        """
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": "BS-OCC", "name": "BS OCC"},
            student_overrides={"student_number": "S-OCC", "legal_name": "Olive CC"},
            audit_kinds=(),
        )
        sp_id = sc.student_program["id"]
        observed_version = sc.student_program["version"]

        first = validate_success(api.create_audit(
            sp_id, create_audit_payload("STANDARD", observed_version),
            registrar_headers), 201)
        assert first["status"] == "CURRENT"
        after = get_student_program(sp_id)
        assert after["version"] == observed_version + 1

        res = api.create_audit(
            sp_id, create_audit_payload("STANDARD", observed_version), registrar_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


class TestAuditListFiltering:
    def test_kind_status_filter_and_pagination_meta(self, api, registrar_headers):
        """PRD §3.4: "Audit history can be reviewed filtered by `audit_kind`,
        `status`, and `target_program_id`."
        PRD §2.3: "The `limit` parameter caps the number of items returned; when
        omitted it defaults to 10" and "Paginated list responses carry the fields
        `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of
        the envelope."

        Design: Corner/endpoints/audit_list_filtering_and_pagination_fields
        """
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": "BS-LF", "name": "BS LF"},
            student_overrides={"student_number": "S-LF", "legal_name": "Lee Filter"},
            audit_kinds=(),
        )
        sp_id = sc.student_program["id"]
        run_audit(sp_id, "STANDARD")
        final_audit = run_audit(sp_id, "FINAL")

        data, meta = validate_paginated(api.list_audits(
            sp_id, registrar_headers,
            params={"audit_kind": "FINAL", "status": "CURRENT"}))
        assert [a["id"] for a in data] == [final_audit["id"]]
        assert data[0]["audit_kind"] == "FINAL"
        assert meta["total_count"] == 1
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
