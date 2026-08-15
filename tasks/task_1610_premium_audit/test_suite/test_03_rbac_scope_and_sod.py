"""Role authorization, entity-backed ownership scoping, and segregation of
duties."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    add_allocation,
    create_appointment_payload,
    create_auditor,
    create_class_code,
    create_classification_code_payload,
    create_policy,
    create_policy_payload,
    file_dispute,
    find_work_order,
    get_success_data,
    issue_result,
    make_audit_manager_headers,
    make_auditor_headers,
    make_insured_headers,
    run_selection,
    schedule_appointment,
    setup_noncompliant_work_order,
    setup_selected_work_order,
    submit_draft,
    validate_error,
    validate_success,
    wo_version,
)

MANAGER = TEST_USERS["audit_manager_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]
INSURED_FALLBACK = TEST_USERS["insured_headers"]


class TestRoleAuthorization:
    def test_insured_cannot_create_policy(self, api):
        """PRD: "A request whose role is authenticated but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: POST /policies — Underwriter.

        Design: Corner/rbac/insured_cannot_create_policy
        """
        cc = create_class_code()

        resp = api.create_policy(
            create_policy_payload(policy_number="WC-R1",
                                  class_code_ids=[cc["id"]]),
            make_insured_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_auditor_cannot_issue_result(self, api):
        """PRD: "A request whose role is authenticated but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: POST /audit-work-orders/{id}/issue-result —
        AuditManager.

        Design: Corner/rbac/auditor_cannot_issue_result
        """
        ctx = setup_selected_work_order(policy_number="WC-R2",
                                        receive_requests=True)
        add_allocation(ctx, 40000, verify=True)
        submit_draft(ctx)

        resp = api.issue_result(ctx["work_order"]["id"], ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_underwriter_cannot_approve_estimated(self, api):
        """PRD: "A request whose role is authenticated but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: POST /audit-work-orders/{id}/approve-estimated —
        AuditManager.

        Design: Corner/rbac/underwriter_cannot_approve_estimated
        """
        ctx = setup_noncompliant_work_order(policy_number="WC-R3")

        resp = api.approve_estimated(ctx["work_order"]["id"],
                                     TEST_USERS["underwriter_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_billing_clerk_cannot_create_classification_code(self, api):
        """PRD: "A request whose role is authenticated but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: POST /classification-codes — Underwriter.

        Design: Corner/rbac/billing_clerk_cannot_create_classification_code
        """
        resp = api.create_classification_code(
            create_classification_code_payload(), BILLING_CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_missing_auth_headers_returns_401(self, api):
        """PRD: "A request with missing headers, or whose role value is not
        one of these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        resp = api.list_policies({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestOwnershipScope:
    def test_insured_cannot_touch_other_policy_graph(self, api):
        """PRD: "When `X-User-Role` is `Insured`, `X-User-ID` is the `id` of
        the acting **Policy**; ownership checks on any resource in a policy's
        audit graph compare the graph's policy reference to `X-User-ID`. An
        insured touching another policy's graph is rejected with
        `ERR_FORBIDDEN_SCOPE` (HTTP 403)."

        Design: Corner/rbac/insured_cannot_touch_other_policy_graph
        """
        cc = create_class_code()
        pol_a = create_policy("WC-R4A", [cc["id"]],
                              estimated_annual_premium_cents=2000000,
                              minimum_premium_cents=100000)
        pol_b = create_policy("WC-R4B", [cc["id"]],
                              estimated_annual_premium_cents=2000000,
                              minimum_premium_cents=100000)
        auditor = create_auditor()
        run_selection()
        wo_b = find_work_order(pol_b["id"])
        get_success_data(api.assign_work_order(
            wo_b["id"], {"auditor_id": auditor["id"]}, MANAGER))
        get_success_data(api.create_records_request(
            wo_b["id"], {"request_type": "PAYROLL_SUMMARY"}, MANAGER))
        ctx = {
            "work_order": wo_b,
            "auditor_headers": make_auditor_headers(auditor["id"]),
        }
        appt_b = get_success_data(api.create_appointment(
            wo_b["id"],
            create_appointment_payload(
                expected_work_order_version=wo_version(ctx)),
            ctx["auditor_headers"]))

        resp = api.confirm_appointment(appt_b["id"],
                                       make_insured_headers(pol_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)

    def test_auditor_cannot_mutate_unassigned_work_order(self, api):
        """PRD: "When `X-User-Role` is `Auditor`, `X-User-ID` is the `id` of
        the acting **Auditor**; an auditor may only mutate child resources of
        work orders whose `assigned_auditor_id` equals `X-User-ID`, and
        violations are rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."

        Design: Corner/rbac/auditor_cannot_mutate_unassigned_work_order
        """
        ctx = setup_selected_work_order(policy_number="WC-R5",
                                        estimated_annual_premium_cents=2000000,
                                        minimum_premium_cents=100000)
        other_auditor = create_auditor(full_name="Bob Auditor", level="STAFF")
        appt = schedule_appointment(ctx)

        resp = api.complete_appointment(
            appt["id"], make_auditor_headers(other_auditor["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)


class TestSegregationOfDuties:
    def test_sod_approve_estimated_same_manager_rejected(self, api):
        """PRD: "The `AuditManager` who approves an estimated (non-compliance)
        billing must not be the manager who flagged the work order
        non-compliant: the approver's `X-User-ID` must differ from the work
        order's `marked_noncompliant_by_user_id`."
        PRD: "A violation of either rule is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/sod_approve_estimated_same_manager_rejected
        """
        ctx = setup_noncompliant_work_order(policy_number="WC-R6",
                                            marker="mgr-1")

        same = api.approve_estimated(ctx["work_order"]["id"],
                                     make_audit_manager_headers("mgr-1"))
        validate_error(same, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        other = api.approve_estimated(ctx["work_order"]["id"],
                                      make_audit_manager_headers("mgr-2"))
        result = validate_success(other, 200)
        assert result["status"] == "ISSUED"
        assert result["variant"] == "ESTIMATED_NONCOMPLIANCE"

    def test_sod_dispute_review_by_issuer_rejected(self, api):
        """PRD: "And the dispute reviewer must not be the issuer of the
        disputed result: starting review, upholding, or overruling a dispute
        all require the caller's `X-User-ID` to differ from the result's
        `issued_by_user_id`."
        PRD: "A violation of either rule is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/sod_dispute_review_by_issuer_rejected
        """
        ctx = setup_selected_work_order(policy_number="WC-R7",
                                        receive_requests=True)
        submit_draft(ctx)
        issue_result(ctx, clock="2026-08-15T00:00:00Z", issuer="mgr-1")
        dispute = file_dispute(ctx, grounds="CLASSIFICATION_ERROR",
                               clock="2026-08-20T00:00:00Z")

        issuer_review = api.start_review_dispute(
            dispute["id"], make_audit_manager_headers("mgr-1"))
        validate_error(issuer_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        other_review = api.start_review_dispute(
            dispute["id"], make_audit_manager_headers("mgr-2"))
        reviewed = validate_success(other_review, 200)
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["reviewed_by_user_id"] == "mgr-2"
