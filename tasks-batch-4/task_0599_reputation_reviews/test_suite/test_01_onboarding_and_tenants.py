"""Tenant onboarding: business defaults, path resolution, listing pages, tenancy."""

from test_helpers import (
    CLOCK_START,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_business,
    assert_instant_equals,
    create_business,
    create_business_payload,
    create_contact_payload,
    create_location,
    make_business_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_business_registration_applies_the_declared_optional_defaults(api, admin_headers):
    """PRD §3.1: "The `plan_tier` is one of `BASIC`, `PRO` or `ENTERPRISE` and defaults
    to `BASIC`."
    PRD §3.1: "The `default_frequency_cap_days` is the per-contact outreach cooldown,
    in whole days, that every campaign of this tenant will honour; it must be at least
    1 and defaults to 30."
    PRD §3.1: "A business also exposes a `location_count`, which the server maintains
    as the number of locations beneath it and which begins at 0."
    PRD §2.4: "`version`, an integer that starts at 1 and increments by one on every
    mutation of that resource."

    Design: Corner/entities/business_create_applies_declared_defaults
    """
    resp = api.create_business(create_business_payload(name="Minimal Co"), admin_headers)
    business = validate_success(resp, 201)
    assert_business(business)

    assert business["plan_tier"] == "BASIC", "plan_tier defaults to BASIC"
    assert business["default_frequency_cap_days"] == 30, "default_frequency_cap_days defaults to 30"
    assert business["location_count"] == 0, "location_count begins at 0"
    assert business["version"] == 1, "version starts at 1"
    assert_instant_equals(business["created_at"], CLOCK_START, "Business.created_at")


def test_reading_an_unknown_location_id_returns_location_not_found(api, admin_headers):
    """PRD §2.9: "Path identifiers are resolved strictly left to right, and the request
    is rejected at the **first** identifier that fails to resolve, with the 404 error
    belonging to that identifier's type: `ERR_BUSINESS_NOT_FOUND`,
    `ERR_LOCATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_RESPONSE_NOT_FOUND`,
    `ERR_ESCALATION_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND` or `ERR_WIDGET_NOT_FOUND`."

    Design: Corner/entities/location_get_with_unknown_id_returns_not_found
    """
    create_business()

    resp = api.get_location(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_LOCATION_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"


def test_contact_list_windows_by_limit_and_offset(api, admin_headers):
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, has a
    minimum of 1 and a maximum of 100. `offset` is the number of items to skip and
    defaults to 0; it must not be negative."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the size of the
    full filtered result set before the window is applied and `has_more` indicates
    whether any items remain beyond the current window."

    Design: Corner/entities/contacts_list_paginates_with_limit_offset
    """
    business = create_business()
    for i in (1, 2, 3):
        resp = api.create_contact(
            business["id"],
            create_contact_payload(full_name=f"E {i}", email=f"e{i}@example.com"),
            admin_headers,
        )
        validate_success(resp, 201)

    resp = api.list_contacts(business["id"], admin_headers, {"limit": 2, "offset": 2})
    rows, meta = validate_paginated(resp)

    assert len(rows) == 1, f"expected the tail row only, got {len(rows)}"
    assert meta["total_count"] == 3, "total_count is the size of the full filtered set"
    assert meta["has_more"] is False, "no items remain beyond offset 2 + limit 2"
    assert meta["limit"] == 2
    assert meta["offset"] == 2


def test_business_owner_reading_another_businesss_location_is_cross_tenant(api):
    """PRD §2.1: "When `X-User-Role` is `BusinessOwner`, `X-User-ID` is the `id` of the
    acting `Business`."
    PRD §2.1: "A mismatch in either case is a tenancy violation and is rejected with
    `ERR_CROSS_TENANT_ACCESS` (403). This check runs on every endpoint whose
    authorized-role list contains `BusinessOwner` or `LocationManager`."

    Design: Corner/validations/business_owner_cannot_touch_another_businesss_location
    """
    business_a = create_business(name="Business A")
    business_b = create_business(name="Business B")
    location_b = create_location(
        business_b["id"],
        name="B Downtown",
        nap_name="B Dental",
        nap_address="2 Main St",
        nap_phone="+15552220000",
    )

    resp = api.get_location(location_b["id"], make_business_owner_headers(business_a["id"]))
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_ACCESS.value)


def test_request_without_the_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID`, which identifies the
    acting principal, and `X-User-Role`, which declares the capacity in which it is
    acting."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of those six
    strings, the request is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    business = create_business()

    resp = api.get_business(business["id"], {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
