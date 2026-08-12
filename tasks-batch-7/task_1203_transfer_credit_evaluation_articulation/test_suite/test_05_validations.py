"""Validation pipeline, cross-entity gates, business constraints, and
segregation-of-duties errors."""
import pytest

from test_helpers import (
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_student_headers,
    create_transcript_course_payload,
    create_transcript_payload,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]
EVAL_A = fixtures.EVAL_A
EVAL_B = fixtures.EVAL_B
FAC_1 = fixtures.FAC_1


class TestAuthAndSchemaValidation:
    def test_missing_auth_headers_returns_400(self):
        """PRD §2.1: "A request with either header missing or empty is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        fixtures.create_partner(name="Auth College", code="AU")
        resp = api_client.list_partner_institutions(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_invalid_credit_system_enum_returns_invalid_request(self):
        """PRD §3.1: "the `credit_system` in which that partner's credits are
        denominated — exactly one of `SEMESTER` or `QUARTER`."
        PRD §2.8: "third, request-body schema — required fields present, enum
        values valid, ... (`ERR_INVALID_REQUEST`)".

        Design: Corner/validations/invalid_credit_system_enum_returns_invalid_request
        """
        fixtures.create_partner(name="Valid College", code="VA")
        resp = api_client.create_partner_institution(
            {"name": "Trimester College", "institution_code": "TR", "credit_system": "TRIMESTER"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_agreement_inverted_date_range_returns_invalid_request(self):
        """PRD §3.2: "a half-open effective window from `effective_start`
        (inclusive) to `effective_end` (exclusive, and strictly after the start)."
        PRD §2.8: "third, request-body schema — required fields present, enum
        values valid, date ranges correctly ordered, numeric domains respected
        (`ERR_INVALID_REQUEST`)".

        Design: Corner/validations/agreement_inverted_date_range_returns_invalid_request
        """
        partner = fixtures.create_partner(name="Date College", code="DA")
        resp = api_client.create_articulation_agreement(
            {
                "partner_institution_id": partner["id"],
                "program_scope": "ALL",
                "effective_start": "2027-07-31",
                "effective_end": "2024-08-01",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_internal_course_missing_course_code_returns_invalid_request(self):
        """PRD §2.8: "third, request-body schema — required fields present, enum
        values valid, date ranges correctly ordered, numeric domains respected
        (`ERR_INVALID_REQUEST`)".
        PRD §3.1: "each created with a unique `course_code`, a `title`, its
        `credit_hours` ... a `level` ... and the owning `department` code."

        Design: Corner/entities/internal_course_missing_course_code_returns_invalid_request
        """
        fixtures.create_course(code="MATH-150")
        resp = api_client.create_internal_course(
            {"title": "No Code", "credit_hours": 3.0, "level": "LOWER", "department": "ENGL"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_transcript_body_fk_unknown_student_returns_not_found(self):
        """PRD §2.8: "fourth, existence of every path identifier and every body
        foreign key (`ERR_NOT_FOUND`)".

        Design: Corner/validations/transcript_body_fk_unknown_student_returns_not_found
        """
        partner = fixtures.create_partner(name="FK College", code="FK")
        payload = create_transcript_payload(
            NON_EXISTENT_UUID, partner["id"], term_completed="2025-06-15", courses=[]
        )
        resp = api_client.create_transcript(payload, STAFF)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestOccGuards:
    def test_equivalency_create_stale_agreement_version_returns_412(self):
        """PRD §2.7: "Creating a course equivalency under an agreement requires
        `expected_agreement_version` in the request body, carrying the version of
        the agreement the client last observed. ... A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/equivalency_create_stale_agreement_version_returns_412
        """
        partner = fixtures.create_partner(name="OCC College", code="OC")
        course = fixtures.create_course(code="MATH-150")
        agreement = fixtures.create_agreement(partner["id"])
        stale_version = agreement["version"] - 1

        resp = api_client.create_course_equivalency(
            agreement["id"],
            {
                "internal_course_id": course["id"],
                "external_course_code": "M-101",
                "external_title": "Calc",
                "external_credit_hours": 4.0,
                "effective_from": "2024-08-01",
                "effective_until": "2027-07-31",
                "expected_agreement_version": stale_version,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_patch_student_version_conflict_returns_412(self):
        """PRD §2.7: "Updating a student profile requires
        `expected_student_version` in the request body, matching the student's
        current `version`. A mismatch — for example because a posting or reopening
        cascade advanced the student's credit totals after the client last read
        the record — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/patch_student_version_conflict_returns_412
        """
        student = fixtures.create_student(major="MATH")
        observed_version = student["version"]

        first = api_client.patch_student(
            student["id"],
            {"declared_major": "HIST", "expected_student_version": observed_version},
            ADMIN,
        )
        updated = get_success_data(first)
        assert updated["version"] == observed_version + 1
        assert updated["declared_major"] == "HIST"

        second = api_client.patch_student(
            student["id"],
            {"declared_major": "ENGL", "expected_student_version": observed_version},
            ADMIN,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)
        stored = get_success_data(api_client.get_student(student["id"], ADMIN))
        assert stored["declared_major"] == "HIST", "stale patch performs no mutation"


class TestOwnership:
    def test_student_cannot_petition_other_students_line(self):
        """PRD §2.1: "A `Student` acting on a resource owned by a different
        student is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) — this guards
        petition creation, appeal creation, prior-learning submission, and a
        student's reads of their own resources."

        Design: Corner/validations/student_cannot_petition_other_students_line
        """
        ctx = fixtures.setup_petition_required_line()
        other_student = fixtures.create_student(major="HIST")

        resp = api_client.create_petition(
            {
                "line_item_id": ctx["line"]["id"],
                "proposed_internal_course_id": ctx["course"]["id"],
                "syllabus_ref": "s3://syllabi/art210.pdf",
            },
            make_student_headers(other_student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestEvaluationCreationGates:
    def test_evaluation_student_mismatch_returns_error(self):
        """PRD §3.4: "the supplied `student_id` must equal the transcript's own
        student, failing with `ERR_TRANSCRIPT_STUDENT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/evaluation_student_mismatch_returns_error
        """
        partner = fixtures.create_partner(name="Mismatch College", code="MM")
        student_a = fixtures.create_student(major="MATH")
        student_b = fixtures.create_student(major="HIST")
        transcript = fixtures.create_verified_transcript(
            student_a["id"], partner["id"], courses=[]
        )

        resp = api_client.create_evaluation(
            {"student_id": student_b["id"], "transcript_id": transcript["id"]}, EVALUATOR
        )
        validate_error(resp, ApiErrorId.ERR_TRANSCRIPT_STUDENT_MISMATCH)

    def test_evaluation_on_unverified_transcript_returns_not_verified(self):
        """PRD §3.4: "the transcript must be in `VERIFIED`, failing with
        `ERR_TRANSCRIPT_NOT_VERIFIED` (HTTP 409)".

        Design: Corner/validations/evaluation_on_unverified_transcript_returns_not_verified
        """
        partner = fixtures.create_partner(name="Verify College", code="VE")
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_transcript(student["id"], partner["id"], courses=[])

        resp = api_client.create_evaluation(
            {"student_id": student["id"], "transcript_id": transcript["id"]}, EVALUATOR
        )
        validate_error(resp, ApiErrorId.ERR_TRANSCRIPT_NOT_VERIFIED)

    def test_duplicate_evaluation_for_transcript_returns_duplicate(self):
        """PRD §3.4: "at most one evaluation may ever exist per transcript, and
        this uniqueness check is deliberately evaluated before the
        transcript-state check — so once the transcript has moved to `EXTRACTED`,
        a second attempt still surfaces `ERR_DUPLICATE_EVALUATION` (HTTP 409)
        rather than a state error".

        Design: Corner/validations/duplicate_evaluation_for_transcript_returns_duplicate
        """
        partner = fixtures.create_partner(name="Dup College", code="DU")
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(student["id"], partner["id"], courses=[])
        fixtures.create_evaluation(student["id"], transcript["id"])
        # Transcript is now EXTRACTED; uniqueness still fires first.
        stored = get_success_data(api_client.get_transcript(transcript["id"], STAFF))
        assert stored["status"] == "EXTRACTED"

        resp = api_client.create_evaluation(
            {"student_id": student["id"], "transcript_id": transcript["id"]}, EVALUATOR
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EVALUATION)


class TestLineItemOperationGates:
    def test_line_adopt_while_evaluation_draft_returns_not_in_review(self):
        """PRD §3.5: "both adopt and deny require the line to currently be
        `AUTO_MATCHED` or `PETITION_REQUIRED` (otherwise `ERR_INVALID_STATE`) and,
        evaluated after that line-state check, the enclosing evaluation to be
        `IN_REVIEW` (otherwise `ERR_EVALUATION_NOT_IN_REVIEW`, HTTP 409)."

        Design: Corner/errors/line_adopt_while_evaluation_draft_returns_not_in_review
        """
        ctx = fixtures.setup_active_agreement_with_equivalency(
            course_kwargs={"code": "MATH-150", "credit_hours": 4.0, "department": "MATH"},
            equivalency_kwargs={"external_course_code": "M-101", "external_credit_hours": 4.0},
        )
        partner, course, agreement, equivalency = ctx
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        line = fixtures.get_evaluation_lines(evaluation["id"])[0]
        assert line["status"] == "AUTO_MATCHED"

        resp = api_client.adopt_line_item(line["id"], {}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_IN_REVIEW)
        stored = get_success_data(api_client.get_line_item(line["id"], EVALUATOR))
        assert stored["status"] == "AUTO_MATCHED"


class TestPetitionGates:
    def test_petition_on_auto_matched_line_returns_not_petitionable(self):
        """PRD §3.7: "Petitionable lines are exactly those in `PETITION_REQUIRED`
        or `DENIED` whose evaluation is `IN_REVIEW` or `POSTED`; anything else is
        rejected with `ERR_LINE_ITEM_NOT_PETITIONABLE` (HTTP 409)."

        Design: Corner/validations/petition_on_auto_matched_line_returns_not_petitionable
        """
        ctx = fixtures.setup_evaluation_in_review(
            course_kwargs={"code": "MATH-150", "credit_hours": 4.0, "department": "MATH"},
            equivalency_kwargs={"external_course_code": "M-101", "external_credit_hours": 4.0},
            transcript_courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )
        line = ctx["lines"][0]
        assert line["status"] == "AUTO_MATCHED"

        resp = api_client.create_petition(
            {
                "line_item_id": line["id"],
                "proposed_internal_course_id": ctx["course"]["id"],
                "syllabus_ref": "s3://syllabi/m101.pdf",
            },
            make_student_headers(ctx["student"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LINE_ITEM_NOT_PETITIONABLE)

    def test_duplicate_open_petition_returns_already_open(self):
        """PRD §3.7: "at most one open petition — one in `SUBMITTED` or
        `UNDER_REVIEW` — may exist per line item, with a duplicate rejected as
        `ERR_PETITION_ALREADY_OPEN` (HTTP 409)".

        Design: Corner/validations/duplicate_open_petition_returns_already_open
        """
        ctx = fixtures.setup_petition_required_line()
        fixtures.file_petition(
            ctx["line"]["id"], ctx["course"]["id"], ctx["student"]["id"],
            syllabus_ref="s3://syllabi/v1.pdf",
        )

        resp = api_client.create_petition(
            {
                "line_item_id": ctx["line"]["id"],
                "proposed_internal_course_id": ctx["course"]["id"],
                "syllabus_ref": "s3://syllabi/v2.pdf",
            },
            make_student_headers(ctx["student"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PETITION_ALREADY_OPEN)

    def test_petition_with_archived_course_returns_course_inactive(self):
        """PRD §3.1: "archived courses reject every **new** reference — from
        equivalency creation, petition filing, or a petition adjudicator's
        override — with `ERR_COURSE_INACTIVE` (HTTP 422)".

        Design: Corner/validations/petition_with_archived_course_returns_course_inactive
        """
        ctx = fixtures.setup_petition_required_line()
        get_success_data(api_client.deactivate_internal_course(ctx["course"]["id"], ADMIN))

        resp = api_client.create_petition(
            {
                "line_item_id": ctx["line"]["id"],
                "proposed_internal_course_id": ctx["course"]["id"],
                "syllabus_ref": "s3://syllabi/art210.pdf",
            },
            make_student_headers(ctx["student"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COURSE_INACTIVE)

    def test_petition_adjudicate_before_review_returns_not_under_review(self):
        """PRD §3.7: "Adjudication takes a `decision` and an `adjudication_note`
        of at least ten characters, and is only valid while the petition is
        `UNDER_REVIEW` — otherwise `ERR_PETITION_NOT_UNDER_REVIEW` (HTTP 409)."

        Design: Corner/validations/petition_adjudicate_before_review_returns_not_under_review
        """
        ctx = fixtures.setup_petition_required_line()
        petition = fixtures.file_petition(
            ctx["line"]["id"], ctx["course"]["id"], ctx["student"]["id"],
            syllabus_ref="s3://syllabi/v1.pdf",
        )

        resp = api_client.adjudicate_petition(
            petition["id"],
            {"decision": "APPROVED", "adjudication_note": "Approved on the merits"},
            FAC_1,
        )
        validate_error(resp, ApiErrorId.ERR_PETITION_NOT_UNDER_REVIEW)


class TestAppealGates:
    def test_appeal_on_submitted_petition_returns_not_fileable(self):
        """PRD §3.7: "Filing an appeal requires the petition to be `DENIED`
        (`ERR_APPEAL_NOT_FILEABLE`, HTTP 409)".

        Design: Corner/validations/appeal_on_submitted_petition_returns_not_fileable
        """
        ctx = fixtures.setup_petition_required_line()
        petition = fixtures.file_petition(
            ctx["line"]["id"], ctx["course"]["id"], ctx["student"]["id"],
            syllabus_ref="s3://syllabi/v1.pdf",
        )

        resp = api_client.create_appeal(
            {"petition_id": petition["id"], "grounds": "Premature appeal before any decision"},
            make_student_headers(ctx["student"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_FILEABLE)

    def test_second_appeal_within_window_returns_already_exists(self):
        """PRD §3.7: "tolerates no second appeal per petition
        (`ERR_APPEAL_ALREADY_EXISTS`, HTTP 409)".

        Design: Corner/errors/second_appeal_within_window_returns_already_exists
        """
        ctx = fixtures.setup_denied_petition()
        fixtures.file_appeal(
            ctx["petition"]["id"], ctx["student"]["id"],
            grounds="First appeal, timely and complete",
        )

        resp = api_client.create_appeal(
            {
                "petition_id": ctx["petition"]["id"],
                "grounds": "Second appeal while first is pending",
            },
            make_student_headers(ctx["student"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_EXISTS)

    def test_appeal_review_by_same_adjudicator_returns_conflict(self):
        """PRD §3.7: "Starting review binds a reviewer — who must not be the
        faculty member whose identity sits in the petition's `adjudicator_id`; a
        self-review attempt is rejected with `ERR_APPEAL_ADJUDICATOR_CONFLICT`
        (HTTP 403)".

        Design: Corner/validations/appeal_review_by_same_adjudicator_returns_conflict
        """
        ctx = fixtures.setup_denied_petition()
        appeal = fixtures.file_appeal(
            ctx["petition"]["id"], ctx["student"]["id"],
            grounds="Disagreement with the contact-hour reading",
        )

        resp = api_client.start_appeal_review(appeal["id"], FAC_1)
        validate_error(resp, ApiErrorId.ERR_APPEAL_ADJUDICATOR_CONFLICT)
        stored = get_success_data(api_client.get_appeal(appeal["id"], EVALUATOR))
        assert stored["status"] == "FILED"


class TestPlaGates:
    def test_pla_verify_exceeds_claimed_returns_error(self):
        """PRD §3.8: "A `TransferEvaluator` then verifies it, supplying
        `verified_credits` no greater than the claim — an over-claim verification
        is rejected with `ERR_VERIFIED_EXCEEDS_CLAIMED` (HTTP 422)".

        Design: Corner/validations/pla_verify_exceeds_claimed_returns_error
        """
        student = fixtures.create_student(major="HIST")
        pla = fixtures.create_pla(student["id"], claimed_credits=4.0, source_type="CLEP")

        resp = api_client.verify_pla(pla["id"], {"verified_credits": 6.0}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_VERIFIED_EXCEEDS_CLAIMED)
        stored = get_success_data(api_client.get_pla(pla["id"], EVALUATOR))
        assert stored["status"] == "SUBMITTED"


class TestAmendmentGates:
    def test_second_draft_amendment_returns_amendment_exists(self):
        """PRD §3.2: "At most one `DRAFT` amendment may exist per agreement at a
        time; a second attempt is rejected with `ERR_AMENDMENT_EXISTS` (HTTP 409)."
        PRD §3.2: "Creating an amendment against an existing agreement spawns a
        new agreement in `DRAFT` that inherits the partner and `program_scope` of
        the amended record, records the lineage in the new agreement's
        `amends_agreement_id`".

        Design: Corner/validations/second_draft_amendment_returns_amendment_exists
        """
        partner = fixtures.create_partner(name="Amend College", code="AM")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        amendment = get_success_data(api_client.create_amendment(
            agreement["id"],
            {"effective_start": "2027-07-31", "effective_end": "2029-07-31"},
            ADMIN,
        ))
        assert amendment["status"] == "DRAFT"
        assert amendment["amends_agreement_id"] == agreement["id"]
        assert amendment["partner_institution_id"] == partner["id"]
        assert amendment["program_scope"] == agreement["program_scope"]

        resp = api_client.create_amendment(
            agreement["id"],
            {"effective_start": "2027-07-31", "effective_end": "2029-07-31"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_EXISTS)


class TestSegregationOfDuties:
    def test_post_by_same_evaluator_returns_sod_error(self):
        """PRD §3.6: "Posting is the fiscal act, and it is maker-checker
        segregated: the posting evaluator's header identity must differ from
        `evaluated_by_id`, failing with `ERR_POSTER_IS_EVALUATOR` (HTTP 403) —
        this segregation check is the last gate evaluated."

        Design: Corner/validations/post_by_same_evaluator_returns_sod_error
        """
        ctx = fixtures.setup_evaluation_in_review(
            course_kwargs={"code": "MATH-150", "credit_hours": 4.0, "department": "MATH"},
            equivalency_kwargs={"external_course_code": "M-101", "external_credit_hours": 4.0},
            transcript_courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )
        fixtures.adopt_all_lines(ctx["evaluation"]["id"], ctx["lines"])
        fixtures.finalize_evaluation(ctx["evaluation"]["id"], EVAL_A)

        resp = api_client.post_evaluation(ctx["evaluation"]["id"], EVAL_A)
        validate_error(resp, ApiErrorId.ERR_POSTER_IS_EVALUATOR)
        evaluation = get_success_data(api_client.get_evaluation(ctx["evaluation"]["id"], EVALUATOR))
        assert evaluation["status"] == "EVALUATED"

    def test_post_by_different_evaluator_succeeds(self):
        """PRD §3.6: "the posting evaluator's header identity must differ from
        `evaluated_by_id`" — the check is on identity, not role.

        Design: Corner/validations/post_by_same_evaluator_returns_sod_error
        """
        ctx = fixtures.setup_evaluation_in_review(
            course_kwargs={"code": "MATH-150", "credit_hours": 4.0, "department": "MATH"},
            equivalency_kwargs={"external_course_code": "M-101", "external_credit_hours": 4.0},
            transcript_courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )
        fixtures.adopt_all_lines(ctx["evaluation"]["id"], ctx["lines"])
        fixtures.finalize_evaluation(ctx["evaluation"]["id"], EVAL_A)

        posted = get_success_data(api_client.post_evaluation(ctx["evaluation"]["id"], EVAL_B))
        assert posted["status"] == "POSTED"
        assert posted["evaluated_by_id"] == "eval-a"
        assert posted["posted_by_id"] == "eval-b"


class TestPriorityPairValidationConflict:
    def test_pla_credit_state_precondition_beats_cap(self):
        """PRD §2.8: "seventh, the invoked transition's from-state precondition
        (`ERR_INVALID_STATE`). Endpoint-specific cross-entity and business rules
        then run in the relative order documented alongside each workflow in §3".
        PRD §3.8: "`CREDITED` and `REJECTED` are terminal."

        Design: Difficulty/priority_pair_validation_conflict/pla_credit_state_precondition_beats_cap
        """
        student, pla = fixtures.setup_student_with_credited_pla(credits=24.0)
        # Re-crediting a CREDITED (terminal) PLA violates the from-state rule
        # AND would breach the 30.0 cap (24 + 24 = 48); the state error wins.
        resp = api_client.credit_pla(pla["id"], EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        stored_student = get_success_data(api_client.get_student(student["id"], EVALUATOR))
        assert stored_student["total_posted_pla_credits"] == pytest.approx(24.0, abs=1e-9), (
            "no mutation on rejection"
        )

    def test_pla_credit_rejection_preserves_status(self):
        """PRD §3.8: "`CREDITED` and `REJECTED` are terminal." — a rejected
        re-credit leaves the assessment CREDITED.

        Design: Difficulty/priority_pair_validation_conflict/pla_credit_state_precondition_beats_cap
        """
        student, pla = fixtures.setup_student_with_credited_pla(credits=24.0)
        api_client.credit_pla(pla["id"], EVALUATOR)
        stored = get_success_data(api_client.get_pla(pla["id"], EVALUATOR))
        assert stored["status"] == "CREDITED"

    def test_appeal_window_temporal_beats_duplicate_constraint(self):
        """PRD §2.8: "Endpoint-specific cross-entity and business rules then run
        in the relative order documented alongside each workflow in §3".
        PRD §3.7: "requires the logical clock to be no later than thirty days
        after the petition's `decided_at` — the boundary day itself is still
        timely, after which filing fails with `ERR_APPEAL_WINDOW_EXPIRED`
        (HTTP 422) — and tolerates no second appeal per petition
        (`ERR_APPEAL_ALREADY_EXISTS`, HTTP 409)" — the window rule is documented
        before the uniqueness rule.

        Design: Difficulty/priority_pair_validation_conflict/appeal_window_temporal_beats_duplicate_constraint
        """
        ctx = fixtures.setup_denied_petition()
        student_id = ctx["student"]["id"]
        # Default clock is 2026-05-01; petition denied at that time.
        get_success_data(api_client.set_clock({"to_iso8601": "2026-05-11T00:00:00Z"}, ADMIN))
        fixtures.file_appeal(
            ctx["petition"]["id"], student_id,
            grounds="First appeal with additional documentation",
        )
        # 31 days after the 2026-05-01 decision: past the inclusive 30-day window.
        get_success_data(api_client.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN))

        resp = api_client.create_appeal(
            {
                "petition_id": ctx["petition"]["id"],
                "grounds": "Second appeal attempt with further evidence",
            },
            make_student_headers(student_id),
        )
        # Both the window (documented first) and uniqueness are violated;
        # the temporal error is reported.
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)

    def test_appeal_window_boundary_day_is_timely(self):
        """PRD §3.7: "requires the logical clock to be no later than thirty days
        after the petition's `decided_at` — the boundary day itself is still
        timely".

        Design: Difficulty/priority_pair_validation_conflict/appeal_window_temporal_beats_duplicate_constraint
        """
        ctx = fixtures.setup_denied_petition()
        student_id = ctx["student"]["id"]
        # Petition denied at default clock 2026-05-01; 30 days later is 2026-05-31.
        get_success_data(api_client.set_clock({"to_iso8601": "2026-05-31T00:00:00Z"}, ADMIN))

        appeal = fixtures.file_appeal(
            ctx["petition"]["id"], student_id,
            grounds="Boundary-day appeal, exactly thirty days after denial",
        )
        assert appeal["status"] == "FILED"


class TestEquivalencyCreateOnSuspendedAgreement:
    def test_equivalency_create_on_suspended_agreement_returns_not_editable(self):
        """PRD §3.3: "Equivalencies may be added only while the parent agreement
        is `DRAFT` or `ACTIVE` — against any other status the write fails with
        `ERR_AGREEMENT_NOT_EDITABLE` (HTTP 409)".

        Design: Corner/validations/equivalency_create_on_suspended_agreement_returns_not_editable
        """
        partner = fixtures.create_partner(name="Suspend College", code="SP")
        course = fixtures.create_course(code="MATH-150")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))
        current = fixtures.get_agreement(agreement["id"])

        resp = api_client.create_course_equivalency(
            agreement["id"],
            {
                "internal_course_id": course["id"],
                "external_course_code": "M-101",
                "external_title": "Calc",
                "external_credit_hours": 4.0,
                "effective_from": "2024-08-01",
                "effective_until": "2027-07-31",
                "expected_agreement_version": current["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EDITABLE)
