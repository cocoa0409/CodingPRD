"""Advisor caseload, equity report, reassignment, and role authorization.

PRD §3.1 (caseload ledger, equity index, district target), §2.7 (OCC on
reassignment), §2.1 (role checks), §4 (endpoint role table).
"""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId, assert_advisor, assert_equity_report, assert_pct,
    add_enrollment, create_active_plan, create_advisor, create_application,
    create_pathway, create_plan, create_student, create_teacher, get_advisor,
    get_equity_report, get_student,
    make_advisor_headers, make_student_headers, make_teacher_headers,
    setup_student_with_active_plan, validate_error, validate_success,
)

ADMIN = TEST_USERS["district_admin_headers"]
WBL = TEST_USERS["wbl_coordinator_headers"]


class TestCaseloadBoundary:
    """Difficulty instance: equality at max_caseload rejects."""

    def _setup_full_advisor(self):
        advisor = create_advisor(full_name="B Adv", max_caseload=2)
        create_student(student_ref="B001", grade_level=11,
                       advisor_id=advisor["id"])
        create_student(student_ref="B002", grade_level=11,
                       demographic_group="GROUP_B", advisor_id=advisor["id"])
        return advisor

    def test_assignment_at_exact_max_rejected(self, api):
        """PRD §3.1: "If the enrollment payload names an `advisor_id`, that
        advisor takes the student, provided the advisor's
        `active_caseload_count` has not yet reached `max_caseload` — when the
        count already equals the ceiling, the assignment is rejected with
        `ERR_CASELOAD_FULL`, equality being sufficient to reject."

        Design: Difficulty/boundary_precision_check/caseload_full_at_exact_max
        """
        advisor = self._setup_full_advisor()
        assert get_advisor(advisor["id"])["active_caseload_count"] == 2
        resp = api.create_student(
            {"student_ref": "B003", "full_name": "Stu B3", "grade_level": 11,
             "demographic_group": "GROUP_C", "advisor_id": advisor["id"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CASELOAD_FULL)

    def test_rejected_assignment_leaves_count_unchanged(self, api):
        """PRD §3.1: "Either way, the chosen advisor's
        `active_caseload_count` rises by 1". PRD §2.4: "The `version` is an
        integer that starts at 1 when the resource is created and increments
        by exactly 1 on every mutation of that resource."

        Design: Difficulty/boundary_precision_check/caseload_full_at_exact_max
        """
        advisor = self._setup_full_advisor()
        before = get_advisor(advisor["id"])
        api.create_student(
            {"student_ref": "B003", "full_name": "Stu B3", "grade_level": 11,
             "demographic_group": "GROUP_C", "advisor_id": advisor["id"]},
            ADMIN,
        )
        after = get_advisor(advisor["id"])
        assert after["active_caseload_count"] == 2
        assert after["version"] == before["version"], (
            "a rejected enrollment mutates nothing"
        )


class TestCaseloadVariants:
    """Difficulty instance: SIMPLE headcount vs WEIGHTED workload view."""

    def _setup_three_advisees(self):
        advisor = create_advisor(full_name="A Three", max_caseload=50)
        pathway = create_pathway(pathway_code="GEN")
        s1 = create_student(student_ref="S101", full_name="Senior NoPlan",
                            grade_level=12, advisor_id=advisor["id"])
        s2 = create_student(student_ref="S102", full_name="Junior Plan",
                            grade_level=11, demographic_group="GROUP_B",
                            advisor_id=advisor["id"])
        s3 = create_student(student_ref="S103", full_name="Soph Plan",
                            grade_level=10, demographic_group="GROUP_C",
                            advisor_id=advisor["id"])
        create_active_plan(s2, pathway["id"], advisor["id"])
        create_active_plan(s3, pathway["id"], advisor["id"])
        return advisor

    def test_simple_count_is_plain_headcount(self, api):
        """PRD §3.1: "The `active_caseload_count` is the plain count of
        assigned students whose `status` is `ENROLLED`. The
        `caseload_load_simple` is the same headcount, exposed under that name
        for the headcount view."

        Design: Difficulty/dual_variant_calc/caseload_load_simple_vs_weighted
        """
        advisor = self._setup_three_advisees()
        report = get_equity_report(advisor["id"])
        assert_equity_report(report)
        assert report["active_caseload_count"] == 3
        assert report["caseload_load_simple"] == 3

    def test_weighted_load_applies_grade_and_plan_weights(self, api):
        """PRD §3.1: "The `caseload_load_weighted` is the workload-equity
        view: each enrolled advisee contributes a base weight of 2.0 for a
        twelfth-grader, 1.5 for an eleventh-grader, or 1.0 for any other
        grade, plus a further 0.5 whenever the advisee has no plan in `ACTIVE`
        status; the weights are summed and the total rounded half-up to 2
        decimal places".

        Design: Difficulty/dual_variant_calc/caseload_load_simple_vs_weighted
        """
        advisor = self._setup_three_advisees()
        report = get_equity_report(advisor["id"])
        # grade 12 without ACTIVE plan: 2.0 + 0.5 = 2.5
        # grade 11 with ACTIVE plan: 1.5; grade 10 with ACTIVE plan: 1.0
        assert_pct(report["caseload_load_weighted"], 5.0)


class TestEquityGapRounding:
    """Difficulty instance: per-group round-then-sum pinned order."""

    def _setup_district(self):
        ax = create_advisor(full_name="Eq X", max_caseload=50)
        ay = create_advisor(full_name="Eq Y", max_caseload=50)
        roster = (("E01", "GROUP_A", ax), ("E02", "GROUP_A", ax),
                  ("E03", "GROUP_B", ax), ("E04", "GROUP_B", ay),
                  ("E05", "GROUP_C", ay), ("E06", "GROUP_C", ay),
                  ("E07", "GROUP_D", ay))
        for ref, group, advisor in roster:
            create_student(student_ref=ref, full_name=f"Stu {ref}",
                           grade_level=11, demographic_group=group,
                           advisor_id=advisor["id"])
        return ax, ay

    def test_equity_gap_uses_per_group_rounding(self, api):
        """PRD §3.1: "The rounding order is pinned and not negotiable: for
        each group, the absolute difference between the two shares is computed
        and rounded half-up to 4 decimal places, and only after all four
        per-group gaps have been individually rounded are they summed,
        multiplied by 100, and rounded half-up to 2 decimal places. Summing
        the raw gaps first and rounding once at the end is a forbidden order —
        it produces a materially different index (85.71 rather than 85.72 on
        the canonical district fixture)."

        Design: Difficulty/combinatorial_formula/equity_gap_per_group_rounding
        """
        ax, ay = self._setup_district()
        report = get_equity_report(ax["id"])
        assert_equity_report(report)
        assert_pct(report["equity_gap_index"], 85.72)

    def test_equity_report_district_totals(self, api):
        """PRD §3.1: "second, the district totals are taken —
        `district_total_students` as the count of `ENROLLED` students and
        `district_total_capacity` as the sum of `max_caseload` across the
        snapshotted pool". PRD §3.1: "The equity report endpoint returns all
        of these figures together".

        Design: Difficulty/combinatorial_formula/equity_gap_per_group_rounding
        """
        ax, ay = self._setup_district()
        report = get_equity_report(ax["id"])
        assert report["district_total_students"] == 7
        assert report["active_caseload_count"] == 3


class TestDistrictTargetCaseload:
    """Difficulty instance: snapshot-first evaluation of the circular-looking
    district ratio."""

    def _setup_targets(self):
        ax = create_advisor(full_name="T X", max_caseload=10)
        ay = create_advisor(full_name="T Y", max_caseload=30)
        roster = (("T01", 9, "GROUP_A"), ("T02", 9, "GROUP_A"),
                  ("T03", 10, "GROUP_B"), ("T04", 10, "GROUP_B"),
                  ("T05", 10, "GROUP_B"), ("T06", 11, "GROUP_C"),
                  ("T07", 11, "GROUP_C"), ("T08", 11, "GROUP_C"),
                  ("T09", 12, "GROUP_D"), ("T10", 12, "GROUP_D"))
        for ref, grade, group in roster:
            create_student(student_ref=ref, full_name=f"Stu {ref}",
                           grade_level=grade, demographic_group=group,
                           advisor_id=ay["id"])
        return ax, ay

    def test_initial_targets_from_snapshot_ratio(self, api):
        """PRD §3.1: "first, the pool of `ACTIVE` advisors is snapshotted at
        evaluation start and never re-read during the computation; second, the
        district totals are taken ... third, a ratio of students to capacity
        is formed (0 when capacity is 0); and fourth, each active advisor's
        `target_caseload` is the ratio multiplied by that advisor's own
        `max_caseload`, rounded half-up to 2 decimal places".

        Design: Difficulty/combinatorial_formula/district_target_caseload_snapshot
        """
        ax, ay = self._setup_targets()
        report_x = get_equity_report(ax["id"])
        assert report_x["district_total_capacity"] == 40
        assert_pct(report_x["target_caseload"], 2.5)   # 10/40 * 10
        report_y = get_equity_report(ay["id"])
        assert_pct(report_y["target_caseload"], 7.5)   # 10/40 * 30

    def test_target_reevaluates_on_new_student(self, api):
        """PRD §3.1: "The equity report endpoint returns all of these figures
        together — `advisor_id`, `active_caseload_count`,
        `caseload_load_simple`, `caseload_load_weighted`, `equity_gap_index`,
        `target_caseload`, `district_total_students`, and
        `district_total_capacity` — and recomputes them at read time."

        Design: Difficulty/combinatorial_formula/district_target_caseload_snapshot
        """
        ax, ay = self._setup_targets()
        create_student(student_ref="T11", full_name="T Eleven", grade_level=12,
                       demographic_group="GROUP_D", advisor_id=ax["id"])
        report_x = get_equity_report(ax["id"])
        assert_pct(report_x["target_caseload"], 2.75)  # 11/40 * 10
        report_y = get_equity_report(ay["id"])
        assert_pct(report_y["target_caseload"], 8.25)  # 11/40 * 30


class TestReassignment:
    """Difficulty instance: district-wide caseload sum conserved."""

    def _setup_reassignment(self):
        ax = create_advisor(full_name="Jx", max_caseload=10)
        ay = create_advisor(full_name="Jy", max_caseload=10)
        s1 = create_student(student_ref="J001", grade_level=11,
                            advisor_id=ax["id"])
        create_student(student_ref="J002", grade_level=11,
                       demographic_group="GROUP_B", advisor_id=ax["id"])
        create_student(student_ref="J003", grade_level=11,
                       demographic_group="GROUP_C", advisor_id=ay["id"])
        return ax, ay, s1

    def test_reassignment_moves_student_and_counts(self, api):
        """PRD §3.1: "Each moved student's `assigned_advisor_id` switches to
        the target and each moved student's `version` increments by 1, while
        the source and target advisors each have their `version` incremented
        by 1. The response reports `moved_count`,
        `source_active_caseload_count`, and `target_active_caseload_count`
        after the move."

        Design: Difficulty/compensating_invariant/caseload_sum_conserved_on_reassignment
        """
        ax, ay, s1 = self._setup_reassignment()
        result = validate_success(api.create_reassignment(
            ax["id"],
            {"student_ids": [s1["id"]], "target_advisor_id": ay["id"],
             "expected_advisor_version": ax["version"]},
            ADMIN))
        assert result["moved_count"] == 1
        assert result["source_active_caseload_count"] == 1
        assert result["target_active_caseload_count"] == 2
        assert get_advisor(ax["id"])["active_caseload_count"] == 1
        assert get_advisor(ay["id"])["active_caseload_count"] == 2
        assert get_student(s1["id"])["assigned_advisor_id"] == ay["id"]

    def test_caseload_sum_conserved(self, api):
        """PRD §3.1: "The `active_caseload_count` is the plain count of
        assigned students whose `status` is `ENROLLED`." PRD §3.1: "For
        targeted corrections, a `DistrictAdmin` may bulk-move a listed set of
        enrolled students off an advisor by supplying `student_ids` and a
        `target_advisor_id`".

        Design: Difficulty/compensating_invariant/caseload_sum_conserved_on_reassignment
        """
        ax, ay, s1 = self._setup_reassignment()
        total_before = (get_advisor(ax["id"])["active_caseload_count"]
                        + get_advisor(ay["id"])["active_caseload_count"])
        assert total_before == 3
        api.create_reassignment(
            ax["id"],
            {"student_ids": [s1["id"]], "target_advisor_id": ay["id"],
             "expected_advisor_version": ax["version"]},
            ADMIN)
        total_after = (get_advisor(ax["id"])["active_caseload_count"]
                       + get_advisor(ay["id"])["active_caseload_count"])
        assert total_after == 3, "no student is double-counted or dropped"

    def test_stale_reassignment_returns_412(self, api):
        """PRD §2.7: "The request must carry `expected_advisor_version`,
        matching the source advisor's current `version`. If that version has
        advanced — a prior reassignment or a deactivation legitimately mutated
        the record — the stale plan is rejected with `ERR_STALE_VERSION`
        (HTTP 412) rather than silently re-applied."

        Design: Corner/validations/stale_reassignment_returns_412
        """
        ax = create_advisor(full_name="OCx", max_caseload=10)
        ay = create_advisor(full_name="OCy", max_caseload=10)
        s1 = create_student(student_ref="OC2", grade_level=11,
                            advisor_id=ax["id"])
        s2 = create_student(student_ref="OC3", grade_level=11,
                            demographic_group="GROUP_B", advisor_id=ax["id"])
        validate_success(api.create_reassignment(
            ax["id"],
            {"student_ids": [s1["id"]], "target_advisor_id": ay["id"],
             "expected_advisor_version": ax["version"]},
            ADMIN))

        resp = api.create_reassignment(
            ax["id"],
            {"student_ids": [s2["id"]], "target_advisor_id": ay["id"],
             "expected_advisor_version": ax["version"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_student(s2["id"])["assigned_advisor_id"] == ax["id"]


class TestEquityReportShape:
    def test_equity_report_shape_and_reverse_lookups(self, api):
        """PRD §3.1: "The equity report endpoint returns all of these figures
        together — `advisor_id`, `active_caseload_count`,
        `caseload_load_simple`, `caseload_load_weighted`, `equity_gap_index`,
        `target_caseload`, `district_total_students`, and
        `district_total_capacity` — and recomputes them at read time." PRD
        §3.1: "An advisor's current roster is readable through the reverse
        lookup of students assigned to that advisor". PRD §3.7: "per-student
        collections — plans, enrollments, applications (filterable by
        `submission_status`), requests, certifications, placements, audits,
        and outcome records — are all exposed through their respective reverse
        lookups".

        Design: Corner/endpoints/equity_report_shape_and_reverse_lookups
        """
        advisor = create_advisor(full_name="EQ Adv", max_caseload=10)
        pathway = create_pathway(pathway_code="GEQ")
        student = create_student(student_ref="EQ1", advisor_id=advisor["id"])
        create_plan(student, pathway["id"], advisor["id"])

        headers = make_advisor_headers(advisor["id"])
        report = validate_success(api.get_equity_report(advisor["id"],
                                                        headers))
        assert_equity_report(report)
        assert report["advisor_id"] == advisor["id"]
        assert report["active_caseload_count"] == 1

        students = validate_success(
            api.list_advisor_students(advisor["id"], headers))
        assert [s["id"] for s in students] == [student["id"]]

        plans = validate_success(api.list_student_plans(student["id"],
                                                        headers))
        assert len(plans) == 1
        assert plans[0]["status"] == "DRAFT"


class TestRoleAuthorization:
    def test_unauthenticated_request_returns_401(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose role value
        is not one of these five, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        resp = api.create_advisor(
            {"full_name": "No Auth", "email": "na@d.org", "max_caseload": 5},
            None,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_forbidden_role_pathway_create_returns_403(self, api):
        """PRD §2.1: "A request whose role is authenticated but is not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §4: `POST /ccr/pathways` is
        authorized for DistrictAdmin only.

        Design: Corner/validations/forbidden_role_pathway_create_returns_403
        """
        teacher = create_teacher(full_name="T Forbidden")
        resp = api.create_pathway(
            {"pathway_code": "NOPE", "name": "Nope",
             "required_course_codes": []},
            make_teacher_headers(teacher["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_student_cannot_transition_enrollment_returns_403(self, api):
        """PRD §2.1: "A request whose role is authenticated but is not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §4: `POST
        /ccr/enrollments/{id}/transition` is authorized for Advisor only.

        Design: Corner/rbac/student_cannot_transition_enrollment_returns_403
        """
        ctx = setup_student_with_active_plan()
        enr = add_enrollment(ctx["student"]["id"], ctx["plan"]["id"],
                             ctx["advisor"]["id"], "X1", 2)
        resp = api.transition_enrollment(
            enr["id"], {"to_status": "ENROLLED"},
            make_student_headers(ctx["student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_wbl_coordinator_cannot_record_decision_returns_403(self, api):
        """PRD §2.1: "A request whose role is authenticated but is not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §4: `POST
        /ccr/applications/{id}/decision` is authorized for DistrictAdmin only.

        Design: Corner/rbac/wbl_coordinator_cannot_record_decision_returns_403
        """
        ctx = setup_student_with_active_plan()
        app = create_application(ctx["student"])
        resp = api.decide_application(app["id"], {"to_decision": "ACCEPTED"},
                                      WBL)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_advisor_cannot_create_site_returns_403(self, api):
        """PRD §2.1: "A request whose role is authenticated but is not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §4: `POST /ccr/placement-sites` is
        authorized for DistrictAdmin only.

        Design: Corner/rbac/advisor_cannot_create_site_returns_403
        """
        advisor = create_advisor(full_name="SC Adv", max_caseload=10)
        resp = api.create_placement_site(
            {"site_code": "NOPE", "name": "Nope",
             "max_concurrent_placements": 5},
            make_advisor_headers(advisor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
