"""Access control (authentication, role authorization, ownership) and the
paginated listing envelope.

Corner instances: rbac/*, endpoints/list_pickup_requests_pagination_envelope.
"""
from test_helpers import (
    api_client as api,
    validate_error, validate_paginated,
    create_route_payload,
    create_partner, create_vehicle, create_donor, create_request,
    make_donor_headers, TEST_USERS,
)

DRIVER = TEST_USERS["driver_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]


def test_missing_auth_headers_rejected():
    """PRD §2.1: "When either header is missing, or X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_pickup_requests(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_driver_cannot_create_route():
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    invoke the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/driver_cannot_create_route_returns_unauthorized
    """
    partner = create_partner()
    vehicle = create_vehicle(capacity_cf=100)
    res = api.create_route(create_route_payload(vehicle["id"], partner["id"]), DRIVER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_donor_cannot_cancel_other_donors_request():
    """PRD §2.1: "for a pickup request or recurring plan, the resource's
    donor_id must equal X-User-ID ... A mismatch is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/donor_cannot_cancel_other_donors_request
    """
    partner = create_partner()
    donor_a = create_donor()
    donor_b = create_donor()
    request = create_request(donor_a["id"], partner["id"], disposition="DONATION")
    res = api.cancel_pickup(request["id"], make_donor_headers(donor_b["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_list_pickup_requests_pagination_envelope():
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope, where total_count is the number
    of records matching the filter before pagination and has_more indicates
    whether records remain beyond the current page."

    Design: Corner/endpoints/list_pickup_requests_pagination_envelope
    """
    partner = create_partner()
    donor = create_donor()
    donor_headers = make_donor_headers(donor["id"])
    create_request(donor["id"], partner["id"], disposition="DONATION")
    create_request(donor["id"], partner["id"], disposition="HAUL")

    res = api.list_pickup_requests(donor_headers,
                                   params={"donor_id": donor["id"], "limit": 1, "offset": 0})
    assert res.json()["response_type"] == "array"
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
