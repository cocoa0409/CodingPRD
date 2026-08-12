"""Transitive cascades: appeal-overturn depth-3 chain and clock-expiry
depth-3 chain, plus cross-entity post/publish gating."""
import pytest

from test_helpers import (
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
FACULTY = TEST_USERS["faculty_headers"]
EVAL_A = fixtures.EVAL_A
EVAL_B = fixtures.EVAL_B
FAC_1 = fixtures.FAC_1
FAC_2 = fixtures.FAC_2


class TestAppealOverturnCascadesPetitionLineEvaluation:
    def _setup_posted_with_denied_line_and_petition(self):
        """QUARTER partner; no equivalency for ART-210 -> PETITION_REQUIRED.
        Petition DENIED by fac-1; line then DENIED; evaluation POSTED."""
        partner = fixtures.create_partner(name="Art College", code="AC", credit_system="QUARTER")
        course = fixtures.create_course(code="ART-200", title="Sculpture I",
                                        credit_hours=4.0, department="ART")
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[create_transcript_course_payload(
                external_course_code="ART-210", title="Sculpture", credit_hours=4.5, grade="A")],
        )
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        line = fixtures.get_evaluation_lines(evaluation["id"])[0]
        get_success_data(api_client.start_evaluation_review(evaluation["id"], EVALUATOR))

        petition = fixtures.file_petition(line["id"], course["id"], student["id"],
                                          syllabus_ref="s3://syllabi/art210.pdf")
        get_success_data(api_client.start_petition_review(petition["id"], FAC_1))
        fixtures.adjudicate_petition(
            petition["id"], "DENIED", note="Insufficient studio hours documented", headers=FAC_1
        )
        get_success_data(api_client.deny_line_item(
            line["id"], {"reason": "Petition denied by faculty"}, EVALUATOR
        ))
        fixtures.finalize_evaluation(evaluation["id"], EVAL_A)
        fixtures.post_evaluation(evaluation["id"], EVAL_B)
        return {
            "partner": partner, "course": course, "student": student,
            "evaluation": evaluation, "line": line, "petition": petition,
        }

    def test_overturn_cascades_petition_line_evaluation(self):
        """PRD §3.7: "An overturn fires a three-link cascade: the petition moves
        `DENIED` → `APPROVED`; the line item moves to `ADOPTED` — forcibly from
        `DENIED` if the evaluation had already posted, or from `PETITION_REQUIRED`
        otherwise — with `awarded_credits` recomputed under the final variant; and
        if the owning evaluation is `POSTED`, the evaluation itself is reopened to
        `IN_REVIEW` with the full compensation of §3.6 and the appeal-overturn
        reopen marker."

        Design: Difficulty/transitive_cascade/appeal_overturn_cascades_petition_line_evaluation
        """
        ctx = self._setup_posted_with_denied_line_and_petition()
        student_id = ctx["student"]["id"]

        appeal = fixtures.file_appeal(
            ctx["petition"]["id"], student_id,
            grounds="New syllabus evidence provided by department chair",
        )
        get_success_data(api_client.start_appeal_review(appeal["id"], FAC_2))
        get_success_data(api_client.adjudicate_appeal(
            appeal["id"],
            {"decision": "OVERTURNED", "adjudication_note": "New evidence accepted by committee"},
            FAC_2,
        ))

        petition = get_success_data(api_client.get_petition(ctx["petition"]["id"], FACULTY))
        assert petition["status"] == "APPROVED", "link 1: petition DENIED -> APPROVED"

        line = get_success_data(api_client.get_line_item(ctx["line"]["id"], FACULTY))
        assert line["status"] == "ADOPTED", "link 2: line DENIED -> ADOPTED"
        assert line["resolution"] == "PETITION"
        # half-step(4.5 * 2/3 = 3.0) capped by the 4.0-hour course.
        assert line["awarded_credits"] == pytest.approx(3.0, abs=1e-9)

        evaluation = get_success_data(api_client.get_evaluation(ctx["evaluation"]["id"], FACULTY))
        assert evaluation["status"] == "IN_REVIEW", "link 3: POSTED -> IN_REVIEW forced reopen"
        assert evaluation["reopen_reason"] == "APPEAL_OVERTURN"

    def test_overturn_compensation_restores_student_total(self):
        """PRD §3.6: "the previously applied sum is subtracted from the student's
        `total_posted_transfer_credits` — full compensation, per the §2.10
        invariant".

        Design: Difficulty/transitive_cascade/appeal_overturn_cascades_petition_line_evaluation
        """
        ctx = self._setup_posted_with_denied_line_and_petition()
        student_id = ctx["student"]["id"]
        # The single line was DENIED at post, so the post applied 0.0.
        student = get_success_data(api_client.get_student(student_id, FACULTY))
        assert student["total_posted_transfer_credits"] == pytest.approx(0.0, abs=1e-9)

        appeal = fixtures.file_appeal(
            ctx["petition"]["id"], student_id,
            grounds="New syllabus evidence provided by department chair",
        )
        get_success_data(api_client.start_appeal_review(appeal["id"], FAC_2))
        get_success_data(api_client.adjudicate_appeal(
            appeal["id"],
            {"decision": "OVERTURNED", "adjudication_note": "New evidence accepted by committee"},
            FAC_2,
        ))

        student = get_success_data(api_client.get_student(student_id, FACULTY))
        assert student["total_posted_transfer_credits"] == pytest.approx(0.0, abs=1e-9), (
            "reopen removes exactly what the post added (0.0 here)"
        )


class TestClockExpiryCascadesAgreementEquivalencyLine:
    def _setup_draft_evaluation_with_auto_matched_line(self):
        partner = fixtures.create_partner(name="Quarter College", code="QC", credit_system="QUARTER")
        course = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        agreement = fixtures.create_agreement(
            partner["id"], effective_start="2024-08-01", effective_end="2026-05-10"
        )
        equivalency = fixtures.add_equivalency(
            agreement["id"], course["id"], "MATH-101", external_title="Intro Calc",
            external_credit_hours=4.5, activate_first=True,
        )
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[create_transcript_course_payload(
                external_course_code="MATH-101", title="Intro Calc", credit_hours=4.5, grade="B")],
        )
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        line = fixtures.get_evaluation_lines(evaluation["id"])[0]
        assert line["status"] == "AUTO_MATCHED"
        return {
            "partner": partner, "course": course, "agreement": agreement,
            "equivalency": equivalency, "student": student,
            "evaluation": evaluation, "line": line,
        }

    def test_clock_expiry_three_link_cascade(self):
        """PRD §3.2: "Expiry is system-driven: when the logical clock reaches or
        passes `effective_end`, an `ACTIVE` agreement becomes `EXPIRED` with
        `expired_at` stamped and the same three-link cascade as suspension".
        PRD §3.2: "each line item in `AUTO_MATCHED` whose `equivalency_id`
        references one of those equivalencies — but only while its owning
        evaluation is still `DRAFT` or `IN_REVIEW` — flips to `PETITION_REQUIRED`
        with its `equivalency_id`, `internal_course_id`, and `provisional_credits`
        all cleared to null".

        Design: Difficulty/transitive_cascade/clock_expiry_cascades_agreement_equivalency_line
        """
        ctx = self._setup_draft_evaluation_with_auto_matched_line()

        get_success_data(api_client.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"}, ADMIN))

        agreement = fixtures.get_agreement(ctx["agreement"]["id"])
        assert agreement["status"] == "EXPIRED", "link 1: half-open window end reached"
        assert agreement["expired_at"] is not None

        equivalency = get_success_data(
            api_client.get_course_equivalency(ctx["equivalency"]["id"], ADMIN)
        )
        assert equivalency["status"] == "INACTIVE", "link 2: equivalency cascade"

        line = get_success_data(api_client.get_line_item(ctx["line"]["id"], ADMIN))
        assert line["status"] == "PETITION_REQUIRED", "link 3: open line flipped"
        assert line["equivalency_id"] is None
        assert line["internal_course_id"] is None
        assert line["provisional_credits"] is None

    def test_clock_expiry_recomputes_evaluation_provisional_total(self):
        """PRD §3.2: "each affected evaluation recomputes its
        `provisional_credits_total` and `open_line_count`."

        Design: Difficulty/transitive_cascade/clock_expiry_cascades_agreement_equivalency_line
        """
        ctx = self._setup_draft_evaluation_with_auto_matched_line()
        evaluation = get_success_data(api_client.get_evaluation(ctx["evaluation"]["id"], ADMIN))
        assert evaluation["provisional_credits_total"] == pytest.approx(3.4, abs=1e-9)

        get_success_data(api_client.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"}, ADMIN))

        evaluation = get_success_data(api_client.get_evaluation(ctx["evaluation"]["id"], ADMIN))
        assert evaluation["provisional_credits_total"] == pytest.approx(0.0, abs=1e-9), (
            "the only provisional line was cleared; total recomputed to 0"
        )
        assert evaluation["open_line_count"] == 1


class TestPostBlockedWhenEquivalencyAgreementSuspended:
    def _setup_evaluated_then_suspend(self):
        partner = fixtures.create_partner(name="Quarter College", code="QC", credit_system="QUARTER")
        course = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.add_equivalency(
            agreement["id"], course["id"], "MATH-101", external_title="Intro Calc",
            external_credit_hours=4.5, activate_first=True,
        )
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[create_transcript_course_payload(
                external_course_code="MATH-101", title="Intro Calc", credit_hours=4.5, grade="A")],
        )
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        line = fixtures.get_evaluation_lines(evaluation["id"])[0]
        get_success_data(api_client.start_evaluation_review(evaluation["id"], EVALUATOR))
        get_success_data(api_client.adopt_line_item(line["id"], {}, EVALUATOR))
        fixtures.finalize_evaluation(evaluation["id"], EVAL_A)
        get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))
        return {"evaluation": evaluation, "agreement": agreement}

    def test_post_blocked_when_equivalency_agreement_suspended(self):
        """PRD §3.6: "Posting also demands that every adopted line still carrying
        an `equivalency_id` references an equivalency whose agreement is currently
        `ACTIVE`; a single lapsed agreement blocks the post with
        `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/post_blocked_when_equivalency_agreement_suspended
        """
        ctx = self._setup_evaluated_then_suspend()
        resp = api_client.post_evaluation(ctx["evaluation"]["id"], EVAL_B)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_blocked_post_leaves_evaluation_unevaluated_mutation_free(self):
        """PRD §3.6: "a single lapsed agreement blocks the post with
        `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)" — the transition does not occur.

        Design: Difficulty/cross_entity_state_dependency/post_blocked_when_equivalency_agreement_suspended
        """
        ctx = self._setup_evaluated_then_suspend()
        api_client.post_evaluation(ctx["evaluation"]["id"], EVAL_B)
        evaluation = get_success_data(api_client.get_evaluation(ctx["evaluation"]["id"], EVALUATOR))
        assert evaluation["status"] == "EVALUATED", "no partial mutation on rejected post"
        assert evaluation["posted_by_id"] is None
        assert evaluation["posted_at"] is None


class TestGuidePublishBlockedWithoutActiveAgreement:
    def test_guide_publish_blocked_without_active_agreement(self):
        """PRD §3.9: "Publishing requires that at least one agreement for that
        partner currently be `ACTIVE` — otherwise the publish fails with
        `ERR_GUIDE_NO_ACTIVE_AGREEMENT` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/guide_publish_blocked_without_active_agreement
        """
        partner = fixtures.create_partner(name="Guide College", code="GC")
        fixtures.create_agreement(partner["id"])  # stays DRAFT, never activated
        guide = fixtures.create_guide(partner["id"])

        resp = api_client.publish_transfer_guide(guide["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_GUIDE_NO_ACTIVE_AGREEMENT)

    def test_blocked_publish_leaves_guide_draft(self):
        """PRD §3.9: "A `RegistrarAdmin` drafts one with `partner_institution_id`
        and `catalog_year`; it begins in `DRAFT`." — a failed publish performs no
        transition.

        Design: Difficulty/cross_entity_state_dependency/guide_publish_blocked_without_active_agreement
        """
        partner = fixtures.create_partner(name="Guide College", code="GC")
        fixtures.create_agreement(partner["id"])
        guide = fixtures.create_guide(partner["id"])

        api_client.publish_transfer_guide(guide["id"], ADMIN)
        stored = get_success_data(api_client.get_transfer_guide(guide["id"], ADMIN))
        assert stored["status"] == "DRAFT"
        assert stored["pinned_agreement_id"] is None
