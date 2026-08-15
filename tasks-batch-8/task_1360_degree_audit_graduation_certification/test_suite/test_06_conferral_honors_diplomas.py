"""Conferral, Latin honors, and diploma production: GPA-basis divergence,
threshold inclusivity, grade-change ledger invariance, honors-policy gating,
diploma state guards, and revoke/reissue (PRD §2.9, §3.2, §3.7).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_gpa,
    confer,
    enroll,
    get_student,
    list_diplomas,
    make_course,
    make_student,
    setup_graduation_pipeline,
    validate_error,
    validate_success,
)

HONORS_POLICY = {
    "cum_threshold": 3.5, "magna_threshold": 3.75, "summa_threshold": 3.9,
    "effective_first_year": 2024, "effective_last_year": 2027,
}

# 9cr institutional A + 1cr institutional B + 10cr transfer C:
# institutional GPA 39.00/10 = 3.900; cumulative GPA 59.00/20 = 2.950.
def _divergent_enrollments(prefix):
    """Spec list for one scenario; course codes are prefixed per scenario
    because both scenarios in a test run against the same server and course
    codes are globally unique (PRD §3.2)."""
    return [
        {"course_code": f"{prefix}100", "term": "2024-FA", "grade": "A"},
        {"course_code": f"{prefix}100", "term": "2025-SP", "grade": "A"},
        {"course_code": f"{prefix}100", "term": "2025-FA", "grade": "A"},
        {"course_code": f"{prefix}101", "term": "2025-FA", "grade": "B", "credits": 1},
        {"course_code": f"{prefix}R500", "term": "2024-FA", "grade": "C", "credits": 5, "is_transfer": True},
        {"course_code": f"{prefix}R500", "term": "2025-SP", "grade": "C", "credits": 5, "is_transfer": True},
    ]


class TestHonorsGpaBasisDivergence:
    def _conferred_pair(self):
        sc_inst = setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-INST", "name": "BS Inst",
                "min_total_credits": 20, "min_gpa": 2.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            honors_policy={**HONORS_POLICY, "honors_gpa_basis": "INSTITUTIONAL",
                           "residency_min_credits": 10},
            student_overrides={"student_number": "S-INST", "legal_name": "Alice Example"},
            enrollment_specs=_divergent_enrollments("CI"),
            application_overrides={"diploma_name": "Alice A. Example"},
            walk_to="CLEARED",
        )
        sc_cum = setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-CUM", "name": "BS Cum",
                "min_total_credits": 20, "min_gpa": 2.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            honors_policy={**HONORS_POLICY, "honors_gpa_basis": "CUMULATIVE",
                           "residency_min_credits": 10},
            student_overrides={"student_number": "S-CUM", "legal_name": "Bob Example"},
            enrollment_specs=_divergent_enrollments("CC"),
            walk_to="CLEARED",
        )
        return sc_inst, sc_cum

    def test_identical_records_yield_divergent_basis_gpas(self, api, registrar_headers):
        """PRD §3.2: "`institutional_gpa` is the credit-weighted GPA over
        non-transfer GPA-bearing enrollments, while `cumulative_gpa` spans all
        GPA-bearing enrollments including transfer work; identical underlying
        data yields different values under the two bases whenever transfer grades
        differ from the institutional average."

        Both students: institutional 39.00/10 = 3.900, cumulative 59.00/20 = 2.950.

        Design: Difficulty/dual_variant_calc/honors_gpa_basis_divergence
        """
        sc_inst, sc_cum = self._conferred_pair()
        for sc in (sc_inst, sc_cum):
            student = get_student(sc.student["id"])
            assert_gpa(student["institutional_gpa"], 3.900)
            assert_gpa(student["cumulative_gpa"], 2.950)
            assert student["institutional_earned_credits"] == 10
            assert student["total_earned_credits"] == 20

    def test_conferral_designations_diverge_by_basis(self, api, registrar_headers):
        """PRD §3.7: "The basis GPA is then selected by the policy's
        `honors_gpa_basis`: `institutional_gpa` under `INSTITUTIONAL`,
        `cumulative_gpa` under `CUMULATIVE`, so the same student can earn a
        designation under one basis and `NONE` under the other when transfer work
        pulls the averages apart."
        PRD §3.7: "And a diploma is created in `PENDING` status whose
        `printed_name` is the application's `diploma_name` — or the student's
        `legal_name` when no diploma name was supplied — whose `conferral_date`
        is the application's `expected_conferral_date`, whose
        `honors_designation` copies the freshly computed designation, and whose
        `reissue_of_diploma_id` is null because it is the original."

        INSTITUTIONAL basis 3.900 >= 3.9 -> SUMMA_CUM_LAUDE; CUMULATIVE basis
        2.950 < 3.5 -> NONE.

        Design: Difficulty/dual_variant_calc/honors_gpa_basis_divergence
        """
        sc_inst, sc_cum = self._conferred_pair()

        conferred_inst = confer(sc_inst.application["id"])
        assert conferred_inst["honors_designation"] == "SUMMA_CUM_LAUDE"

        conferred_cum = confer(sc_cum.application["id"])
        assert conferred_cum["honors_designation"] == "NONE"

        diplomas, meta = list_diplomas(application_id=sc_inst.application["id"])
        assert meta["total_count"] == 1
        assert diplomas[0]["honors_designation"] == "SUMMA_CUM_LAUDE"


class TestHonorsThresholdBoundary:
    def _boundary_scenario(self):
        # 9cr A + 3cr B -> 45.00/12 = 3.750, exactly the magna threshold.
        return setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-HB", "name": "BS HB",
                "min_total_credits": 12, "min_gpa": 2.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            honors_policy={**HONORS_POLICY, "honors_gpa_basis": "INSTITUTIONAL",
                           "residency_min_credits": 10},
            student_overrides={"student_number": "S-HB", "legal_name": "Hank Bounds"},
            enrollment_specs=[
                {"course_code": "HB3", "term": "2024-FA", "grade": "A"},
                {"course_code": "HB3", "term": "2025-SP", "grade": "A"},
                {"course_code": "HB3", "term": "2025-FA", "grade": "A"},
                {"course_code": "HB3", "term": "2026-SP", "grade": "B"},
            ],
            walk_to="CLEARED",
        )

    def test_gpa_exactly_at_magna_threshold(self, api, registrar_headers):
        """PRD §2.9: "Latin-honors thresholds are compared against the
        already-rounded three-decimal GPA, and the comparison is inclusive — a
        GPA exactly equal to a threshold earns that threshold's tier."

        The student's basis GPA lands exactly on 3.750.

        Design: Difficulty/boundary_precision_check/honors_threshold_exact_gpa_boundary
        """
        sc = self._boundary_scenario()
        student = get_student(sc.student["id"])
        assert_gpa(student["institutional_gpa"], 3.750)
        assert student["institutional_earned_credits"] == 12  # residency 10 met

    def test_conferral_at_exact_threshold_earns_magna(self, api, registrar_headers):
        """PRD §3.7: "The designation is `SUMMA_CUM_LAUDE` when the basis reaches
        `summa_threshold`, otherwise `MAGNA_CUM_LAUDE` when it reaches
        `magna_threshold`, otherwise `CUM_LAUDE` when it reaches `cum_threshold`,
        otherwise `NONE`; a basis exactly equal to a threshold earns that tier."

        Basis 3.750 reaches magna_threshold (3.75) but not summa_threshold (3.9).

        Design: Difficulty/boundary_precision_check/honors_threshold_exact_gpa_boundary
        """
        sc = self._boundary_scenario()
        conferred = confer(sc.application["id"])
        assert conferred["honors_designation"] == "MAGNA_CUM_LAUDE"
        assert conferred["honors_designation"] not in ("CUM_LAUDE", "SUMMA_CUM_LAUDE", "NONE")


class TestGradeChangeLedgerInvariant:
    def _graded_student(self):
        course = make_course(course_code="GC3", title="GC", credits=3)
        student = make_student(student_number="S-GC", legal_name="Gus Cole")
        enrollment = enroll(student["id"], course["id"], "2024-FA", grade="A")
        return student, enrollment

    def test_grade_change_a_to_f_zeroes_earned_credits(self, api, registrar_headers):
        """PRD §3.2: "A letter grade on a `COMPLETED` enrollment keeps it
        `COMPLETED` with corrected figures" and "An enrollment's `credits_earned`
        equals the course's credits when the enrollment is `COMPLETED` with a
        grade of `A` through `D`, and is zero in every other case — an `F` earns
        nothing, and a withdrawal earns nothing."

        A -> F: the F keeps 3 credits in the GPA denominator with 0 points, so
        total_earned_credits falls 3 -> 0 and institutional_gpa to 0.000.

        Design: Difficulty/compensating_invariant/grade_change_credit_ledger_invariant
        """
        student, enrollment = self._graded_student()
        initial = get_student(student["id"])
        assert initial["total_earned_credits"] == 3
        assert_gpa(initial["institutional_gpa"], 4.000)

        changed = validate_success(api.change_grade(
            enrollment["id"], {"new_grade": "F", "reason": "academic integrity"},
            registrar_headers), 200)
        assert changed["status"] == "COMPLETED"
        assert changed["credits_earned"] == 0

        after = get_student(student["id"])
        assert after["total_earned_credits"] == 0
        assert_gpa(after["institutional_gpa"], 0.000)

    def test_compensating_f_to_a_restores_ledger_exactly(self, api, registrar_headers):
        """PRD §3.2: "`total_earned_credits` sums `credits_earned` over all of
        the student's `COMPLETED` enrollments, institutional and transfer alike."
        The compensating F -> A change restores the ledger to its exact
        pre-change values (3 earned, GPA 4.000) with zero drift.

        Design: Difficulty/compensating_invariant/grade_change_credit_ledger_invariant
        """
        student, enrollment = self._graded_student()
        validate_success(api.change_grade(
            enrollment["id"], {"new_grade": "F", "reason": "academic integrity"},
            registrar_headers), 200)
        restored = validate_success(api.change_grade(
            enrollment["id"], {"new_grade": "A", "reason": "integrity finding reversed"},
            registrar_headers), 200)
        assert restored["credits_earned"] == 3

        after = get_student(student["id"])
        assert after["total_earned_credits"] == 3
        assert_gpa(after["institutional_gpa"], 4.000)


class TestHonorsPolicyMissingAtConfer:
    def test_confer_without_covering_policy_rejected(self, api, registrar_headers):
        """PRD §3.7: "Before the degree can post, an honors policy of the
        declaration's program whose closed effective interval contains the
        declaration's `catalog_year` must exist; its absence stops conferral with
        `ERR_HONORS_POLICY_MISSING`."

        Design: Corner/errors/honors_policy_missing_at_confer
        """
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": "BS-HM", "name": "BS HM"},
            honors_policy=None,  # no policy at all
            student_overrides={"student_number": "S-HM", "legal_name": "Hon Miss"},
            enrollment_specs=[{"course_code": "HM3", "term": "2024-FA", "grade": "A"}],
            audit_kinds=("FINAL",),
            walk_to="CLEARED",
        )
        assert sc.application["status"] == "CLEARED"

        res = api.confer_application(sc.application["id"], registrar_headers)
        validate_error(res, ApiErrorId.ERR_HONORS_POLICY_MISSING.value, expected_status=422)

        assert api.get_application(sc.application["id"], registrar_headers).json()["data"]["status"] == "CLEARED"
        diplomas, meta = list_diplomas(application_id=sc.application["id"])
        assert diplomas == []
        assert meta["total_count"] == 0


def _conferred_with_diploma(program_code, student_number, legal_name,
                            diploma_name=None):
    """Full pipeline through conferral; returns the scenario namespace."""
    app_overrides = {"diploma_name": diploma_name} if diploma_name else {}
    return setup_graduation_pipeline(
        program_overrides={"program_code": program_code, "name": program_code},
        honors_policy={**HONORS_POLICY, "honors_gpa_basis": "INSTITUTIONAL",
                       "residency_min_credits": 3},
        student_overrides={"student_number": student_number, "legal_name": legal_name},
        enrollment_specs=[{"course_code": "DP3", "term": "2024-FA", "grade": "A"}],
        audit_kinds=("FINAL",),
        application_overrides=app_overrides,
        walk_to="CONFERRED",
    )


class TestDiplomaStateGuards:
    def test_reissue_requires_revoked_latest_and_revoked_is_terminal(self, api, registrar_headers):
        """PRD §3.7: "`RegistrarStaff` reissues against a `DEGREE_CONFERRED`
        application whose latest diploma — the most recent by `created_at` — is
        `REVOKED`; if the application is not conferred or its latest diploma is
        anything other than `REVOKED`, the reissue is rejected with
        `ERR_DIPLOMA_INVALID_STATE`."
        PRD §3.7: "`REVOKED` is terminal, and any issue or revoke attempted from
        a state that does not allow it is rejected with
        `ERR_DIPLOMA_INVALID_STATE`."

        Design: Corner/state_machines/diploma_state_guards
        """
        sc = _conferred_with_diploma("BS-DG", "S-DG", "Dee Gee")
        diploma = sc.diploma
        assert diploma["status"] == "PENDING"

        # Reissue while the latest diploma is PENDING is rejected.
        res = api.reissue_diploma(
            sc.application["id"],
            {"printed_name": "Premature Reissue", "reason": "attempt before revoke"},
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_DIPLOMA_INVALID_STATE.value, expected_status=409)

        revoked = validate_success(api.revoke_diploma(
            diploma["id"], {"reason": "damage"}, registrar_headers), 200)
        assert revoked["status"] == "REVOKED"

        # Issue after revoke: REVOKED is terminal.
        res = api.issue_diploma(diploma["id"], registrar_headers)
        validate_error(res, ApiErrorId.ERR_DIPLOMA_INVALID_STATE.value, expected_status=409)


class TestDiplomaRevokeReissue:
    def test_revoke_then_reissue_links_corrected_diploma(self, api, registrar_headers):
        """PRD §3.7: "Revocation — the correction path — moves either `PENDING`
        or `ISSUED` → `REVOKED` and records the supplied `revocation_reason`" and
        "The new diploma starts `PENDING`, points its `reissue_of_diploma_id` at
        the revoked predecessor". The request "may carry corrected `printed_name`
        and/or `conferral_date` values".

        Design: Difficulty/compensating_invariant/diploma_revoke_reissue_cardinality_invariant
        """
        sc = _conferred_with_diploma("BS-DP", "S-DP", "Dana Old Name",
                                     diploma_name="Dana Old Name")
        d1 = sc.diploma
        validate_success(api.issue_diploma(d1["id"], registrar_headers), 200)

        revoked = validate_success(api.revoke_diploma(
            d1["id"], {"reason": "name misspelled"}, registrar_headers), 200)
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason"] == "name misspelled"

        d2 = validate_success(api.reissue_diploma(
            sc.application["id"],
            {"printed_name": "Dana Corrected Name",
             "reason": "post-graduation name correction"},
            registrar_headers), 201)
        assert d2["status"] == "PENDING"
        assert d2["reissue_of_diploma_id"] == d1["id"]
        assert d2["printed_name"] == "Dana Corrected Name"

    def test_active_diploma_cardinality_and_recomputed_honors(self, api, registrar_headers):
        """PRD §3.7: "`RegistrarStaff` reissues against a `DEGREE_CONFERRED`
        application whose latest diploma — the most recent by `created_at` — is
        `REVOKED`; if the application is not conferred or its latest diploma is
        anything other than `REVOKED`, the reissue is rejected with
        `ERR_DIPLOMA_INVALID_STATE`."
        PRD §3.7: "The new diploma starts `PENDING`, points its
        `reissue_of_diploma_id` at the revoked predecessor, and — unlike the
        original creation — has its `honors_designation` **recomputed from the
        student's current GPAs** under the same honors rule, so post-conferral
        grade corrections flow through to the corrected diploma."

        After revoke+reissue exactly one active (PENDING or ISSUED) diploma
        remains for the application.

        Design: Difficulty/compensating_invariant/diploma_revoke_reissue_cardinality_invariant
        """
        sc = _conferred_with_diploma("BS-DP2", "S-DP2", "Dana Old Name",
                                     diploma_name="Dana Old Name")
        d1 = sc.diploma
        # GPA 4.000 >= summa_threshold 3.9 with residency met -> SUMMA_CUM_LAUDE.
        assert d1["honors_designation"] == "SUMMA_CUM_LAUDE"
        validate_success(api.issue_diploma(d1["id"], registrar_headers), 200)
        validate_success(api.revoke_diploma(
            d1["id"], {"reason": "name misspelled"}, registrar_headers), 200)

        d2 = validate_success(api.reissue_diploma(
            sc.application["id"],
            {"printed_name": "Dana Corrected Name",
             "reason": "post-graduation name correction"},
            registrar_headers), 201)
        assert d2["honors_designation"] == "SUMMA_CUM_LAUDE"

        diplomas, meta = list_diplomas(application_id=sc.application["id"])
        assert meta["total_count"] == 2
        active = [d for d in diplomas if d["status"] in ("PENDING", "ISSUED")]
        assert [d["id"] for d in active] == [d2["id"]]
        by_id = {d["id"]: d for d in diplomas}
        assert by_id[d1["id"]]["status"] == "REVOKED"
