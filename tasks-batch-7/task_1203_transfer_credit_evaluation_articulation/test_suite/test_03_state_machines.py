"""State machine behavior: initial states, invalid and repeated transitions,
terminal lockdown, cyclic loops, and precondition enforcement."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_student_headers,
    create_transcript_course_payload,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]
EVAL_A = fixtures.EVAL_A
EVAL_B = fixtures.EVAL_B
FAC_1 = fixtures.FAC_1


class TestAgreementSuspendReactivateCycle:
    def test_equivalency_status_rides_the_cycle(self):
        """PRD §3.2: "Suspending an `ACTIVE` agreement moves it to `SUSPENDED` and
        fires a three-link cascade: every equivalency of the agreement in `ACTIVE`
        becomes `INACTIVE`...".
        PRD §3.2: "Reactivation returns a `SUSPENDED` agreement to `ACTIVE` ...
        and restores exactly the equivalency set the suspension inactivated".

        Design: Difficulty/non_linear_state_machine/agreement_suspend_reactivate_cycle
        """
        partner = fixtures.create_partner(name="Cycle College", code="CC")
        course = fixtures.create_course(code="BIO-110", title="Biology", department="BIOL",
                                        gened_tags=["GENED_SCIENCE"])
        agreement = fixtures.create_agreement(partner["id"])
        equivalency = fixtures.add_equivalency(
            agreement["id"], course["id"], "BIO-101", external_credit_hours=4.0
        )
        assert equivalency["status"] == "INACTIVE", "created under DRAFT: INACTIVE"

        fixtures.activate_agreement(agreement["id"])
        eq = get_success_data(api_client.get_course_equivalency(equivalency["id"], ADMIN))
        assert eq["status"] == "ACTIVE"

        get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))
        eq = get_success_data(api_client.get_course_equivalency(equivalency["id"], ADMIN))
        assert eq["status"] == "INACTIVE"

        get_success_data(api_client.reactivate_agreement(agreement["id"], ADMIN))
        ag = fixtures.get_agreement(agreement["id"])
        eq = get_success_data(api_client.get_course_equivalency(equivalency["id"], ADMIN))
        assert ag["status"] == "ACTIVE"
        assert eq["status"] == "ACTIVE", "A->B->A cycle closed, equivalency restored"

    def test_full_cycle_statuses_on_agreement(self):
        """PRD §3.2: "A new agreement begins in `DRAFT`. Activation by a
        `RegistrarAdmin` stamps `activated_at` from the logical clock".
        PRD §3.2: "Suspending an `ACTIVE` agreement moves it to `SUSPENDED`";
        "Reactivation returns a `SUSPENDED` agreement to `ACTIVE`".

        Design: Difficulty/non_linear_state_machine/agreement_suspend_reactivate_cycle
        """
        partner = fixtures.create_partner(name="Cycle College", code="CC")
        agreement = fixtures.create_agreement(partner["id"])
        assert agreement["status"] == "DRAFT"

        activated = fixtures.activate_agreement(agreement["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["activated_at"] is not None

        suspended = get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"

        reactivated = get_success_data(api_client.reactivate_agreement(agreement["id"], ADMIN))
        assert reactivated["status"] == "ACTIVE", "A->B->A cycle closed on the agreement"

    def test_reactivate_from_active_rejected(self):
        """PRD §3.2: "Reactivation returns a `SUSPENDED` agreement to `ACTIVE` —
        provided the logical clock's date is still strictly before `effective_end`"
        — the transition is defined only from SUSPENDED.
        PRD §2.8: "seventh, the invoked transition's from-state precondition
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/agreement_reactivate_from_active_returns_invalid_state
        """
        partner = fixtures.create_partner(name="State College", code="ST")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])

        resp = api_client.reactivate_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        ag = fixtures.get_agreement(agreement["id"])
        assert ag["status"] == "ACTIVE"


class TestEvaluationPostReopenRepostCycle:
    def _setup_posted_single_line(self):
        return fixtures.setup_posted_evaluation(
            course_kwargs={"code": "MATH-150", "credit_hours": 4.0, "department": "MATH"},
            equivalency_kwargs={"external_course_code": "M-101", "external_credit_hours": 4.0},
            transcript_courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )

    def test_reopen_compensates_and_repost_reproduces(self):
        """PRD §3.6: "Every posted line returns to `ADOPTED` with `applied_credits`
        cleared to null, all `RequirementApplication` rows belonging to the
        evaluation are deleted, the previously applied sum is subtracted from the
        student's `total_posted_transfer_credits` — full compensation, per the
        §2.10 invariant — and `applied_credits_total` is zeroed while
        `posted_by_id` and `posted_at` are nulled."

        Design: Difficulty/non_linear_state_machine/evaluation_post_reopen_repost_cycle
        """
        ctx = self._setup_posted_single_line()
        ev_id = ctx["evaluation"]["id"]
        line_id = ctx["lines"][0]["id"]
        student_id = ctx["student"]["id"]

        student = get_success_data(api_client.get_student(student_id, EVALUATOR))
        assert student["total_posted_transfer_credits"] == pytest.approx(4.0, abs=1e-9)

        reopened = get_success_data(api_client.reopen_evaluation(
            ev_id, {"reason": "Student submitted additional coursework"}, EVALUATOR
        ))
        assert reopened["status"] == "IN_REVIEW"
        line = get_success_data(api_client.get_line_item(line_id, EVALUATOR))
        assert line["status"] == "ADOPTED"
        assert line["applied_credits"] is None
        student = get_success_data(api_client.get_student(student_id, EVALUATOR))
        assert student["total_posted_transfer_credits"] == pytest.approx(0.0, abs=1e-9)

        # Second pass through the cycle reproduces the identical outcome.
        fixtures.finalize_evaluation(ev_id, EVAL_A)
        reposted = fixtures.post_evaluation(ev_id, EVAL_B)
        assert reposted["status"] == "POSTED"
        student = get_success_data(api_client.get_student(student_id, EVALUATOR))
        assert student["total_posted_transfer_credits"] == pytest.approx(4.0, abs=1e-9)

    def test_reopen_nulls_posting_attribution(self):
        """PRD §3.6: "`applied_credits_total` is zeroed while `posted_by_id` and
        `posted_at` are nulled."

        Design: Difficulty/non_linear_state_machine/evaluation_post_reopen_repost_cycle
        """
        ctx = self._setup_posted_single_line()
        ev_id = ctx["evaluation"]["id"]

        reopened = get_success_data(api_client.reopen_evaluation(
            ev_id, {"reason": "Recheck requested by student"}, EVALUATOR
        ))
        assert reopened["applied_credits_total"] == pytest.approx(0.0, abs=1e-9)
        assert reopened["posted_by_id"] is None
        assert reopened["posted_at"] is None
        assert reopened["reopen_reason"] == "Recheck requested by student"


class TestTranscriptStateMachine:
    def test_transcript_initial_state_received(self):
        """PRD §3.4: "A fresh transcript is `RECEIVED`."

        Design: Corner/state_machines/transcript_initial_state_received
        """
        partner = fixtures.create_partner(name="Init College", code="IN")
        student = fixtures.create_student(major="MATH")
        course_entry = create_transcript_course_payload(
            external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A"
        )
        transcript = fixtures.create_transcript(student["id"], partner["id"], courses=[course_entry])
        assert transcript["status"] == "RECEIVED"
        assert len(transcript["courses"]) == 1
        stored = transcript["courses"][0]
        assert stored["external_course_code"] == "M-101"
        assert stored["credit_hours"] == pytest.approx(4.0, abs=1e-9)
        assert stored["grade"] == "A"

    def test_transcript_second_verify_rejected(self):
        """PRD §3.4: "Verification stamps `verified_at` and moves it to `VERIFIED`"
        — the verify transition is defined only from `RECEIVED`.
        PRD §2.8: "seventh, the invoked transition's from-state precondition
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/transcript_second_verify_rejected
        """
        partner = fixtures.create_partner(name="Init College", code="IN")
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_transcript(student["id"], partner["id"])

        first = api_client.verify_transcript(transcript["id"], STAFF)
        verified = validate_success(first)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_at"] is not None

        second = api_client.verify_transcript(transcript["id"], STAFF)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_terminal_state_lockdown_transcript_rejected_cannot_verify(self):
        """PRD §3.4: "rejection is possible from either `RECEIVED` or `VERIFIED`,
        records the supplied `reason` in `rejection_reason`, and lands in
        `REJECTED`, which like `EXTRACTED` is terminal."

        Design: Corner/state_machines/terminal_state_lockdown_transcript_rejected_cannot_verify
        """
        partner = fixtures.create_partner(name="Init College", code="IN")
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_transcript(student["id"], partner["id"])
        get_success_data(api_client.reject_transcript(
            transcript["id"], {"reason": "Illegible scan"}, STAFF
        ))

        resp = api_client.verify_transcript(transcript["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        stored = get_success_data(api_client.get_transcript(transcript["id"], STAFF))
        assert stored["status"] == "REJECTED"
        assert stored["rejection_reason"] == "Illegible scan"


class TestEvaluationFinalizePrecondition:
    def test_evaluation_finalize_with_unresolved_lines_rejected(self):
        """PRD §3.6: "Finalization moves an evaluation `IN_REVIEW` → `EVALUATED`
        and is allowed only when every line item sits in `ADOPTED` or `DENIED` —
        any unresolved line rejects the call with `ERR_UNRESOLVED_LINE_ITEMS`
        (HTTP 409)."

        Design: Corner/state_machines/evaluation_finalize_with_unresolved_lines_rejected
        """
        ctx = fixtures.setup_evaluation_in_review(
            course_kwargs={"code": "MATH-150", "credit_hours": 4.0, "department": "MATH"},
            equivalency_kwargs={"external_course_code": "M-101", "external_credit_hours": 4.0},
            transcript_courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )
        # Line stays AUTO_MATCHED — never adopted or denied.
        resp = api_client.finalize_evaluation(ctx["evaluation"]["id"], EVAL_A)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_LINE_ITEMS)
        evaluation = get_success_data(api_client.get_evaluation(ctx["evaluation"]["id"], EVALUATOR))
        assert evaluation["status"] == "IN_REVIEW"


class TestPetitionRepetitionLoop:
    def test_petition_repetition_loop_allowed_after_denial(self):
        """PRD §3.7: "On `DENIED`, the line remains `PETITION_REQUIRED` and the
        re-petition loop stays open — the student may file again once no open
        petition remains."
        PRD §3.7: "at most one open petition — one in `SUBMITTED` or
        `UNDER_REVIEW` — may exist per line item".

        Design: Corner/state_machines/petition_repetition_loop_allowed_after_denial
        """
        ctx = fixtures.setup_denied_petition()
        line = get_success_data(api_client.get_line_item(ctx["line"]["id"], EVALUATOR))
        assert line["status"] == "PETITION_REQUIRED"

        pet2 = fixtures.file_petition(
            ctx["line"]["id"], ctx["course"]["id"], ctx["student"]["id"],
            syllabus_ref="s3://syllabi/v2.pdf",
        )
        assert pet2["status"] == "SUBMITTED", "DENIED first petition does not block re-petition"
        line = get_success_data(api_client.get_line_item(ctx["line"]["id"], EVALUATOR))
        assert line["status"] == "PETITION_REQUIRED"


class TestGuidePublishSupersedesPreviousPublished:
    def test_guide_publish_supersedes_previous_published(self):
        """PRD §3.9: "The publish stamps `published_at`, captures an immutable
        `entries_snapshot` ... and supersedes any other `PUBLISHED` guide for the
        same partner and catalog year into `ARCHIVED`."

        Design: Corner/state_machines/guide_publish_supersedes_previous_published
        """
        partner = fixtures.create_partner(name="Guide College", code="GC")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        g1 = fixtures.create_guide(partner["id"])
        g2 = fixtures.create_guide(partner["id"])
        get_success_data(api_client.publish_transfer_guide(g1["id"], ADMIN))

        published = get_success_data(api_client.publish_transfer_guide(g2["id"], ADMIN))
        assert published["status"] == "PUBLISHED"
        assert published["pinned_agreement_id"] == agreement["id"]

        g1_after = get_success_data(api_client.get_transfer_guide(g1["id"], ADMIN))
        assert g1_after["status"] == "ARCHIVED"
