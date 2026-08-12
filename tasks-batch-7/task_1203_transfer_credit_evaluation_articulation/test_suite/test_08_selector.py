"""Auto-match selector: eligibility filtering and ranking."""
import pytest

from test_helpers import (
    get_success_data,
    api_client,
    TEST_USERS,
    create_transcript_course_payload,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


class TestSelectorPrefersMajorSpecificAgreement:
    def _setup(self):
        """Two ACTIVE agreements for one partner: scope ALL and scope MATH, each
        with an M-101 equivalency; MATH-major student."""
        partner = fixtures.create_partner(name="Select College", code="SE")
        course = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")

        a_all = fixtures.create_agreement(partner["id"], program_scope="ALL")
        fixtures.activate_agreement(a_all["id"])
        eq_all = fixtures.add_equivalency(
            a_all["id"], course["id"], "M-101", external_title="Calc ALL", external_credit_hours=4.0
        )

        a_maj = fixtures.create_agreement(partner["id"], program_scope="MATH")
        fixtures.activate_agreement(a_maj["id"])
        eq_maj = fixtures.add_equivalency(
            a_maj["id"], course["id"], "M-101", external_title="Calc MATH", external_credit_hours=4.0
        )

        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )
        return student, transcript, eq_all, eq_maj

    def test_major_specific_scope_wins(self):
        """PRD §3.3: "Eligible candidates are ranked by a total order that never
        consults identifiers: first, scope specificity — a rule whose agreement is
        scoped to the student's declared major beats an `ALL`-scoped rule".

        Design: Corner/calculations/selector_prefers_major_specific_agreement
        """
        student, transcript, eq_all, eq_maj = self._setup()
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        lines = fixtures.get_evaluation_lines(evaluation["id"])
        assert lines[0]["equivalency_id"] == eq_maj["id"]
        assert lines[0]["equivalency_id"] != eq_all["id"]

    def test_selected_line_becomes_auto_matched(self):
        """PRD §3.4: "a non-empty pool moves it to `AUTO_MATCHED`, stamping
        `equivalency_id` with the winner and `internal_course_id` from the matched
        rule".

        Design: Corner/calculations/selector_prefers_major_specific_agreement
        """
        student, transcript, eq_all, eq_maj = self._setup()
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        lines = fixtures.get_evaluation_lines(evaluation["id"])
        assert lines[0]["status"] == "AUTO_MATCHED"
        assert lines[0]["internal_course_id"] == eq_maj["internal_course_id"]


class TestSelectorExcludesWindowNotCoveringTerm:
    def test_window_not_covering_term_excluded(self):
        """PRD §3.3: "the transcript's `term_completed` falls within the rule's
        closed window, both bounds inclusive" — an equivalency whose window does
        not cover the term is ineligible.
        PRD §3.3: "An empty pool sends the line to `PETITION_REQUIRED`."

        Design: Corner/calculations/selector_excludes_window_not_covering_term
        """
        partner = fixtures.create_partner(name="Window College", code="WC", credit_system="QUARTER")
        course = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        fixtures.add_equivalency(
            agreement["id"], course["id"], "MATH-101", external_title="Old Calc",
            external_credit_hours=4.5, effective_from="2024-08-01", effective_until="2024-12-31",
        )
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[create_transcript_course_payload(
                external_course_code="MATH-101", title="Calc", credit_hours=4.5, grade="B")],
            term_completed="2025-06-15",
        )
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        lines = fixtures.get_evaluation_lines(evaluation["id"])
        assert lines[0]["status"] == "PETITION_REQUIRED"
        assert lines[0]["equivalency_id"] is None
        assert lines[0]["provisional_credits"] is None


class TestSelectorExcludesArchivedInternalCourse:
    def test_archived_course_candidate_excluded(self):
        """PRD §3.3: "the referenced internal course is active" is one of the
        eligibility conditions; "An empty pool sends the line to
        `PETITION_REQUIRED`."
        PRD §3.1: "existing equivalencies and line items that already reference
        the course continue to resolve."

        Design: Corner/calculations/selector_excludes_archived_internal_course
        """
        partner = fixtures.create_partner(name="Archive College", code="AR")
        course = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        equivalency = fixtures.add_equivalency(
            agreement["id"], course["id"], "M-101", external_credit_hours=4.0
        )
        get_success_data(api_client.deactivate_internal_course(course["id"], ADMIN))

        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        lines = fixtures.get_evaluation_lines(evaluation["id"])
        assert lines[0]["status"] == "PETITION_REQUIRED", (
            "sole candidate ineligible: internal course archived"
        )

        stored_eq = get_success_data(api_client.get_course_equivalency(equivalency["id"], EVALUATOR))
        assert stored_eq["status"] == "ACTIVE", (
            "archival of the course does not mutate the equivalency row"
        )
