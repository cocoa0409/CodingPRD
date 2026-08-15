"""Vendor/product catalog onboarding, auth context, and list pagination (PRD §2.1-2.3, §3.1)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_license_position,
    assert_product,
    assert_vendor,
    create_audit_case,
    create_audit_case_payload,
    create_product,
    create_product_payload,
    create_vendor,
    create_vendor_payload,
    get_license_position,
    parse_iso8601,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProductCreation:
    def test_product_creation_auto_creates_license_position(self, api, admin_headers,
                                                            sam_manager_headers):
        """PRD §3.1: "Registering a product automatically creates its LicensePosition
        with all quantities zero, `gap_severity` of `COMPLIANT`, and `position_basis`
        of `SELF_AUDIT`; exactly one position exists per product for the product's
        entire lifetime."

        Design: Corner/entities/product_creation_auto_creates_license_position
        """
        vendor = create_vendor()
        product = create_product(vendor["id"])
        assert_product(product)

        rows = validate_success(
            api.list_license_positions(product["id"], sam_manager_headers), 200)
        assert isinstance(rows, list) and len(rows) == 1, \
            "exactly one LicensePosition exists per product"
        position = rows[0]
        assert_license_position(position)
        assert position["entitled_quantity"] == 0
        assert position["deployed_quantity"] == 0
        assert position["gap_quantity"] == 0
        assert position["gap_severity"] == "COMPLIANT"
        assert position["position_basis"] == "SELF_AUDIT"

    def test_product_get_not_found_returns_404(self, api, sam_manager_headers):
        """PRD §3.1: "The catalog can be browsed as a list (optionally filtered by
        `vendor_id`) or fetched individually; unknown vendor or product identifiers
        surface as `ERR_VENDOR_NOT_FOUND` or `ERR_PRODUCT_NOT_FOUND`."

        Design: Corner/entities/product_get_not_found_returns_404
        """
        resp = api.get_product(NON_EXISTENT_UUID, sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)


class TestVendorOnboarding:
    def test_vendor_default_response_deadline_applied(self, api, admin_headers,
                                                      legal_counsel_headers):
        """PRD §3.1: "Each vendor also carries `notice_response_deadline_days`, the
        number of days the customer has to respond to an audit notice; it defaults
        to 30 when omitted and must be a positive integer."
        PRD §3.5: "The case's `response_deadline_on` is computed once at creation as
        `notice_received_on` plus the vendor's `notice_response_deadline_days` days."

        Design: Corner/entities/vendor_default_response_deadline_applied
        """
        resp = api.create_vendor(create_vendor_payload(), admin_headers)
        vendor = validate_success(resp, 201)
        assert_vendor(vendor)
        assert vendor["notice_response_deadline_days"] == 30, \
            "notice_response_deadline_days defaults to 30 when omitted"

        case = validate_success(
            api.create_audit_case(
                create_audit_case_payload(
                    vendor["id"], notice_received_on="2026-08-01T00:00:00Z"),
                legal_counsel_headers),
            201)
        deadline = parse_iso8601(case["response_deadline_on"])
        assert deadline == datetime(2026, 8, 31, tzinfo=timezone.utc), \
            "notice 2026-08-01 plus 30 days lands on 2026-08-31"

    def test_vendor_create_client_supplied_id_input_ignored(self, api, admin_headers):
        """PRD §2.5: "Request payloads that carry unknown fields — including
        client-supplied `id`, `version`, or `created_at` — are not rejected on that
        account; the unknown fields are simply ignored."

        Design: Corner/entities/vendor_create_client_supplied_id_input_ignored
        """
        payload = create_vendor_payload(
            id="11111111-1111-1111-1111-111111111111", version=99)
        resp = api.create_vendor(payload, admin_headers)
        vendor = validate_success(resp, 201)
        assert_vendor(vendor)
        assert vendor["id"] != "11111111-1111-1111-1111-111111111111", \
            "the server mints its own UUID id"
        assert vendor["version"] != 99, \
            "the client-supplied version is ignored, not echoed"

    def test_duplicate_vendor_code_rejected(self, api, admin_headers):
        """PRD §3.1: "Vendor codes are unique across the entire catalog: registering
        a vendor whose `vendor_code` is already taken is rejected with
        `ERR_DUPLICATE_VENDOR_CODE`."

        Design: Corner/validations/duplicate_vendor_code_rejected
        """
        first = validate_success(api.create_vendor(create_vendor_payload(
            name="Vendor A", vendor_code="VND-A",
            default_license_metric="PER_INSTALL"), admin_headers), 201)
        assert_vendor(first)

        resp = api.create_vendor(create_vendor_payload(
            name="Vendor A Clone", vendor_code="VND-A",
            default_license_metric="PER_USER"), admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VENDOR_CODE)

    def test_vendor_id_not_found_on_product_create(self, api, admin_headers):
        """PRD §3.1: "unknown vendor or product identifiers surface as
        `ERR_VENDOR_NOT_FOUND` or `ERR_PRODUCT_NOT_FOUND`."
        PRD §2.10: "Existence — path identifiers are validated left to right, then
        body-referenced identifiers such as `vendor_id`, `product_id`,
        `audit_case_id`, `covered_scope_item_ids`, and `target_deployment_ids`,
        each yielding the resource-specific not-found error from §5."

        Design: Corner/errors/vendor_id_not_found_on_product_create
        """
        resp = api.create_product(
            create_product_payload(NON_EXISTENT_UUID), admin_headers)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_FOUND)


class TestAuthContext:
    def test_missing_user_context_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the system
        does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/rbac/missing_user_context_header_unauthenticated
        """
        resp = api.create_vendor(create_vendor_payload(), {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Role header present but user id missing is equally unauthenticated.
        resp2 = api.create_vendor(create_vendor_payload(),
                                  {"X-User-Role": "SAMPlatformAdmin"})
        validate_error(resp2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestListPagination:
    def test_list_pagination_limit_offset(self, api, admin_headers, sam_manager_headers):
        """PRD §2.3: "List endpoints paginate through two query parameters. `limit`
        caps the number of items returned: when not provided it defaults to 10, and
        it accepts a minimum of 1 and a maximum of 100. `offset` skips a number of
        items from the beginning of the result set and defaults to 0."
        PRD §2.3: "List responses include the following pagination fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/endpoints/list_pagination_limit_offset
        """
        vendor = create_vendor()
        p1 = create_product(vendor["id"], name="Prod 1", unit_list_price_cents=10000,
                            support_rate_pct=0.22)
        p2 = create_product(vendor["id"], name="Prod 2", unit_list_price_cents=5000,
                            support_rate_pct=0.2)

        page1, meta1 = validate_paginated(
            api.list_products(sam_manager_headers, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1, "limit=1 returns exactly one row"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_products(sam_manager_headers, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1, "offset=1 with limit=1 returns the remaining row"
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], "the two pages are disjoint"
        assert {page1[0]["id"], page2[0]["id"]} == {p1["id"], p2["id"]}
