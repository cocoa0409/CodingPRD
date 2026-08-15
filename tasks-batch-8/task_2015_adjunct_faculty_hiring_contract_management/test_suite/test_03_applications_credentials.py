"""Recruiting pipeline: revision loop cap, segregation of duties, credential
completeness, approval side effects, credential state gates (PRD Sections 2.8, 3.3)."""
from test_helpers import (
    ApiErrorId,
    add_credential,
    approve_application_by_second_reviewer,
    create_application,
    create_department,
    create_fall_term,
    create_open_posting,
    get_success_data,
    set_clock,
    start_review,
    validate_error,
    validate_success,
    verify_credential,
)
from test_helpers import TEST_USERS

REV1 = TEST_USERS["hr_reviewer_1_headers"]
REV2 = TEST_USERS["hr_reviewer_2_headers"]


def _open_posting(dept_code, min_tier="BACHELORS"):
    set_clock("2026-06-01T00:00:00Z")
    dept = create_department(code=dept_code, contact_hour_value=1.00)
    create_fall_term()
    return create_open_posting(dept["id"], term_code="2026FA", min_education_tier=min_tier)


def _under_review_application(posting_id, name, email, tier="BACHELORS"):
    application = create_application(
        posting_id, applicant_name=name, applicant_email=email,
        claimed_education_tier=tier,
    )
    start_review(application["id"])
    return application


class TestApprovalSideEffect:
    def test_application_approve_creates_faculty_side_effect(self, api, hr_admin_headers):
        """PRD Section 3.3: "A successful approval moves the application to
        `APPROVED` and creates the faculty record: the new `AdjunctFaculty` carries
        the application's `application_id`, the posting's `department_id`, a
        `legal_name` copied from `applicant_name`, an `education_tier` set to the
        highest tier evidenced among the application's verified credentials, and a
        `hire_date` set to the current logical date."
        PRD Section 3.3: "The faculty record starts with `compliance_status`
        `ONBOARDING` and `retention_status` `PROVISIONAL`, and the system immediately
        evaluates the onboarding-to-compliant automatic transition against any
        already-verified `BACKGROUND_CHECK` and `TRAINING` credentials on the
        application, so a fully cleared applicant is created directly in `COMPLIANT`."

        Design: Corner/state_machines/application_approve_creates_faculty_side_effect
        """
        posting = _open_posting("HIRE", min_tier="BACHELORS")
        application = _under_review_application(
            posting["id"], "Rae Adjunct", "rae@x.edu", tier="BACHELORS")
        degree = add_credential(application["id"], "DEGREE", tier="DOCTORATE")
        bg = add_credential(application["id"], "BACKGROUND_CHECK")
        tr = add_credential(application["id"], "TRAINING")
        for cred in (degree, bg, tr):
            verify_credential(cred["id"])

        approved = approve_application_by_second_reviewer(application["id"])
        assert approved["application_status"] == "APPROVED"
        assert approved["hired_faculty_id"], "hired_faculty_id back-link must be set"

        faculty = get_success_data(api.get_faculty(approved["hired_faculty_id"], hr_admin_headers))
        assert faculty["application_id"] == application["id"]
        assert faculty["department_id"] == posting["department_id"]
        assert faculty["legal_name"] == "Rae Adjunct"
        assert faculty["education_tier"] == "DOCTORATE", (
            "highest VERIFIED tier wins over the claimed BACHELORS"
        )
        assert faculty["compliance_status"] == "COMPLIANT", (
            "fully cleared applicant is created directly in COMPLIANT"
        )
        assert faculty["retention_status"] == "PROVISIONAL"


class TestCredentialStateGate:
    def test_credential_verify_idempotency_second_attempt_fails(self, api):
        """PRD Section 3.3: "Verifying moves a record from `PENDING` to `VERIFIED`"
        — the transition exists only out of `PENDING`.
        PRD Section 2.8: "This single state error covers terminal-state lockdown and
        repeated-action (double-action) failures, and it applies to every action
        endpoint: posting publish, suspend, resume, close, and archive; application
        start-review, return-for-revision, resubmit, approve, reject, and withdraw;
        credential verify and reject; section cancel and complete; contract void;
        payroll period lock and close; reappoint and mark-non-reappointed; and
        compliance reinstatement."
        PRD Section 3.3: "Either decision stamps the record with `verified_by_hr_id`
        — the acting reviewer's `X-User-ID` — and `decided_at`, the current logical
        timestamp."

        Design: Corner/state_machines/credential_verify_idempotency_second_attempt_fails
        """
        posting = _open_posting("IDEM")
        application = _under_review_application(posting["id"], "Sam Adjunct", "sam@x.edu")
        cred = add_credential(application["id"], "LICENSE")
        verified = verify_credential(cred["id"])
        assert verified["verification_status"] == "VERIFIED"
        assert verified["verified_by_hr_id"] == "hr_reviewer_1"

        second = api.verify_credential(cred["id"], REV2)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api.get_credential(cred["id"], REV1))
        assert after["verified_by_hr_id"] == "hr_reviewer_1", "first decision stands"
        assert after["verification_status"] == "VERIFIED"

    def test_credential_verify_guarded_by_application_state_rejected_app(self, api):
        """PRD Section 3.3: "Verifying moves a record from `PENDING` to `VERIFIED`,
        rejecting moves it from `PENDING` to `REJECTED`, and both are allowed only
        while the application is `UNDER_REVIEW` or `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/credential_verify_guarded_by_application_state
        """
        posting = _open_posting("ANTH")
        application = _under_review_application(posting["id"], "Lee Adjunct", "lee@x.edu")
        cred = add_credential(application["id"], "TRANSCRIPT", tier="BACHELORS")
        get_success_data(api.reject_application(application["id"], REV2))

        blocked = api.verify_credential(cred["id"], REV1)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_credential(cred["id"], REV1))
        assert after["verification_status"] == "PENDING", (
            "failed verify must leave the credential untouched"
        )

    def test_credential_reject_guarded_by_application_state_rejected_app(self, api):
        """PRD Section 3.3: "Verifying moves a record from `PENDING` to `VERIFIED`,
        rejecting moves it from `PENDING` to `REJECTED`, and both are allowed only
        while the application is `UNDER_REVIEW` or `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/credential_verify_guarded_by_application_state
        """
        posting = _open_posting("ANT2")
        application = _under_review_application(posting["id"], "Lee Two", "lee2@x.edu")
        cred = add_credential(application["id"], "TRANSCRIPT", tier="BACHELORS")
        get_success_data(api.reject_application(application["id"], REV2))

        blocked = api.reject_credential(cred["id"], REV1)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_credential(cred["id"], REV1))
        assert after["verification_status"] == "PENDING"


class TestSegregationOfDuties:
    def test_segregation_of_duties_same_reviewer_blocked(self, api):
        """PRD Section 3.3: "The acting reviewer's `X-User-ID` must differ from
        `verified_by_hr_id` on every `VERIFIED` credential of the application: a
        reviewer who personally verified any credential on a file cannot approve
        that file, and the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/validations/segregation_of_duties_same_reviewer_blocked
        """
        posting = _open_posting("SODX")
        application = _under_review_application(posting["id"], "Ali Adjunct", "ali@x.edu")
        cred = add_credential(application["id"], "TRANSCRIPT", tier="BACHELORS")
        verify_credential(cred["id"])  # verified by hr_reviewer_1

        own = api.approve_application(application["id"], REV1)
        validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        other = api.approve_application(application["id"], REV2)
        approved = validate_success(other, 200)
        assert approved["application_status"] == "APPROVED"


class TestCredentialCompleteness:
    def test_approve_blocked_by_pending_credential(self, api):
        """PRD Section 3.3: "Completeness then demands three things, any failure of
        which is refused with `ERR_CREDENTIALS_INCOMPLETE`: every `TRANSCRIPT` and
        `DEGREE` credential on the application is `VERIFIED`; at least one `VERIFIED`
        credential evidences a `verified_education_tier` at or above the posting's
        `min_education_tier`, using the tier ordering in which `BACHELORS` ranks
        below `MASTERS`, which ranks below `DOCTORATE`; and no credential of any
        kind on the application remains `PENDING`."

        Design: Corner/validations/approve_blocked_by_pending_credential
        """
        posting = _open_posting("PEND")
        application = _under_review_application(posting["id"], "Bea Adjunct", "bea@x.edu")
        transcript = add_credential(application["id"], "TRANSCRIPT", tier="BACHELORS")
        add_credential(application["id"], "LICENSE")  # stays PENDING
        verify_credential(transcript["id"])

        blocked = api.approve_application(application["id"], REV2)
        validate_error(blocked, ApiErrorId.ERR_CREDENTIALS_INCOMPLETE)

    def test_approve_blocked_when_verified_tier_below_minimum(self, api):
        """PRD Section 3.3: "at least one `VERIFIED` credential evidences a
        `verified_education_tier` at or above the posting's `min_education_tier`,
        using the tier ordering in which `BACHELORS` ranks below `MASTERS`, which
        ranks below `DOCTORATE`" — failures are refused with
        `ERR_CREDENTIALS_INCOMPLETE`.

        Design: Corner/validations/approve_blocked_when_verified_tier_below_minimum
        """
        posting = _open_posting("TIER", min_tier="MASTERS")
        application = _under_review_application(
            posting["id"], "Cid Adjunct", "cid@x.edu", tier="MASTERS")
        transcript = add_credential(application["id"], "TRANSCRIPT", tier="BACHELORS")
        verify_credential(transcript["id"])

        blocked = api.approve_application(application["id"], REV2)
        validate_error(blocked, ApiErrorId.ERR_CREDENTIALS_INCOMPLETE)


class TestRevisionCycleCap:
    def _application_after_two_loops(self, api, dept_code, email):
        posting = _open_posting(dept_code)
        application = _under_review_application(posting["id"], "Eve Adjunct", email)
        for _ in range(2):
            get_success_data(api.return_for_revision(application["id"], REV1))
            get_success_data(api.resubmit_application(application["id"], REV1))
        return application

    def test_revision_cycle_loops_three_times(self, api):
        """PRD Section 3.3: "Returning the application for revision moves it to
        `RETURNED_FOR_REVISION`, increments its `revision_count` by one, and is
        bounded: the return is allowed only while `revision_count` is below three,
        so an application may cycle `UNDER_REVIEW` to `RETURNED_FOR_REVISION` and
        back at most three times"

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_with_cap
        """
        application = self._application_after_two_loops(api, "BIOL", "eve@x.edu")
        third = validate_success(
            api.return_for_revision(application["id"], REV1), 200)
        assert third["revision_count"] == 3, "third return increments the count to 3"
        assert third["application_status"] == "RETURNED_FOR_REVISION"
        back = validate_success(api.resubmit_application(application["id"], REV1), 200)
        assert back["application_status"] == "UNDER_REVIEW", "cycle traversed a third time"
        assert back["revision_count"] == 3

    def test_fourth_return_attempt_rejected_at_cap(self, api):
        """PRD Section 3.3: "the return is allowed only while `revision_count` is
        below three, so an application may cycle `UNDER_REVIEW` to
        `RETURNED_FOR_REVISION` and back at most three times, and a fourth return
        attempt is refused with `ERR_REVISION_LIMIT`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_with_cap
        """
        application = self._application_after_two_loops(api, "BIO2", "eve2@x.edu")
        validate_success(api.return_for_revision(application["id"], REV1), 200)
        validate_success(api.resubmit_application(application["id"], REV1), 200)

        fourth = api.return_for_revision(application["id"], REV1)
        validate_error(fourth, ApiErrorId.ERR_REVISION_LIMIT)
        after = get_success_data(api.get_application(application["id"], REV1))
        assert after["application_status"] == "UNDER_REVIEW", (
            "failed transition leaves the state unchanged"
        )
        assert after["revision_count"] == 3


class TestStateBeatsSegregation:
    def _withdrawn_application_verified_by_rev1(self, api, dept_code):
        posting = _open_posting(dept_code)
        application = _under_review_application(posting["id"], "Hal Adjunct", "hal@x.edu")
        cred = add_credential(application["id"], "TRANSCRIPT", tier="BACHELORS")
        verify_credential(cred["id"])  # verified by hr_reviewer_1
        get_success_data(api.withdraw_application(application["id"], REV2))
        return application

    def test_state_beats_safety_on_approve_of_withdrawn_application(self, api):
        """PRD Section 3.3: "Approval is the pipeline's gate with the most
        conditions, evaluated in the pipeline order of Section 2.8 — state gate
        first, then segregation of duties, then credential completeness."
        PRD Section 3.3: "The terminal application states are `APPROVED`,
        `REJECTED`, `WITHDRAWN`, and `EXPIRED`; any action attempted from a terminal
        state fails the state gate with `ERR_INVALID_STATE`."

        The approving reviewer DID verify the file's credential, so segregation
        would also fail — the state gate must win because it evaluates first.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_approve_of_withdrawn_application
        """
        application = self._withdrawn_application_verified_by_rev1(api, "GEOL")
        resp = api.approve_application(application["id"], REV1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_of_withdrawn_application_is_state_error_for_any_reviewer(self, api):
        """PRD Section 3.3: "The terminal application states are `APPROVED`,
        `REJECTED`, `WITHDRAWN`, and `EXPIRED`; any action attempted from a terminal
        state fails the state gate with `ERR_INVALID_STATE`."

        A reviewer who verified nothing on the file still gets the state error,
        isolating the state gate from the segregation rule.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_approve_of_withdrawn_application
        """
        application = self._withdrawn_application_verified_by_rev1(api, "GEO2")
        resp = api.approve_application(application["id"], REV2)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_application(application["id"], REV1))
        assert after["application_status"] == "WITHDRAWN"

