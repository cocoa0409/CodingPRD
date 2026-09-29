"""Eligibility refuses on programme state, on inclusive thresholds, and in ladder order."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.test_users import (
    ELIGIBILITY_REVIEWER_1_ID,
    ELIGIBILITY_REVIEWER_2_ID,
    ELIGIBILITY_REVIEWER_3_ID,
    make_eligibility_reviewer_headers,
)

EDUCATION_REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_1_ID)
EXPERIENCE_REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_2_ID)
AUDITOR = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_3_ID)

ALL_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _verify(api, application_id, dimension, headers):
    return validate_success(api.verify_application_dimension(
        application_id, f.verify_dimension_payload(dimension, "PASS"), headers), 200)


def _three_boundary_applications(api):
    """Exactly at both thresholds, one month short, and one year too old."""
    program = fx.active_program(api)
    profiles = [("a", 24, 2016), ("b", 23, 2016), ("c", 24, 2015)]
    applications = []
    for label, months, year in profiles:
        candidate = fx.create_candidate(api, email=f"cand.{label}@example.com",
                                        full_name=f"Cand {label.upper()}")
        applications.append(fx.submitted_application(
            api, candidate["id"], program["id"], experience_months=months,
            education_completion_year=year))
    return program, applications


def _application_awaiting_audit(api):
    """A programme that audits every completion, so the verified pair is sampled."""
    state = fx.pipeline_through_published_form(api, program_overrides={"audit_every_nth": 1})
    candidate = fx.create_candidate(api)
    application = fx.approved_application(api, candidate["id"], state.program_id)
    assert application["status"] == "AUDIT_SELECTED"
    state.candidate_id = candidate["id"]
    state.application_id = application["id"]
    return state


class TestApplicationRequiresAnActiveProgramme:
    """The gate is on the programme's state, not on the body's shape."""

    def test_a_draft_programme_refuses_the_application_and_stores_nothing(self, api):
        """A well-formed submission against a programme that was never activated is
        refused on state, and no application row survives the attempt.

        PRD §3.6: "The cited program must be `ACTIVE`, or the submission is refused with
        `ERR_PROGRAM_NOT_ACTIVE`."

        Design: Corner/validations/application_against_a_draft_programme_returns_program_not_active
        """
        program = fx.create_program(api)
        candidate = fx.create_candidate(api)
        assert program["status"] == "DRAFT"

        refused = api.create_application(
            f.create_application_payload(candidate["id"], program["id"]), EDUCATION_REVIEWER)

        error = validate_error(refused, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        assert error["error_id"] != ApiErrorId.ERR_PROGRAM_NOT_FOUND.value
        _rows, meta = validate_paginated(api.list_applications(EDUCATION_REVIEWER))
        assert meta["total_count"] == 0

    def test_activation_lets_the_identical_body_through_at_submitted(self, api):
        """Nothing about the request changes: once the programme is ACTIVE the same body
        creates an application with both dimensions pending.

        PRD §3.6: "A new application has `status` `SUBMITTED`, both `education_status` and
        `experience_status` `PENDING`, an empty `verifier_user_ids` list, `attempts_consumed`
        at 0, and `eligibility_expires_on`, `audit_sequence_number`, `auditor_user_id`, and
        `denial_reason` all null."

        Design: Corner/validations/application_against_a_draft_programme_returns_program_not_active
        """
        program = fx.create_program(api)
        candidate = fx.create_candidate(api)
        body = f.create_application_payload(candidate["id"], program["id"])
        api.create_application(body, EDUCATION_REVIEWER)

        activated = validate_success(api.activate_program(
            program["id"], f.activate_program_payload(), fx.PROGRAM_ADMIN), 200)
        assert activated["status"] == "ACTIVE"

        application = validate_success(api.create_application(body, EDUCATION_REVIEWER), 201)
        assert application["status"] == "SUBMITTED"
        assert application["education_status"] == "PENDING"
        assert application["experience_status"] == "PENDING"
        assert application["attempts_consumed"] == 0
        assert application["eligibility_expires_on"] is None
        assert application["audit_sequence_number"] is None
        ax.assert_eligibility_application(application, expected_version=1)


class TestInclusiveEligibilityThresholds:
    """Both prerequisite comparisons are at-least comparisons."""

    def test_exactly_the_threshold_month_and_the_oldest_admissible_year_verify(self, api):
        """Twenty-four months of practice and a credential earned exactly ten years ago
        both clear, so the application reaches APPROVED with both verifiers recorded.

        PRD §3.6: "Both comparisons are inclusive: `experience_months` exactly equal to
        `min_experience_months` verifies, and a credential completed in exactly the year that
        is `education_recency_years` before the current year verifies while one completed a
        year earlier fails."

        PRD §3.6: "Each accepted call appends a record of the `dimension` together with the
        acting `user_id` to `verifier_user_ids`, in call order."

        Design: Corner/validations/eligibility_verifies_at_exactly_twenty_four_months_and_exactly_ten_year_old_education
        """
        _program, applications = _three_boundary_applications(api)

        half_done = _verify(api, applications[0]["id"], "EDUCATION", EDUCATION_REVIEWER)
        assert half_done["status"] == "UNDER_REVIEW"
        assert half_done["education_status"] == "VERIFIED"

        approved = _verify(api, applications[0]["id"], "EXPERIENCE", EXPERIENCE_REVIEWER)
        assert approved["status"] == "APPROVED"
        assert approved["experience_status"] == "VERIFIED"
        assert approved["audit_sequence_number"] == 1
        assert str(approved["eligibility_expires_on"]).startswith("2027-08-01")
        assert [entry["user_id"] for entry in approved["verifier_user_ids"]] == [
            ELIGIBILITY_REVIEWER_1_ID, ELIGIBILITY_REVIEWER_2_ID]
        assert [entry["dimension"] for entry in approved["verifier_user_ids"]] == [
            "EDUCATION", "EXPERIENCE"]

    def test_one_month_short_and_one_year_too_old_are_each_denied(self, api):
        """A month below the threshold fails the experience dimension and a year beyond
        recency fails the education dimension, and only the satisfied pair advanced the
        audit counter.

        PRD §3.6: "The education dimension clears the arithmetic when the application's
        `education_credential` appears in the program's `accepted_education_credentials`
        **and** its `education_completion_year` is at least the current year of the logical
        clock minus the program's `education_recency_years`."

        PRD §3.6: "A call in which the decided dimension evaluates to `FAILED` sends the
        application straight to `DENIED` — from `SUBMITTED` if it is the first dimension
        decided, from `UNDER_REVIEW` if it is the second — with `denial_reason` set to
        `EDUCATION_FAILED` or `EXPERIENCE_FAILED` according to which dimension failed."

        Design: Corner/validations/eligibility_verifies_at_exactly_twenty_four_months_and_exactly_ten_year_old_education
        """
        program, applications = _three_boundary_applications(api)
        _verify(api, applications[0]["id"], "EDUCATION", EDUCATION_REVIEWER)
        _verify(api, applications[0]["id"], "EXPERIENCE", EXPERIENCE_REVIEWER)

        _verify(api, applications[1]["id"], "EDUCATION", EDUCATION_REVIEWER)
        short_experience = _verify(api, applications[1]["id"], "EXPERIENCE",
                                   EXPERIENCE_REVIEWER)
        assert short_experience["status"] == "DENIED"
        assert short_experience["experience_status"] == "FAILED"
        assert short_experience["denial_reason"] == "EXPERIENCE_FAILED"

        stale_education = _verify(api, applications[2]["id"], "EDUCATION", EDUCATION_REVIEWER)
        assert stale_education["status"] == "DENIED"
        assert stale_education["education_status"] == "FAILED"
        assert stale_education["denial_reason"] == "EDUCATION_FAILED"

        assert fx.read_program(api, program["id"])["verified_application_counter"] == 1


class TestBodyReferenceOutranksSchema:
    """One request breaks two rules and must answer with the earlier layer's error."""

    def test_the_unknown_candidate_outranks_the_missing_attestation(self, api):
        """The body cites a candidate that does not exist and omits the attestation; the
        ladder answers 404 on the reference rather than 400 on the shape.

        PRD §2.7: "4. **Body-reference existence.** Every foreign identifier carried in a
        request body resolves to a stored record, with the 404 that matches the referenced
        collection. This layer guards item creation, form assembly, application submission,
        registration creation, and disciplinary case opening."

        PRD §2.7: "7. **Schema.** All required body fields present, enum values within their
        declared sets, integers non-negative, array sizes within their declared bounds,
        timestamps ISO 8601 → otherwise `ERR_INVALID_REQUEST` (400). Applies to every write
        operation."

        Design: Corner/validations/unknown_candidate_id_not_found_outranks_the_missing_attestation_on_one_application
        """
        program = fx.active_program(api)
        body = f.create_application_payload(ALL_ZERO_UUID, program["id"])
        body.pop("attestation_signed")

        refused = api.create_application(body, EDUCATION_REVIEWER)

        error = validate_error(refused, ApiErrorId.ERR_CANDIDATE_NOT_FOUND.value, 404)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

    def test_each_rule_is_independently_live_and_neither_refusal_wrote_a_row(self, api):
        """With a real candidate the omission alone is a 400, the complete body is a 201,
        and exactly one application exists at the end.

        PRD §3.6: "`attestation_signed`, which must be true — an application submitted
        without a signed attestation to the code of conduct is refused with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/unknown_candidate_id_not_found_outranks_the_missing_attestation_on_one_application
        """
        program = fx.active_program(api)
        candidate = fx.create_candidate(api)
        incomplete = f.create_application_payload(candidate["id"], program["id"])
        incomplete.pop("attestation_signed")

        api.create_application(f.create_application_payload(ALL_ZERO_UUID, program["id"]),
                               EDUCATION_REVIEWER)
        validate_error(api.create_application(incomplete, EDUCATION_REVIEWER),
                       ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        created = validate_success(api.create_application(
            f.create_application_payload(candidate["id"], program["id"]),
            EDUCATION_REVIEWER), 201)
        assert created["status"] == "SUBMITTED"
        _rows, meta = validate_paginated(api.list_applications(EDUCATION_REVIEWER))
        assert meta["total_count"] == 1


class TestAuditHoldBlocksRegistration:
    """The registration gate reads the application's status, not the request's shape."""

    def test_an_audited_application_refuses_the_registration_on_approval_alone(self, api):
        """With a published form and a sufficient fee, the only thing wrong is that the
        application sits in audit.

        PRD §2.7: "15. **Application approved.** The cited eligibility application's
        `status` is `APPROVED` → otherwise `ERR_APPLICATION_NOT_APPROVED` (409). Applies to
        registration creation."

        PRD §3.6: "its `eligibility_expires_on` deliberately stays null, and any attempt to
        register against it is refused with `ERR_APPLICATION_NOT_APPROVED` until the audit is
        decided."

        Design: Corner/validations/registration_is_blocked_while_the_application_sits_in_audit_and_unblocked_by_the_audit_decision
        """
        state = _application_awaiting_audit(api)

        refused = api.create_exam_registration(
            f.create_registration_payload(state.application_id, state.form_id),
            fx.EXAM_OPERATIONS)

        error = validate_error(refused, ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_FORM_NOT_PUBLISHED.value
        assert error["error_id"] != ApiErrorId.ERR_EXAM_FEE_INSUFFICIENT.value
        application = fx.read_application(api, state.application_id)
        assert application["status"] == "AUDIT_SELECTED"
        assert application["eligibility_expires_on"] is None

    def test_a_passing_audit_decision_unblocks_the_identical_registration_body(self, api):
        """An independent auditor's PASS stamps the eligibility date and approves the
        application, and the same registration body is then accepted.

        PRD §3.6: "A `PASS` moves the application `AUDIT_SELECTED → APPROVED` and stamps
        `eligibility_expires_on` from the current logical-clock instant plus
        `eligibility_valid_days`, exactly as the unsampled branch would have."

        PRD §3.7: "A new registration begins with `seat_status` `UNSCHEDULED`, `score_status`
        `NOT_APPLICABLE`, `form_reassignment_required` false, `session_id` and
        `session_ends_at` null, and `raw_score`, `scaled_score`, `outcome`, and
        `score_status_before_hold` all null."

        Design: Corner/validations/registration_is_blocked_while_the_application_sits_in_audit_and_unblocked_by_the_audit_decision
        """
        state = _application_awaiting_audit(api)
        body = f.create_registration_payload(state.application_id, state.form_id)
        api.create_exam_registration(body, fx.EXAM_OPERATIONS)

        audited = validate_success(api.decide_application_audit(
            state.application_id,
            f.audit_decision_payload("PASS",
                                     audit_note="transcripts and employer letters sighted"),
            AUDITOR), 200)

        assert audited["status"] == "APPROVED"
        assert audited["auditor_user_id"] == ELIGIBILITY_REVIEWER_3_ID
        assert str(audited["eligibility_expires_on"]).startswith("2027-08-01")
        assert audited["audit_sequence_number"] == 1

        registration = validate_success(
            api.create_exam_registration(body, fx.EXAM_OPERATIONS), 201)
        assert registration["attempt_number"] == 1
        assert registration["seat_status"] == "UNSCHEDULED"
        assert registration["session_id"] is None
        assert fx.read_program(api, state.program_id)["verified_application_counter"] == 1
