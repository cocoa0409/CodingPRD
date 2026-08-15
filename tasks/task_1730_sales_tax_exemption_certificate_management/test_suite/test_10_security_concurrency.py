"""Authentication context, RBAC denials, tenant isolation, and the two
optimistic-concurrency points."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    USER_IDS,
    add_exemption_reason,
    begin_remediation,
    create_certificate_draft,
    create_customer,
    create_manual_remediation,
    create_onboarded_customer,
    create_order_payload,
    create_tenant,
    drive_certificate_to_under_review,
    setup_campaign_with_failed_sample,
    setup_tenant_config,
    upload_version,
    get_success_data,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["tenant_admin_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
AUD1 = TEST_USERS["auditor_headers"]
CLERK = TEST_USERS["order_clerk_headers"]
FULFILL = TEST_USERS["fulfillment_clerk_headers"]


class TestAuthenticationContext:
    @pytest.mark.parametrize("headers", [
        {},                                                   # neither header
        {"X-User-Role": "TenantAdmin"},                       # missing X-User-ID
        {"X-User-ID": "u_admin"},                             # missing X-User-Role
    ], ids=["no-headers", "missing-user-id", "missing-role"])
    def test_missing_user_context_header(self, api, headers):
        """PRD §2.1: "A request missing either header, or carrying a malformed header value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_context_header
        """
        res = api.get_tenant(NON_EXISTENT_UUID, headers)
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)


class TestTenantIsolation:
    def test_cross_tenant_path_reference_rejected(self, api, order_clerk_headers):
        """PRD §2.6: "For any endpoint whose path contains multiple resource identifiers, the system validates identifiers strictly left to right. The request is rejected immediately with a 404 carrying `ERR_NOT_FOUND` at the first path identifier that does not resolve to a live record inside the tenant scope; later segments are not examined."

        Design: Corner/validations/cross_tenant_reference_rejected
        """
        t1 = create_tenant(legal_name="T1")
        t2 = create_tenant(legal_name="T2", home_state_code="CA")
        add_exemption_reason(t1["id"], code="RES", requires_certificate=False,
                             allowed_form_types=[])
        cust_in_t1 = create_customer(t1["id"], external_ref="C1")
        # The customer id belongs to tenant T1 and cannot resolve inside T2's scope.
        res = api.create_order(
            t2["id"], cust_in_t1["id"],
            create_order_payload(order_ref="O", ship_to_state="CA",
                                 exemption_reason_code="RES"),
            order_clerk_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestRbacDenials:
    def test_auditor_cannot_approve_certificate(self, api, auditor_headers):
        """PRD §2.1: "A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/tenants/{tid}/certificates/{id}/approve` | Approve a certificate; requires the parent customer's version | ComplianceOfficer |"

        Design: Corner/endpoints/auditor_cannot_approve_certificate
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        cert = drive_certificate_to_under_review(tenant["id"], cust["id"])
        cust_v = get_success_data(api.get_customer(tenant["id"], cust["id"], CO1))["version"]
        res = api.approve_certificate(
            tenant["id"], cert["id"], {"expected_customer_version": cust_v}, auditor_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_order_clerk_cannot_advance_clock(self, api, order_clerk_headers):
        """PRD §2.1: "A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/tenants/{tid}/_clock/advance_day` | Advance the tenant's logical clock by a number of days | TenantAdmin |"

        Design: Corner/endpoints/order_clerk_cannot_advance_clock
        """
        tenant = create_tenant(legal_name="T1")
        res = api.advance_day(tenant["id"], {"days": 1}, order_clerk_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_fulfillment_clerk_cannot_open_audit_campaign(self, api, fulfillment_clerk_headers):
        """PRD §2.1: "A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/tenants/{tid}/audit_campaigns` | Create an AuditCampaign in DRAFT | Auditor |"

        Design: Corner/endpoints/fulfillment_clerk_cannot_open_audit_campaign
        """
        tenant = create_tenant(legal_name="T1")
        res = api.create_audit_campaign(
            tenant["id"],
            {"name": "X", "population_state_filter": [],
             "sampling_method": "FIXED_FLOOR", "floor_sample_size": 1},
            fulfillment_clerk_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)


class TestOptimisticConcurrency:
    def test_occ_stale_customer_version_on_approve(self, api, compliance_officer_2_headers):
        """PRD §2.8: "Approving a certificate requires `expected_customer_version` in the request body, carrying the client's last-observed `version` of the certificate's parent `Customer`. A mismatch — for example because another writer has since approved a different certificate for the same customer, legitimately advancing the customer's version by recomputing its standing — is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a standing it has not observed."

        Design: Corner/errors/occ_stale_customer_version
        """
        tenant = setup_tenant_config()
        cust = create_customer(tenant["id"], external_ref="C1")
        stale_version = cust["version"]  # captured before onboarding completes
        get_success_data(api.complete_onboarding(tenant["id"], cust["id"], CO1))
        cert = drive_certificate_to_under_review(tenant["id"], cust["id"])
        res = api.approve_certificate(
            tenant["id"], cert["id"], {"expected_customer_version": stale_version},
            compliance_officer_2_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_stale_campaign_version_on_remediate(self, api, compliance_officer_headers):
        """PRD §2.8: "Resolving a remediation action requires `expected_campaign_version` in the request body, carrying the client's last-observed `version` of the parent `AuditCampaign`. A mismatch — for example because another auditor has since initiated resampling, legitimately advancing the campaign's version — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_campaign_version_on_remediate
        """
        bundle = setup_campaign_with_failed_sample()
        tid = bundle["tenant"]["id"]
        # Version captured at campaign creation; open/sample/remediation have
        # advanced it since (every mutation increments version, PRD §2.5).
        stale_version = bundle["campaign"]["version"]
        action = create_manual_remediation(tid, bundle["sample"]["id"],
                                           action_type="WAIVE_SAMPLE",
                                           assigned_to_user_id=USER_IDS["COMPLIANCE_OFFICER"])
        begin_remediation(tid, action["id"], CO1)
        res = api.resolve_remediation_action(
            tid, action["id"], {"expected_campaign_version": stale_version},
            compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
