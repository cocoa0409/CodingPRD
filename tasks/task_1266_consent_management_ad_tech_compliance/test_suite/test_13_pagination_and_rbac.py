"""Pagination envelope/defaults, list filters, and role-based access control."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_property, create_visitor,
    create_property_payload, create_vendor_payload, create_tag_audit_scan_payload,
    run_scan_payload,
    make_auditor_headers, build_user_headers,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["privacy_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
ANY = TEST_USERS["any_headers"]
AUD1 = make_auditor_headers("aud-1")


def test_vendors_pagination_defaults(api):
    """PRD section 2.3: "The `limit` parameter specifies the maximum number of
    items to return. If not provided, it defaults to 10, with a minimum of 1 and
    maximum of 100. The `offset` parameter specifies the number of items to skip
    and defaults to 0." and "all list endpoints return resources sorted by their
    creation timestamp in ascending order."

    Design: Corner/endpoints/vendors_pagination_defaults
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    vm = TEST_USERS["vendor_manager_headers"]
    for i in range(1, 12):
        get_success_data(
            api.create_vendor(
                create_vendor_payload(
                    prop["id"], legal_name=f"V{i:02d}",
                    tracker_signatures=[f"v{i:02d}.com"],
                ),
                vm,
            )
        )
    page1, meta1 = validate_paginated(api.list_vendors(ANY, params={"property_id": prop["id"]}))
    assert meta1["total_count"] == 11
    assert len(page1) == 10, "default limit is 10"
    assert meta1["has_more"] is True
    assert page1[0]["legal_name"] == "V01", "created_at ascending"

    page2, meta2 = validate_paginated(
        api.list_vendors(ANY, params={"property_id": prop["id"], "offset": 10})
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert page2[0]["legal_name"] == "V11"


def test_vendors_filter_by_status(api):
    """PRD section 2.3: "List endpoints additionally accept the filter
    parameters named in §3 narratives (for example `property_id`, `status`,
    ...)"; PRD section 3.3: a vendor "begins `PENDING_REVIEW`; only a
    `PrivacyAdmin` may approve it (`PENDING_REVIEW → APPROVED`)".

    Design: Corner/endpoints/vendors_filter_by_status
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    vm = TEST_USERS["vendor_manager_headers"]
    v1 = get_success_data(
        api.create_vendor(create_vendor_payload(prop["id"], legal_name="FA",
                                                tracker_signatures=["fa.com"]), vm)
    )
    get_success_data(
        api.create_vendor(create_vendor_payload(prop["id"], legal_name="FP",
                                                tracker_signatures=["fp.com"]), vm)
    )
    get_success_data(api.approve_vendor(v1["id"], ADMIN))
    data, meta = validate_paginated(
        api.list_vendors(ANY, params={"property_id": prop["id"], "status": "APPROVED"})
    )
    assert meta["total_count"] == 1
    assert data[0]["status"] == "APPROVED"


def test_visitor_cannot_create_vendor(api):
    """PRD section 2.1: "an attempt to perform an action outside the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."
    PRD section 4: "POST | `/v1/vendors` | Register a vendor | VendorManager".

    Design: Corner/rbac/visitor_cannot_create_vendor
    """
    prop = create_property(name="P", sale_share_designation="SELLS_AND_SHARES")
    visitor_headers = build_user_headers("00000000-0000-0000-0000-000000000001", "Visitor")
    res = api.create_vendor(
        create_vendor_payload(prop["id"], legal_name="X", tracker_signatures=["x.com"]),
        visitor_headers,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_privacy_admin_cannot_run_scan(api):
    """PRD section 3.7: "Running the scan (again `ComplianceAuditor`-only, and
    only from `SCHEDULED`, else `ERR_SCAN_NOT_RUNNABLE`)"; PRD section 2.1: "an
    attempt to perform an action outside the caller's designated role is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."

    Design: Corner/rbac/privacy_admin_cannot_run_scan
    """
    prop = create_property(name="P", sale_share_designation="NO_SALE_NO_SHARE")
    scan = get_success_data(
        api.create_tag_audit_scan(create_tag_audit_scan_payload(prop["id"]), AUD1)
    )
    res = api.run_tag_audit_scan(scan["id"], run_scan_payload([]), ADMIN)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_anonymous_cannot_create_property(api):
    """PRD section 2.1: "When `X-User-Role` is `Anonymous`, the caller is
    unauthenticated and may only register new visitor profiles" and "an attempt
    to perform an action outside the caller's designated role is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (403)."

    Design: Corner/rbac/anonymous_cannot_create_property
    """
    res = api.create_property(
        create_property_payload(name="X", sale_share_designation="SELLS_AND_SHARES"), ANON
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_request_missing_auth_headers(api):
    """PRD section 2.1: "Requests missing either header, or carrying an
    unrecognized role, are rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400)."

    Design: Corner/rbac/request_missing_auth_headers
    """
    res = api.list_properties(headers=None)
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
