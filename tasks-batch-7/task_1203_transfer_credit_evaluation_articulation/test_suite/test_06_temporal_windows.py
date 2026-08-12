"""Temporal window semantics: half-open agreement windows (adjacency allowed)
vs closed equivalency windows (touching endpoints overlap), and the
inclusive grade-point boundary."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    create_transcript_course_payload,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


class TestAgreementWindowsHalfOpenAdjacencyAllowed:
    def test_adjacent_agreement_window_allowed(self):
        """PRD §3.2: "windows that merely touch — the new start equal to an
        existing end, or the new end equal to an existing start — are allowed,
        because the half-open convention leaves no shared date."

        Design: Difficulty/resource_temporal_overlap/agreement_windows_half_open_adjacency_allowed
        """
        partner = fixtures.create_partner(name="Adjacent College", code="AJ")
        fixtures.create_agreement(
            partner["id"], effective_start="2024-08-01", effective_end="2027-07-31"
        )

        resp = api_client.create_articulation_agreement(
            {
                "partner_institution_id": partner["id"],
                "program_scope": "ALL",
                "effective_start": "2027-07-31",
                "effective_end": "2028-07-31",
            },
            ADMIN,
        )
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "DRAFT"

    def test_overlapping_agreement_window_rejected(self):
        """PRD §3.2: "the new window must not overlap any existing agreement for
        the same partner and scope whose status is `DRAFT`, `ACTIVE`, or
        `SUSPENDED` ... A violation is rejected with
        `ERR_AGREEMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/agreement_windows_half_open_adjacency_allowed
        """
        partner = fixtures.create_partner(name="Adjacent College", code="AJ")
        fixtures.create_agreement(
            partner["id"], effective_start="2024-08-01", effective_end="2027-07-31"
        )

        resp = api_client.create_articulation_agreement(
            {
                "partner_institution_id": partner["id"],
                "program_scope": "ALL",
                "effective_start": "2027-07-30",
                "effective_end": "2028-07-31",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)


class TestEquivalencyWindowsClosedAdjacencyRejected:
    def _setup(self):
        partner = fixtures.create_partner(name="Closed College", code="CL", credit_system="QUARTER")
        course = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        return partner, course, agreement

    def test_touching_equivalency_windows_overlap(self):
        """PRD §3.3: "Within one agreement, the closed windows of rules sharing
        the same `external_course_code` must be strictly disjoint, and here
        touching endpoints **do** count as overlap — a new rule whose
        `effective_from` equals a sibling's `effective_until` is rejected with
        `ERR_EQUIVALENCY_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/equivalency_windows_closed_adjacency_rejected
        """
        partner, course, agreement = self._setup()
        fixtures.add_equivalency(
            agreement["id"], course["id"], "MATH-101", external_title="Calc v1",
            external_credit_hours=4.5, effective_from="2024-08-01", effective_until="2025-07-31",
        )
        current = fixtures.get_agreement(agreement["id"])

        resp = api_client.create_course_equivalency(
            agreement["id"],
            {
                "internal_course_id": course["id"],
                "external_course_code": "MATH-101",
                "external_title": "Calc v2",
                "external_credit_hours": 4.5,
                "effective_from": "2025-07-31",
                "effective_until": "2026-07-31",
                "expected_agreement_version": current["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_EQUIVALENCY_WINDOW_OVERLAP)

    def test_strictly_later_equivalency_window_allowed(self):
        """PRD §3.3: "the closed windows of rules sharing the same
        `external_course_code` must be strictly disjoint" — a start strictly after
        the sibling's inclusive end is disjoint and allowed.

        Design: Difficulty/resource_temporal_overlap/equivalency_windows_closed_adjacency_rejected
        """
        partner, course, agreement = self._setup()
        fixtures.add_equivalency(
            agreement["id"], course["id"], "MATH-101", external_title="Calc v1",
            external_credit_hours=4.5, effective_from="2024-08-01", effective_until="2025-07-31",
        )
        current = fixtures.get_agreement(agreement["id"])

        resp = api_client.create_course_equivalency(
            agreement["id"],
            {
                "internal_course_id": course["id"],
                "external_course_code": "MATH-101",
                "external_title": "Calc v3",
                "external_credit_hours": 4.5,
                "effective_from": "2025-08-01",
                "effective_until": "2026-07-31",
                "expected_agreement_version": current["version"],
            },
            ADMIN,
        )
        validate_success(resp, expected_status=201)


class TestGradePointsTwoZeroInclusiveBoundary:
    def _setup(self):
        partner = fixtures.create_partner(name="Quarter College", code="QC", credit_system="QUARTER")
        course = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        fixtures.add_equivalency(agreement["id"], course["id"], "MATH-101",
                                 external_title="Calc 1", external_credit_hours=4.5)
        fixtures.add_equivalency(agreement["id"], course["id"], "MATH-102",
                                 external_title="Calc 2", external_credit_hours=4.5)
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[
                create_transcript_course_payload(external_course_code="MATH-101", title="Calc 1",
                                                 credit_hours=4.5, grade="C"),
                create_transcript_course_payload(external_course_code="MATH-102", title="Calc 2",
                                                 credit_hours=4.5, grade="C-"),
            ],
        )
        return student, transcript

    def test_grade_c_exactly_meets_threshold(self):
        """PRD §3.4: "A grade is transferable when its points are at least 2.0 —
        a C exactly meets the threshold; a C- does not."
        PRD §3.4: "C converts to 2.0".

        Design: Difficulty/boundary_precision_check/grade_points_two_zero_inclusive_boundary
        """
        student, transcript = self._setup()
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        lines = fixtures.get_evaluation_lines(evaluation["id"])
        by_code = {l["external_course_code"]: l for l in lines}

        line_c = by_code["MATH-101"]
        assert line_c["grade_points"] == pytest.approx(2.0, abs=1e-9)
        assert line_c["status"] == "AUTO_MATCHED", "grade_points == 2.0 is transferable (inclusive)"

    def test_grade_c_minus_below_threshold_auto_denied(self):
        """PRD §3.4: "A non-transferable line goes straight to `DENIED` with
        `resolution` set to `AUTO_GRADE` and `denial_reason` recorded as the
        below-threshold marker."
        PRD §3.4: "A grade is transferable when its points are at least 2.0 — a
        C exactly meets the threshold; a C- does not."

        Design: Difficulty/boundary_precision_check/grade_points_two_zero_inclusive_boundary
        """
        student, transcript = self._setup()
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        lines = fixtures.get_evaluation_lines(evaluation["id"])
        by_code = {l["external_course_code"]: l for l in lines}

        line_cm = by_code["MATH-102"]
        assert line_cm["grade_points"] == pytest.approx(1.7, abs=1e-9)
        assert line_cm["status"] == "DENIED"
        assert line_cm["resolution"] == "AUTO_GRADE"
