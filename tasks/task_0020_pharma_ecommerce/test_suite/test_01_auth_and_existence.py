"""Authentication, role authorization, path existence, and OCC version checks
for the Pharma E-Commerce Compliance API (PRD §2.1, §2.5, §2.6).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
    ApiErrorId,
    create_platform_payload,
    create_vendor_payload,
    create_drug_payload,
    create_customer_payload,
    create_pharmacist_payload,
    open_pharmacist_review_payload,
    setup_basic_platform,
    setup_otc_purchase_scenario,
    setup_approved_prescription_with_order,
    setup_order_in_review,
    setup_otc_order_in_review,
    create_platform,
    create_vendor,
    create_pharmacist,
    create_customer,
    create_otc_drug_on_shelf,
    create_drug,
    place_order,
    pay_order,
    get_order,
    TEST_USERS,
    make_admin_headers,
    make_customer_headers,
    make_vendor_admin_headers,
    make_prescription_reviewer_headers,
    make_pharmacist_re_reviewer_headers,
    make_pharmacist_headers,
    order_item,
)


# ---------------------------------------------------------------------------
# Missing/malformed auth headers (PRD §2.1)
# ---------------------------------------------------------------------------

class TestMissingAuthHeaders:
    """PRD §2.1: 'Every request must carry two HTTP headers: X-User-ID to
    identify the acting principal, and X-User-Role to declare the operational
    capacity that principal is acting in. Missing, malformed, or empty headers
    cause the request to be rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'
    """

    def test_create_platform_no_headers_rejected(self, api):
        """PRD §2.1: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER when both
        auth headers are absent."""
        resp = api.create_platform(create_platform_payload(),
                                     headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_create_platform_missing_user_id_rejected(self, api):
        """PRD §2.1: missing X-User-ID -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
        resp = api.create_platform(create_platform_payload(),
                                     headers={"X-User-Role": "PlatformAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_create_platform_missing_role_rejected(self, api):
        """PRD §2.1: missing X-User-Role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
        resp = api.create_platform(create_platform_payload(),
                                     headers={"X-User-ID": "admin-1"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: 'Missing, malformed, or empty headers cause the request
        to be rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""
        resp = api.create_platform(create_platform_payload(),
                                     headers={"X-User-ID": "", "X-User-Role": "PlatformAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ---------------------------------------------------------------------------
# Role authorization (PRD §2.1, §4)
# ---------------------------------------------------------------------------

class TestRoleAuthorization:
    """PRD §2.1: 'Once headers are present, the server checks the role against
    the per-endpoint authorization table (see §4); a role that is not on the
    endpoint's whitelist receives ERR_INSUFFICIENT_PERMISSIONS.'
    """

    def test_customer_cannot_create_platform(self, api):
        """PRD §4: POST /pharma-platforms — PlatformAdmin only."""
        resp = api.create_platform(create_platform_payload(),
                                     TEST_USERS["customer_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_customer_cannot_advance_clock(self, api):
        """PRD §4: POST /pharma-platforms/{pid}/_clock/advance — PlatformAdmin only."""
        pf = create_platform(api)
        resp = api.advance_clock(pf["id"], "2025-06-01T00:00:00.000Z",
                                   TEST_USERS["customer_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_customer_cannot_shelve_drug(self, api):
        """PRD §4: POST /drugs/{drugId}/shelve — PlatformAdmin only."""
        pf, vendor = setup_basic_platform(api)
        drug = create_drug(api, pf["id"], vendor["id"])
        resp = api.shelve_drug(pf["id"], drug["id"], TEST_USERS["customer_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_regulatory_cannot_create_vendor(self, api):
        """PRD §4: POST /vendors — PlatformAdmin only."""
        pf = create_platform(api)
        resp = api.create_vendor(pf["id"], create_vendor_payload(),
                                   TEST_USERS["regulatory_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_admin_cannot_pay_order(self, api):
        """PRD §4: POST /orders/{orderId}/pay — Customer only."""
        s = setup_otc_purchase_scenario(api)
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        order = place_order(api, pf["id"], customer,
                              items=[order_item(drug["id"], qty=1, unit_price_cents=1000)])
        resp = api.pay_order(pf["id"], order["id"], TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_customer_cannot_approve_prescription(self, api):
        """PRD §4: POST /prescriptions/{rxId}/approve — PrescriptionReviewer only."""
        s = setup_approved_prescription_with_order(api)
        # Build a fresh REVIEW_PENDING prescription via Customer for this test:
        from test_helpers import upload_prescription, prescription_item
        rx = upload_prescription(api, s["platform"]["id"], s["customer"],
                                   drug_items=[prescription_item(s["drug"]["id"], qty=1)],
                                   issued_at="2025-01-01T00:00:00.000Z",
                                   validity_days=30)
        # Customer attempts approve.
        resp = api.approve_prescription(s["platform"]["id"], rx["id"],
                                          make_customer_headers(s["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------------------------------------------------------------------------
# Resource existence (PRD §2.1, §2.6)
# ---------------------------------------------------------------------------

class TestResourceNotFound:
    """PRD §2.6: 'When a path contains multiple identifiers ... the system
    validates each identifier in the order they appear in the URL,
    left-to-right. The first identifier that does not resolve causes the
    request to be rejected immediately with the corresponding subject-specific
    not-found code.'
    """

    def test_get_platform_not_found(self, api):
        """PRD §2.1: 'ERR_PLATFORM_NOT_FOUND'."""
        resp = api.get_platform(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PLATFORM_NOT_FOUND.value)

    def test_get_drug_not_found(self, api):
        """PRD §2.1: 'ERR_DRUG_NOT_FOUND'."""
        pf = create_platform(api)
        resp = api.get_drug(pf["id"], NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_DRUG_NOT_FOUND.value)

    def test_get_vendor_not_found(self, api):
        """PRD §2.1: 'ERR_VENDOR_NOT_FOUND'."""
        pf = create_platform(api)
        resp = api.get_vendor(pf["id"], NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_FOUND.value)

    def test_get_pharmacist_not_found(self, api):
        """PRD §2.1: 'ERR_PHARMACIST_NOT_FOUND'."""
        pf = create_platform(api)
        resp = api.get_pharmacist(pf["id"], NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PHARMACIST_NOT_FOUND.value)

    def test_get_customer_not_found(self, api):
        """PRD §2.1: 'ERR_CUSTOMER_NOT_FOUND'."""
        pf = create_platform(api)
        resp = api.get_customer(pf["id"], NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)

    def test_get_order_not_found(self, api):
        """PRD §2.1: 'ERR_ORDER_NOT_FOUND'."""
        pf = create_platform(api)
        resp = api.get_order(pf["id"], NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)

    def test_get_prescription_not_found(self, api):
        """PRD §2.1: 'ERR_PRESCRIPTION_NOT_FOUND'."""
        pf = create_platform(api)
        resp = api.get_prescription(pf["id"], NON_EXISTENT_UUID,
                                       TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_FOUND.value)

    def test_get_shipment_not_found(self, api):
        """PRD §2.1: 'ERR_SHIPMENT_NOT_FOUND'."""
        pf = create_platform(api)
        resp = api.get_cold_chain_shipment(pf["id"], NON_EXISTENT_UUID,
                                              TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value)

    def test_get_adr_not_found(self, api):
        """PRD §2.1: 'ERR_REPORT_NOT_FOUND'."""
        pf = create_platform(api)
        resp = api.get_adr(pf["id"], NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND.value)

    def test_left_to_right_validation_platform_first(self, api):
        """PRD §2.6: 'the system validates each identifier in the order they
        appear in the URL, left-to-right. The first identifier that does not
        resolve causes the request to be rejected immediately with the
        corresponding subject-specific not-found code (e.g.,
        ERR_PLATFORM_NOT_FOUND first, then ERR_ORDER_NOT_FOUND, then
        ERR_REVIEW_NOT_FOUND).'

        With both pid and orderId nonexistent, ERR_PLATFORM_NOT_FOUND wins.
        """
        resp = api.get_order(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                               TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PLATFORM_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Optimistic concurrency control (PRD §2.5)
# ---------------------------------------------------------------------------

class TestOptimisticConcurrency:
    """PRD §2.5: 'When a client supplies version, the server compares the
    supplied integer to the row's current version; if they differ, the request
    is rejected with ERR_VERSION_MISMATCH and no state changes. When version
    is omitted, the server processes the mutation without an OCC check.'
    """

    def test_pay_with_stale_version_rejected(self, api):
        """PRD §2.5: version mismatch on a mutation endpoint → ERR_VERSION_MISMATCH."""
        s = setup_otc_purchase_scenario(api)
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        order = place_order(api, pf["id"], customer,
                              items=[order_item(drug["id"], qty=1, unit_price_cents=1000)])
        # PRD §2.5: 'When a client supplies version' — pass an obviously
        # stale version (current row version is 0+; -1 cannot match).
        stale_version = order["version"] + 99
        resp = api.pay_order(pf["id"], order["id"],
                               make_customer_headers(customer["id"]),
                               payload={"version": stale_version})
        validate_error(resp, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_pay_omitting_version_succeeds(self, api):
        """PRD §2.5: 'When version is omitted, the server processes the
        mutation without an OCC check.'
        """
        s = setup_otc_purchase_scenario(api)
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        order = place_order(api, pf["id"], customer,
                              items=[order_item(drug["id"], qty=1, unit_price_cents=1000)])
        # Omit version entirely.
        resp = api.pay_order(pf["id"], order["id"],
                               make_customer_headers(customer["id"]))
        data = validate_success(resp)
        assert data["payment_status"] == "PAID"
