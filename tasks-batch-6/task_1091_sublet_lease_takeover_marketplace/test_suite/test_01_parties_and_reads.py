"""Party onboarding, read/not-found, and list-envelope corner cases."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_landlord_payload, create_applicant_payload,
    create_lease_payload, make_landlord_headers,
    new_landlord, new_leaseholder, assert_landlord,
)


def test_create_landlord_returns_201_with_object_envelope(api):
    """PRD §4: "Operations that create a new, stand-alone resource return `201 Created`."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increments by 1
    on every mutation."

    Design: Corner/entities/create_landlord_returns_201_with_envelope
    """
    resp = api.create_landlord(create_landlord_payload(name="Ada", email="ada@x.com"),
                               TEST_USERS["admin_headers"])
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object", "single-resource create must be response_type object"
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"
    assert_landlord(data)


def test_get_lease_not_found_returns_404(api):
    """PRD §2.9: "every id in the path or body must resolve to an existing resource,
    checked left-to-right; the first unresolved id yields its specific not-found error (404)."

    Design: Corner/entities/get_lease_not_found_returns_404
    """
    resp = api.get_lease(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_FOUND.value)


def test_create_applicant_missing_income_returns_validation(api):
    """PRD §2.9: "Malformed bodies, missing required fields, and type or range
    violations surface as `ERR_VALIDATION` (HTTP 400) and are caught alongside the
    structural checks above."

    Design: Corner/entities/create_applicant_missing_income_returns_validation
    """
    payload = {"name": "No Income", "email": "ni@x.com", "credit_score": 700}
    resp = api.create_applicant(payload, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_list_leases_pagination_shape(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_leases_pagination_shape
    """
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    payload = create_lease_payload(landlord["id"], leaseholder["id"])
    validate_success(api.create_lease(payload, make_landlord_headers(landlord["id"])), 201)

    resp = api.list_leases(TEST_USERS["admin_headers"], params={"landlord_id": landlord["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array", "list must be response_type array"
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, "single-item page must have has_more False"
