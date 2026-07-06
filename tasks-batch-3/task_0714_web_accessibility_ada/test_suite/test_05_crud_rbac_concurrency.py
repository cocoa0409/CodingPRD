"""CRUD shape & input validation, listing/pagination, RBAC, OCC stale-version guards,
versioning, and computed-read endpoints.

Covers the entities, endpoints, rbac, and cross_cutting_complexity_layers corner sections.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_organization, assert_site, assert_monitoring_check,
    setup_org_active_sub_site, setup_completed_scan, setup_subscription_past_due,
    create_org, add_site, create_draft_vpat, scan_version,
    create_site_payload, create_scan_payload, create_organization_payload,
    activate_subscription_payload, issue_vpat_payload, build_user_headers,
    TEST_USERS, make_org_admin_headers, NON_EXISTENT_UUID,
)


class TestCreationAndShape:
    def test_create_organization_returns_201_with_fields(self, api, platform_admin_headers):
        """PRD §3.1: "An Organization, created by a PlatformAdmin who supplies the legal_name and
        the primary compliance contact_email."
        PRD §3.1: "Its account_credit_cents is a running credit balance in cents that starts at
        0".

        POST returns 201, echoes the inputs, and defaults account_credit_cents to 0.

        Design: Corner/entities/create_organization_returns_201_with_fields
        """
        res = api.create_organization(
            create_organization_payload(legal_name="Acme", contact_email="a@acme.test"),
            TEST_USERS["platform_admin_headers"])
        org = validate_success(res, 201)
        assert_organization(org)
        assert org["legal_name"] == "Acme"
        assert org["account_credit_cents"] == 0

    def test_get_site_not_found_returns_404(self, api, platform_admin_headers):
        """PRD §2.8: "Every resource referenced by a request — whether named in the URL path or
        carried in the request body — must exist. ... the first reference that does not resolve
        causes the request to be rejected with ERR_RESOURCE_NOT_FOUND (HTTP 404)".

        GET /sites/{nonexistent} -> ERR_RESOURCE_NOT_FOUND.

        Design: Corner/entities/get_site_not_found_returns_404
        """
        res = api.get_site(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_create_site_missing_required_field_returns_422(self, api, org_admin_headers):
        """PRD §2.10: "Required body fields that are absent are rejected with
        ERR_MISSING_REQUIRED_FIELD (HTTP 422)."
        PRD §3.1: "A Site is registered under an organization by an OrgAdmin or PlatformAdmin, who
        supplies the organization_id, the root url, and the audited_page_count".

        POST /sites omitting audited_page_count -> ERR_MISSING_REQUIRED_FIELD.

        Design: Corner/entities/create_site_missing_required_field_returns_422
        """
        org = create_org()
        owner = make_org_admin_headers(org["id"])
        res = api.create_site({"organization_id": org["id"], "url": "https://x.test"}, owner)
        validate_error(res, "ERR_MISSING_REQUIRED_FIELD")

    def test_create_site_page_count_below_one_returns_422(self, api, org_admin_headers):
        """PRD §2.10: "Body fields that are present but carry an unrecognized enum value, an
        out-of-range number, or an otherwise malformed value are rejected with
        ERR_INVALID_FIELD_VALUE (HTTP 422); this covers a bad enum on any enumerated field, an
        audited_page_count below 1".

        audited_page_count=0 violates integer>=1 -> ERR_INVALID_FIELD_VALUE.

        Design: Corner/entities/create_site_page_count_below_one_returns_422
        """
        org = create_org()
        owner = make_org_admin_headers(org["id"])
        res = api.create_site(
            {"organization_id": org["id"], "url": "https://y.test", "audited_page_count": 0}, owner)
        validate_error(res, "ERR_INVALID_FIELD_VALUE")

    def test_scan_bad_enum_wcag_level_returns_422(self, api, audit_engineer_headers):
        """PRD §2.10: "this covers a bad enum on any enumerated field".
        PRD §3.2: "A scan is queued by naming its site_id and a wcag_target_level of A, AA, or
        AAA".

        wcag_target_level=AAAA is not in {A,AA,AAA} -> ERR_INVALID_FIELD_VALUE.

        Design: Corner/entities/scan_bad_enum_wcag_level_returns_422
        """
        org = create_org()
        site = add_site(org["id"], audited_page_count=5)
        res = api.create_scan(
            {"site_id": site["id"], "wcag_target_level": "AAAA"}, TEST_USERS["audit_engineer_headers"])
        validate_error(res, "ERR_INVALID_FIELD_VALUE")

    def test_monitoring_check_create_returns_201_with_checked_at(self, api, audit_engineer_headers):
        """PRD §3.8: "A PlatformAdmin or AuditEngineer records a MonitoringCheck for a site by
        naming the site_id and the number of new accessibility regressions_found during that
        sweep, which must be an integer of at least 0. The server stamps the check's checked_at
        with the logical-clock instant of the sweep."

        POST /monitoring-checks returns 201 with the echoed regressions_found and a checked_at at
        the default clock instant.

        Design: Corner/endpoints/monitoring_check_create_returns_201
        """
        org = create_org()
        site = add_site(org["id"], audited_page_count=5)
        res = api.create_monitoring_check(
            {"site_id": site["id"], "regressions_found": 3}, TEST_USERS["audit_engineer_headers"])
        mc = validate_success(res, 201)
        assert_monitoring_check(mc)
        assert mc["regressions_found"] == 3
        assert mc["checked_at"] == "2026-03-01T00:00:00.000Z"


class TestListingAndPagination:
    def test_list_sites_pagination_envelope(self, api, org_admin_headers):
        """PRD §2.3: "Paginated list responses include the following fields in the meta object of
        the response envelope: limit, offset, total_count, and has_more."
        PRD §2.2: "The response_type is either 'object' for a single resource or 'array' for a
        list of resources."

        GET /sites returns response_type array with total_count 1 and has_more false for one site.

        Design: Corner/entities/list_sites_pagination_envelope_present
        """
        org = create_org()
        owner = make_org_admin_headers(org["id"])
        add_site(org["id"], audited_page_count=5, url="https://l.test")
        data, meta = validate_paginated(api.list_sites(
            owner, params={"organization_id": org["id"], "limit": 10, "offset": 0}))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

    def test_list_sites_invalid_pagination_returns_422(self, api, platform_admin_headers):
        """PRD §2.3: "A limit outside the inclusive range of 1 through 100, or an offset below 0,
        is rejected with ERR_INVALID_PAGINATION (HTTP 422)."

        GET /sites?limit=0 violates the lower bound -> ERR_INVALID_PAGINATION.

        Design: Corner/entities/list_sites_invalid_pagination_returns_422
        """
        res = api.list_sites(TEST_USERS["platform_admin_headers"], params={"limit": 0})
        validate_error(res, "ERR_INVALID_PAGINATION")


class TestRoleBasedAccessControl:
    def test_remediation_vendor_cannot_create_scan(self, api, remediation_vendor_headers):
        """PRD §2.1: "When the headers are valid but the named role is not permitted to perform
        the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
        PRD §4: the POST /compliance/scans row authorizes only AuditEngineer.

        RemediationVendor calling POST /scans -> ERR_FORBIDDEN_ROLE.

        Design: Corner/rbac/remediation_vendor_cannot_create_scan
        """
        org = create_org()
        site = add_site(org["id"], audited_page_count=5)
        res = api.create_scan(
            {"site_id": site["id"], "wcag_target_level": "AA"},
            TEST_USERS["remediation_vendor_headers"])
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_audit_engineer_cannot_create_vpat(self, api, audit_engineer_headers):
        """PRD §2.1: "When the headers are valid but the named role is not permitted to perform
        the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
        PRD §4: the POST /compliance/vpat-reports row authorizes only ComplianceManager.

        AuditEngineer calling POST /vpat-reports -> ERR_FORBIDDEN_ROLE.

        Design: Corner/rbac/audit_engineer_cannot_issue_vpat
        """
        org, sub, site, scan = setup_completed_scan([{"wcag_criterion": "1.4.3", "severity": "CRITICAL"}],
                                                    tier="SCAN", audited_page_count=5)
        res = api.create_vpat_report(
            {"site_id": site["id"], "source_scan_id": scan["id"]},
            TEST_USERS["audit_engineer_headers"])
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_unknown_role_returns_401(self, api):
        """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the recognized
        role names, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        A request whose X-User-Role is an unrecognized name -> ERR_UNAUTHENTICATED.

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        bad_headers = build_user_headers("someone", "NotARole")
        res = api.list_organizations(bad_headers)
        validate_error(res, "ERR_UNAUTHENTICATED")


class TestOptimisticConcurrency:
    def test_stale_scan_version_blocks_vpat_issue(self, api, compliance_manager_headers):
        """PRD §2.7: "Issuing a VPAT report must carry expected_scan_version matching the current
        version of the report's pinned source scan. ... if another writer has advanced the source
        scan's version since the client last read it (for example by re-completing the scan or
        otherwise mutating it), the client's view is stale and the issue is rejected with
        ERR_STALE_SCAN_VERSION (HTTP 412)."

        Issuing with expected_scan_version one behind the live version -> ERR_STALE_SCAN_VERSION.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_scan_version_blocks_vpat_issue
        """
        org, sub, site, scan = setup_completed_scan([{"wcag_criterion": "1.4.3", "severity": "CRITICAL"}],
                                                    tier="SCAN", audited_page_count=5)
        vpat = create_draft_vpat(site["id"], scan["id"])
        sv = scan_version(scan["id"])
        res = api.issue_vpat_report(
            vpat["id"], {"expected_scan_version": sv - 1}, TEST_USERS["compliance_manager_headers"])
        validate_error(res, "ERR_STALE_SCAN_VERSION")

    def test_stale_subscription_version_blocks_activate(self, api, org_admin_headers):
        """PRD §2.7: "Activating a subscription must carry expected_subscription_version matching
        the current version of the target subscription. ... if the subscription's version has
        advanced since the client last read it — for instance because a past-due-then-reactivate
        cycle bumped it — the client's view is stale and the activation is rejected with
        ERR_STALE_SUBSCRIPTION_VERSION (HTTP 412)."

        After ACTIVE->PAST_DUE bumps the version, activating with a version one behind the live
        value -> ERR_STALE_SUBSCRIPTION_VERSION.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_subscription_version_blocks_activate
        """
        org, past_due, site = setup_subscription_past_due(tier="SCAN", audited_page_count=5)
        owner = make_org_admin_headers(org["id"])
        res = api.activate_subscription(
            past_due["id"], {"expected_subscription_version": past_due["version"] - 1}, owner)
        validate_error(res, "ERR_STALE_SUBSCRIPTION_VERSION")

    def test_version_increments_on_scan_start(self, api, audit_engineer_headers):
        """PRD §2.4: "an integer version that begins at 1 and increments by exactly one on every
        mutation that changes the resource."
        PRD §3.2: "Starting a scan advances it from QUEUED to RUNNING ... and advances the scan's
        version."

        A fresh scan is version 1; after start it is version 2.

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_scan_mutation
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=5)
        scan = validate_success(api.create_scan(
            {"site_id": site["id"], "wcag_target_level": "A"}, TEST_USERS["audit_engineer_headers"]), 201)
        assert scan["version"] == 1
        started = validate_success(api.start_scan(scan["id"], TEST_USERS["audit_engineer_headers"]), 200)
        assert started["version"] == 2
