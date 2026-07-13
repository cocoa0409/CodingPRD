"""Onboarding, property registration, computed compliance fields, RBAC, listing.

Each test is independent and builds its own state against an empty database.
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    make_landlord_headers,
    create_landlord_payload, create_property_payload,
    assert_property,
    create_landlord, create_property, set_clock,
)


def test_property_creation_returns_201_with_computed_fields(api):
    """PRD §3.1: "A newly registered property begins in registration_status REGISTERED,
    with its money ledger total_fees_paid_cents initialized to 0 and its current_license_id
    unset until a license is later issued."
    PRD §3.1: "At registration the system computes has_lead_risk, setting it to true exactly
    when year_built is earlier than 1978; properties built in 1978 or later carry no lead risk."

    Design: Corner/entities/property_creation_returns_201_with_computed_fields
    """
    landlord = create_landlord(api)
    resp = api.create_property(
        create_property_payload(landlord["id"], street_address="1 New", unit_count=3, year_built=1980),
        make_landlord_headers(landlord["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert_property(data)
    assert data["registration_status"] == "REGISTERED"
    assert data["has_lead_risk"] is False, "year_built 1980 >= 1978 → no lead risk"
    assert data["total_fees_paid_cents"] == 0


def test_property_creation_missing_unit_count_returns_422(api):
    """PRD §3.1: "The unit count must be an integer of at least 1, and the referenced
    landlord must already exist — a missing landlord reference fails with ERR_LANDLORD_NOT_FOUND."
    PRD §2.10: "missing required fields, invalid enum values, or out-of-range numbers (a
    unit_count below 1, a term_years outside 1, 2, or 3, or a duration_minutes that is not
    greater than 0) yield ERR_VALIDATION."

    Design: Corner/entities/property_creation_missing_unit_count_returns_422
    """
    landlord = create_landlord(api)
    payload = {"landlord_id": landlord["id"], "street_address": "2 New", "year_built": 1980}
    resp = api.create_property(payload, make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_property_get_nonexistent_returns_404(api):
    """PRD §2.8: "If a path resource does not exist, the request fails with the not-found
    error naming that specific resource type (for example ERR_PROPERTY_NOT_FOUND or
    ERR_INSPECTION_NOT_FOUND, HTTP 404) before any deeper validation runs."

    Design: Corner/entities/property_get_nonexistent_returns_404
    """
    resp = api.get_property(NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


def test_property_lead_risk_true_for_pre1978(api):
    """PRD §3.1: "At registration the system computes has_lead_risk, setting it to true
    exactly when year_built is earlier than 1978; properties built in 1978 or later carry
    no lead risk."

    Design: Corner/entities/property_lead_risk_true_for_pre1978
    """
    landlord = create_landlord(api)
    prop = create_property(api, landlord["id"], street_address="3 Old", unit_count=2, year_built=1950)
    resp = api.get_property(prop["id"], TEST_USERS["registrar_headers"])
    data = validate_success(resp)
    assert data["has_lead_risk"] is True, "year_built 1950 < 1978 → lead risk"


def test_tenant_cannot_register_property_returns_403(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation according to the authorization rules in this document,
    the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/validations/tenant_cannot_register_property_returns_403
    """
    landlord = create_landlord(api)
    resp = api.create_property(
        create_property_payload(landlord["id"], street_address="10 S", unit_count=3, year_built=1980),
        TEST_USERS["tenant_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_landlord_cannot_register_for_other_landlord_returns_403(api):
    """PRD §2.1: "An ownership violation — an entity-backed actor operating on a resource it
    does not own — is rejected with ERR_FORBIDDEN_OWNERSHIP (HTTP 403)."

    Design: Corner/validations/landlord_cannot_register_for_other_landlord_returns_403
    """
    landlord_a = create_landlord(api, full_name="A", email="a@x.com")
    landlord_b = create_landlord(api, full_name="B", email="b@x.com")
    # Landlord B (X-User-ID == B) tries to register a property owned by A.
    resp = api.create_property(
        create_property_payload(landlord_a["id"], street_address="11 S", unit_count=3, year_built=1980),
        make_landlord_headers(landlord_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "If either header is missing, or X-User-Role does not name a known role,
    the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api.get_property(NON_EXISTENT_UUID, TEST_USERS["unknown_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_list_properties_by_landlord_pagination(api):
    """PRD §3.1: "A landlord may list properties through the portal, optionally narrowing the
    list to their own by supplying a landlord_id filter or narrowing by registration_status;
    a registrar may list across all properties."
    PRD §2.3: "For every list response, the meta object carries the pagination fields limit,
    offset, total_count, and has_more. The total_count reflects the full number of matching
    records before pagination is applied, and has_more is true when records remain beyond the
    current page."

    Design: Corner/endpoints/list_properties_by_landlord_pagination
    """
    landlord = create_landlord(api)
    create_property(api, landlord["id"], street_address="16 A", unit_count=3, year_built=1980)
    create_property(api, landlord["id"], street_address="16 B", unit_count=4, year_built=1990)
    resp = api.list_properties(
        make_landlord_headers(landlord["id"]),
        params={"landlord_id": landlord["id"], "limit": 10, "offset": 0},
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected exactly 2 properties, got {len(data)}"
    assert all(p["landlord_id"] == landlord["id"] for p in data)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
