"""RBAC denials, authentication priority, domain-specific 404s, and FK
reverse-lookup listings."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_assignment,
    assign_study,
    create_active_hospital,
    create_draft_report,
    create_hospital_payload,
    create_radiologist,
    create_routed_study,
    create_study_payload,
    get_success_data,
    make_hospital_user_headers,
    make_qa_headers,
    make_radiologist_headers,
    setup_assignment_ready,
    setup_credentialed_radiologist,
    setup_routing_ready_hospital,
    setup_study_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import NONEXISTENT_UUID

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]
QA = TEST_USERS["qa_headers"]


class TestRoleDenials:
    def test_radiologist_cannot_create_hospital(self, api):
        """PRD section 2.1: "A request whose role is authenticated but not
        listed among an endpoint's authorized roles, or that violates one of
        these ownership bindings, is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)." and the endpoint table: POST /telerad/hospitals is
        authorized for PlatformAdmin only.

        Design: Corner/rbac/radiologist_cannot_create_hospital
        """
        rad = create_radiologist(full_name="RB Rad", subspecialties=["BODY"])
        resp = api.create_hospital(
            create_hospital_payload(name="Nope Hosp", state_code="CA"),
            make_radiologist_headers(rad["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_hospital_user_cannot_create_study_for_other_hospital(self, api):
        """PRD section 2.1: "When `X-User-Role` is `ClientHospitalUser`,
        `X-User-ID` is the `id` of an acting ClientHospital, and ownership
        checks compare the resource's `hospital_id` to `X-User-ID`; study
        creation in particular requires the payload's `hospital_id` to equal
        `X-User-ID`."
        PRD section 2.1: "A request whose role is authenticated but not listed
        among an endpoint's authorized roles, or that violates one of these
        ownership bindings, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/hospital_user_cannot_create_study_for_other_hospital
        """
        h1 = create_active_hospital(name="Hosp H1", state_code="CA")
        h2 = create_active_hospital(name="Hosp H2", state_code="TX")
        resp = api.create_study(create_study_payload(h2["id"], "ACC-XH"),
                                make_hospital_user_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_radiologist_cannot_accept_others_assignment(self, api):
        """PRD section 3.5: "Once assigned, only the named radiologist may
        accept: acceptance requires the assignment `ACTIVE`, the caller's
        `X-User-ID` equal to the assignment's `radiologist_id`, and the study in
        `ASSIGNED`; it moves the study to `IN_PROGRESS` and increments both the
        study's and the assignment's `version`."
        PRD section 2.1: "A request whose role is authenticated but not listed
        among an endpoint's authorized roles, or that violates one of these
        ownership bindings, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/radiologist_cannot_accept_others_assignment
        """
        ctx = setup_assignment_ready(hospital_name="Hosp OA")
        hosp, rad_a = ctx["hospital"], ctx["radiologist"]
        rad_b = create_radiologist(full_name="OA B", subspecialties=["NEURORAD"])
        study = create_routed_study(hosp["id"], "ACC-OA")
        asg = assign_study(study["id"], rad_a["id"])

        resp = api.accept_assignment(asg["id"], make_radiologist_headers(rad_b["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_success_data(api.get_assignment(asg["id"], DISPATCH))["status"] == "ACTIVE"
        assert get_success_data(api.get_study(study["id"], DISPATCH))["status"] == "ASSIGNED"

    def test_qa_reviewer_cannot_sign_report(self, api):
        """PRD section 2.1: "A request whose role is authenticated but not
        listed among an endpoint's authorized roles, or that violates one of
        these ownership bindings, is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)." and the endpoint table: POST /telerad/reports/{id}/sign is
        authorized for Radiologist only.

        Design: Corner/rbac/qa_reviewer_cannot_sign_report
        """
        ctx = setup_study_in_progress(accession_number="ACC-QA")
        rad = ctx["radiologist"]
        rep = create_draft_report(ctx["assignment"]["id"], rad["id"], "FINAL")
        resp = api.sign_report(rep["id"], QA)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_success_data(api.get_report(rep["id"], QA))["status"] == "DRAFT"


class TestAuthPriority:
    def test_missing_auth_headers_take_priority_over_not_found(self, api):
        """PRD section 2.8: "Every request passes through a fixed priority
        ladder, and a failure at an earlier rung masks every later rung. First
        (priority 1), authentication headers are validated as in §2.1. ...
        Third (priority 3), existence: every identifier in the path is resolved
        left to right..."
        PRD section 2.1: "A request with missing or unrecognized headers is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_take_priority_over_not_found
        """
        resp = api.get_study(NONEXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestNotFoundSweep:
    def test_study_get_not_found_returns_404(self, api):
        """PRD section 2.8: "Each missing resource raises its own
        domain-specific error: ... `ERR_STUDY_NOT_FOUND`, ... (all HTTP 404)."

        Design: Corner/entities/study_get_not_found_returns_404
        """
        resp = api.get_study(NONEXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FOUND, 404)

    def test_not_found_sweep_across_entities(self, api):
        """PRD section 2.8: "Each missing resource raises its own
        domain-specific error: `ERR_HOSPITAL_NOT_FOUND`,
        `ERR_RADIOLOGIST_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`,
        `ERR_POLICY_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_NOTICE_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND`, or
        `ERR_INVOICE_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/not_found_sweep_across_entities
        """
        cases = [
            (api.get_hospital, ADMIN, ApiErrorId.ERR_HOSPITAL_NOT_FOUND),
            (api.get_radiologist, ADMIN, ApiErrorId.ERR_RADIOLOGIST_NOT_FOUND),
            (api.get_shift, ADMIN, ApiErrorId.ERR_SHIFT_NOT_FOUND),
            (api.get_routing_policy, ADMIN, ApiErrorId.ERR_POLICY_NOT_FOUND),
            (api.get_credential_grant, ADMIN, ApiErrorId.ERR_GRANT_NOT_FOUND),
            (api.get_assignment, ADMIN, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.get_report, QA, ApiErrorId.ERR_REPORT_NOT_FOUND),
            (api.get_discrepancy_case, QA, ApiErrorId.ERR_CASE_NOT_FOUND),
            (api.get_critical_notice, ADMIN, ApiErrorId.ERR_NOTICE_NOT_FOUND),
            (api.get_billing_period, ADMIN, ApiErrorId.ERR_BILLING_PERIOD_NOT_FOUND),
            (api.get_invoice, ADMIN, ApiErrorId.ERR_INVOICE_NOT_FOUND),
        ]
        for getter, headers, err_id in cases:
            resp = getter(NONEXISTENT_UUID, headers)
            validate_error(resp, err_id, 404)


class TestAssignmentReverseLookup:
    def test_assignments_filtered_by_study_reverse_lookup(self, api):
        """PRD section 3.5: "Assignments may be listed filtered by `study_id`,
        `radiologist_id`, or `status`."

        Design: Corner/endpoints/assignments_filtered_by_study_reverse_lookup
        """
        hosp = setup_routing_ready_hospital(name="Hosp RL")
        rad_a, _ga, _sa = setup_credentialed_radiologist(hosp["id"], full_name="RL A")
        rad_b, _gb, _sb = setup_credentialed_radiologist(hosp["id"], full_name="RL B")
        study = create_routed_study(hosp["id"], "ACC-RL")
        asg1 = assign_study(study["id"], rad_a["id"])
        validate_success(api.release_assignment(
            asg1["id"], make_radiologist_headers(rad_a["id"])), 200)
        assign_study(study["id"], rad_b["id"])

        rows, meta = validate_paginated(
            api.list_assignments(DISPATCH, params={"study_id": study["id"]}))
        assert meta["total_count"] == 2
        assert all(r["study_id"] == study["id"] for r in rows)
        by_status = {r["status"] for r in rows}
        assert "RELEASED" in by_status
        assert "ACTIVE" in by_status


class TestRvuModalityConstants:
    def test_study_rvu_modality_constants_applied(self, api):
        """PRD section 3.5: "The base RVU depends only on modality: `CT` 1.5,
        `MR` 2.0, `XR` 0.5, `US` 1.0, `NM` 1.5, and `MG` 1.0, carried at 1
        decimal place." and "The new assignment is created `ACTIVE` with two
        derived attributes: a `phase` of `PRELIMINARY` when the resolved
        policy's `prelim_required` is true and no `SIGNED` preliminary report
        exists yet for the study, and `FINAL` otherwise; and a `reserved_rvu`
        equal to the study's base RVU."

        Design: Corner/calculations/study_rvu_modality_constants_applied
        """
        ctx = setup_assignment_ready(hospital_name="Hosp RVU", modality="XR",
                                     shift_modalities=["XR", "CT"])
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        study = create_routed_study(hosp["id"], "ACC-XR", modality="XR")
        asg = assign_study(study["id"], rad["id"])
        assert asg["reserved_rvu"] == 0.5  # RVU_BASE[XR]
        rad_after = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert rad_after["reserved_rvu"] == 0.5
