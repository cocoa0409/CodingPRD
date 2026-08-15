"""Exemption requests: adjudication lifecycle, segregation of duties, outbreak guard."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exemption_request,
    assert_student,
    create_approved_exemption,
    create_denied_exemption,
    create_exemption_request_payload,
    create_mmr_requirement,
    create_student,
    declare_outbreak,
    get_student,
    lift_outbreak,
    list_exemptions,
    make_nurse_headers,
    make_officer_headers,
    resubmit_exemption_payload,
    submit_exemption,
    validate_error,
    validate_success,
)


class TestDenyResubmitCycle:

    def test_deny_then_resubmit_clears_review_fields(self):
        """PRD section 3.4: "Resubmission returns the request to `SUBMITTED`,
        replaces `document_ref` with the new value, clears `reviewed_by_user_id`
        and `denial_reason` back to null, and — crucially for segregation of
        duties — re-anchors `submitted_by_user_id` to the resubmitting caller's
        `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/exemption_deny_resubmit_cycle
        """
        student, denied = create_denied_exemption("SCH-C", requirement=True)
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "missing physician signature"

        resp = api_client.resubmit_exemption(
            denied["id"],
            resubmit_exemption_payload(document_ref="doc://exm-v2"),
            make_nurse_headers("nurse-1"),
        )
        resubmitted = validate_success(resp, 200)
        assert_exemption_request(resubmitted)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["document_ref"] == "doc://exm-v2"
        assert resubmitted["reviewed_by_user_id"] is None
        assert resubmitted["denial_reason"] is None
        assert resubmitted["submitted_by_user_id"] == "nurse-1"

    def test_resubmit_then_approve_completes_cycle(self):
        """PRD section 3.4: "Approval moves the request to `APPROVED` and
        immediately re-evaluates the student, since an `APPROVED` exemption
        satisfies its requirement under both lenses; if the approval completes the
        student's schedule, the student transitions toward `ENROLLED_COMPLIANT` as
        described in §3.5."
        PRD section 3.5: "A student in `ENROLLED_PROVISIONAL` who reaches full
        satisfaction through the same events transitions directly to
        `ENROLLED_COMPLIANT` with the deficiency list cleared."

        Design: Difficulty/non_linear_state_machine/exemption_deny_resubmit_cycle
        """
        student, denied = create_denied_exemption("SCH-C", requirement=True)

        resubmitted = validate_success(
            api_client.resubmit_exemption(
                denied["id"],
                resubmit_exemption_payload(document_ref="doc://exm-v2"),
                make_nurse_headers("nurse-1"),
            ),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"

        officer = make_officer_headers("officer-1")
        reviewed = validate_success(
            api_client.start_exemption_review(resubmitted["id"], officer), 200
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        approved = validate_success(
            api_client.approve_exemption(resubmitted["id"], officer), 200
        )
        assert approved["status"] == "APPROVED"

        final = get_student(student["id"])
        assert_student(final)
        assert final["status"] == "ENROLLED_COMPLIANT"
        assert final["deficiency_vaccine_codes"] == []


class TestInvalidExemptionTransitions:

    def test_approve_exemption_from_submitted_rejected(self):
        """PRD section 3.4: "Both approval and denial enforce the same
        segregation-of-duties check as start-review, and both are rejected with
        `ERR_EXEMPTION_NOT_REVIEWABLE` when attempted from a state other than
        `UNDER_REVIEW`."

        Design: Corner/state_machines/approve_exemption_from_submitted_rejected
        """
        student = create_student("SCH-SM", legal_name="Skip Step")
        exemption = submit_exemption(student["id"], document_ref="doc://sm-1")
        assert exemption["status"] == "SUBMITTED"

        resp = api_client.approve_exemption(
            exemption["id"], make_officer_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_NOT_REVIEWABLE)

        exemptions, _ = list_exemptions(student["id"])
        assert exemptions[0]["status"] == "SUBMITTED", (
            "a rejected approval must leave the request SUBMITTED"
        )

    def test_resubmit_from_approved_rejected(self):
        """PRD section 3.4: "A `SchoolNurse` or `DistrictHealthOfficer` may resubmit
        a request that is in `DENIED`, supplying a fresh `document_ref`;
        resubmission from any other state is rejected with
        `ERR_EXEMPTION_NOT_RESUBMITTABLE`."

        Design: Corner/state_machines/resubmit_from_approved_rejected
        """
        student = create_student("SCH-SM", legal_name="Re Sub")
        exemption = create_approved_exemption(student["id"])
        assert exemption["status"] == "APPROVED"

        resp = api_client.resubmit_exemption(
            exemption["id"],
            resubmit_exemption_payload(document_ref="doc://sm-2b"),
            make_nurse_headers("nurse-1"),
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_NOT_RESUBMITTABLE)

        exemptions, _ = list_exemptions(student["id"])
        assert exemptions[0]["status"] == "APPROVED", (
            "a rejected resubmission must leave the request APPROVED"
        )


class TestSegregationOfDuties:

    def test_segregation_of_duties_on_approve(self):
        """PRD section 3.4: "Adjudication is reserved for a
        `DistrictHealthOfficer`, with a hard segregation rule: the reviewing
        officer must not be the person who submitted the request."
        PRD section 3.4: "the action is rejected with
        `ERR_EXEMPTION_NOT_REVIEWABLE` from any other state, and with
        `ERR_SEGREGATION_OF_DUTIES` when the caller's `X-User-ID` equals the
        request's `submitted_by_user_id`."

        Design: Corner/validations/segregation_of_duties_on_approve
        """
        student = create_student("SCH-SOD", legal_name="Seg Duty")
        # DistrictHealthOfficer may also submit (shared operation, PRD section 4).
        exemption = submit_exemption(
            student["id"],
            document_ref="doc://sod-1",
            submitter_headers=make_officer_headers("officer-1"),
        )
        assert exemption["submitted_by_user_id"] == "officer-1"

        resp = api_client.start_exemption_review(
            exemption["id"], make_officer_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        officer_2 = make_officer_headers("officer-2")
        reviewed = validate_success(
            api_client.start_exemption_review(exemption["id"], officer_2), 200
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["reviewed_by_user_id"] == "officer-2"
        approved = validate_success(
            api_client.approve_exemption(exemption["id"], officer_2), 200
        )
        assert approved["status"] == "APPROVED"


class TestApproveOutbreakGuard:

    def test_exemption_approve_blocked_by_active_outbreak(self):
        """PRD section 3.4: "Approval is not permitted while an outbreak is active
        for the same school and vaccine — the combination of the student's
        `school_code` and the request's `vaccine_code` — and such an attempt is
        rejected with `ERR_OUTBREAK_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/exemption_approve_blocked_by_active_outbreak
        """
        create_mmr_requirement(doses_required=1)
        student = create_student("SCH-X2", legal_name="Ola Ex")
        exemption = submit_exemption(student["id"], exemption_type="RELIGIOUS",
                                     document_ref="doc://exm-x2")
        reviewed = validate_success(
            api_client.start_exemption_review(
                exemption["id"], make_officer_headers("officer-1")
            ),
            200,
        )
        assert reviewed["status"] == "UNDER_REVIEW"

        declare_outbreak("SCH-X2", "MMR")

        resp = api_client.approve_exemption(
            exemption["id"], make_officer_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_OUTBREAK_ACTIVE)

        exemptions, _ = list_exemptions(student["id"])
        assert exemptions[0]["status"] == "UNDER_REVIEW", (
            "a rejected approval must leave the request UNDER_REVIEW"
        )

    def test_exemption_approve_allowed_after_outbreak_lifted(self):
        """PRD section 3.4: "Approval is not permitted while an outbreak is active
        for the same school and vaccine — the combination of the student's
        `school_code` and the request's `vaccine_code` — and such an attempt is
        rejected with `ERR_OUTBREAK_ACTIVE`."
        PRD section 3.6: "Lifting the outbreak — again a `DistrictHealthOfficer`
        action, permitted only while the event is `ACTIVE` and otherwise rejected
        with `ERR_OUTBREAK_ALREADY_LIFTED` — moves the event to its terminal
        `LIFTED` status, stamps `lifted_at`, and runs the cascade in reverse."

        Design: Difficulty/cross_entity_state_dependency/exemption_approve_blocked_by_active_outbreak
        """
        create_mmr_requirement(doses_required=1)
        student = create_student("SCH-X2", legal_name="Ola Ex")
        exemption = submit_exemption(student["id"], exemption_type="RELIGIOUS",
                                     document_ref="doc://exm-x2")
        validate_success(
            api_client.start_exemption_review(
                exemption["id"], make_officer_headers("officer-1")
            ),
            200,
        )
        outbreak = declare_outbreak("SCH-X2", "MMR")
        lift_outbreak(outbreak["id"])

        approved = validate_success(
            api_client.approve_exemption(
                exemption["id"], make_officer_headers("officer-1")
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        final = get_student(student["id"])
        assert final["status"] == "ENROLLED_COMPLIANT"
