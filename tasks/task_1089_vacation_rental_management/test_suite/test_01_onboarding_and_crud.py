"""Onboarding and CRUD corners: creation defaults, required fields, enums, not-found,
and list pagination envelope.

Every test translates one queue-B (corner) instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId,
    create_owner_payload, create_guest_payload, create_vendor_payload, create_property_payload,
    fixtures,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["property_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]
NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


def test_owner_create_returns_active_version_one(api):
    """PRD §3.1: "A new owner begins in `status` `ACTIVE`".
    PRD §2.4: "an integer `version` that begins at 1 on creation and increments by 1 on each mutation."

    Design: Corner/entities/owner_create_returns_201_with_fields
    """
    resp = api.create_owner(create_owner_payload(legal_name="Acme Owner", default_management_fee_pct=22), ADMIN)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["default_management_fee_pct"] == 22


def test_property_get_nonexistent_returns_not_found(api):
    """PRD §2.6: "every path id and every referenced foreign key resolves to an existing
    resource, validated left-to-right in the order they appear in the path and then the
    body, else `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/property_get_nonexistent_returns_not_found
    """
    resp = api.get_property(NON_EXISTENT, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_booking_missing_check_out_returns_validation(api):
    """PRD §2.6: "required fields present, enum values legal, and numeric ranges satisfied
    (a `rating` between 1 and 5 inclusive, a `cost_cents` that is zero or greater, and a
    `check_out` strictly after `check_in`), else `ERR_VALIDATION` (422)."

    Design: Corner/entities/booking_missing_check_out_returns_validation
    """
    listed = fixtures.create_listed_property(api)
    guest = fixtures.create_guest(api)
    resp = api.create_booking(
        {"property_id": listed["property"]["id"], "guest_id": guest["id"], "check_in": "2026-07-01T00:00:00Z"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_guest_create_defaults_status_and_id_flag(api):
    """PRD §3.1: "either way the payload carries a `full_name`, an `email`, and an optional
    `government_id_verified` flag that defaults to false when omitted. A guest starts
    `UNSCREENED`".

    Design: Corner/entities/guest_create_defaults_status_unscreened
    """
    resp = api.create_guest(create_guest_payload(full_name="Zed"), ANON)
    data = validate_success(resp, 201)
    assert data["status"] == "UNSCREENED", f"expected UNSCREENED, got {data['status']}"
    assert data["government_id_verified"] is False


def test_vendor_invalid_vendor_type_enum_returns_validation(api):
    """PRD §2.6: "required fields present, enum values legal, and numeric ranges satisfied
    (a `rating` between 1 and 5 inclusive, a `cost_cents` that is zero or greater, and a
    `check_out` strictly after `check_in`), else `ERR_VALIDATION` (422)."

    Design: Corner/entities/vendor_invalid_vendor_type_enum_returns_validation
    """
    resp = api.create_vendor({"name": "Bad", "vendor_type": "PLUMBER", "email": "b@x.com"}, PM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_property_list_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the total number of records matching the filter before pagination), and
    `has_more` (true when records remain beyond the current page)."

    Design: Corner/entities/property_list_pagination_envelope
    """
    owner = fixtures.create_owner(api)
    fixtures.create_property(api, owner["id"])
    resp = api.list_properties(PM, params={"owner_id": owner["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False
