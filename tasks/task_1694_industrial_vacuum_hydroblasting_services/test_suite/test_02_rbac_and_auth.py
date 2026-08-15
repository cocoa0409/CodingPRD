"""Authentication and role-based access control."""
from test_helpers import (
    ApiErrorId,
    create_job_payload,
    create_site_payload,
    get_success_data,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_request_without_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` is missing or does not name
        one of these roles, or whose `X-User-ID` is missing, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_unauthenticated_without_role_header
        """
        resp = api.create_site({"name": "No Auth Inc"}, headers={"Content-Type": "application/json"})
        assert resp.status_code == 401
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestRoleEnforcement:
    def test_field_supervisor_cannot_issue_invoice(
        self, api, field_supervisor_headers, account_manager_headers
    ):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /v1/invoices/{invoiceId}/issue — Authorized Role(s):
        AccountManager.

        Design: Corner/errors/error_field_role_denied_invoice_issue
        """
        from test_helpers import create_invoiced_job
        ctx = create_invoiced_job()
        inv_id = ctx["invoice"]["id"]
        resp = api.issue_invoice(inv_id, field_supervisor_headers)
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        invoice = get_success_data(api.get_invoice(inv_id, account_manager_headers))
        assert invoice["status"] == "DRAFT"

    def test_project_manager_cannot_approve_jha(self, api, project_manager_headers):
        """PRD §3.3: "Approval belongs to a `SafetyManager`."
        PRD §4: POST /v1/jhas/{jhaId}/approve — Authorized Role(s): SafetyManager.
        PRD §2.1: "A request whose role is not authorized for the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_pm_cannot_approve_jha
        """
        from test_helpers import (
            create_jha_payload,
            create_site_with_active_schedule,
            create_job,
        )
        from test_helpers import TEST_USERS
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"])
        jha = get_success_data(
            api.create_jha(create_jha_payload(job["id"]), TEST_USERS["field_supervisor_headers"])
        )
        get_success_data(api.submit_jha(jha["id"], TEST_USERS["field_supervisor_headers"]))
        job_now = get_success_data(api.get_job(job["id"], project_manager_headers))
        resp = api.approve_jha(
            jha["id"], {"expected_job_version": job_now["version"]}, project_manager_headers
        )
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_safety_manager_cannot_generate_invoice(self, api, safety_manager_headers):
        """PRD §3.7: "Invoice generation (`FIELD_COMPLETE` → `INVOICED`, by a
        `ProjectManager`)".
        PRD §2.1: "A request whose role is not authorized for the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_safety_manager_cannot_generate_invoice
        """
        from test_helpers import create_job_field_complete
        ctx = create_job_field_complete()
        resp = api.generate_invoice(ctx["job"]["id"], safety_manager_headers)
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_account_manager_cannot_set_clock(self, api, account_manager_headers):
        """PRD §2.5: "A `PlatformAdmin` advances it through an administrative
        test-driving capability that accepts a `to_iso8601` instant and reports
        the resulting `current_utc`."
        PRD §2.1: "A request whose role is not authorized for the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_account_manager_cannot_set_clock
        """
        resp = api.set_clock("2026-08-02T00:00:00Z", account_manager_headers)
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_compliance_officer_cannot_approve_and_approver_cannot_submit(
        self, api, compliance_officer_headers, environmental_approver_headers,
        account_manager_headers, platform_admin_headers
    ):
        """PRD §3.6: "the `ComplianceOfficer` submits (`DRAFT` → `SUBMITTED`,
        stamping `submitted_by` with the caller's `X-User-ID`), and an
        `EnvironmentalApprover` approves (`SUBMITTED` → `APPROVED`)".
        PRD §2.1: "A request whose role is not authorized for the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_compliance_cannot_approve_and_approver_cannot_submit
        """
        from test_helpers import (
            create_disposal_facility_payload,
            create_waste_profile_payload,
        )
        site = get_success_data(
            api.create_site(create_site_payload(), account_manager_headers)
        )
        facility = get_success_data(
            api.create_disposal_facility(create_disposal_facility_payload(), platform_admin_headers)
        )
        prof1 = get_success_data(
            api.create_waste_profile(
                create_waste_profile_payload(site["id"], facility["id"]),
                compliance_officer_headers,
            )
        )
        prof2 = get_success_data(
            api.create_waste_profile(
                create_waste_profile_payload(
                    site["id"], facility["id"], waste_code="NONHAZ-WW",
                    hazard_class="NON_HAZ", variance_basis="VOLUME",
                ),
                compliance_officer_headers,
            )
        )
        get_success_data(api.submit_waste_profile(prof2["id"], compliance_officer_headers))

        resp_submit = api.submit_waste_profile(prof1["id"], environmental_approver_headers)
        assert resp_submit.status_code == 403
        validate_error(resp_submit, ApiErrorId.ERR_FORBIDDEN.value)

        resp_approve = api.approve_waste_profile(prof2["id"], compliance_officer_headers)
        assert resp_approve.status_code == 403
        validate_error(resp_approve, ApiErrorId.ERR_FORBIDDEN.value)

    def test_field_supervisor_jha_create_and_submit_allowed(
        self, api, field_supervisor_headers, project_manager_headers
    ):
        """PRD §3.3: "A `FieldSupervisor` authors a revision against a `job_id`
        ... Each revision ... enters as `DRAFT`."
        PRD §3.3: "Submitting moves a revision `DRAFT` → `SUBMITTED` and stamps
        `submitted_by` with the caller's `X-User-ID`."

        Design: Corner/rbac/rbac_field_supervisor_jha_draft_and_submit_allowed
        """
        from test_helpers import (
            create_jha_payload,
            create_site_with_active_schedule,
            create_job,
        )
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"])
        create_resp = api.create_jha(create_jha_payload(job["id"], hazards=["ERGONOMIC"]),
                                     field_supervisor_headers)
        jha = validate_success(create_resp, expected_status=201)
        assert jha["status"] == "DRAFT"
        submit_resp = api.submit_jha(jha["id"], field_supervisor_headers)
        submitted = validate_success(submit_resp, expected_status=200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by"] == "fs_1"
