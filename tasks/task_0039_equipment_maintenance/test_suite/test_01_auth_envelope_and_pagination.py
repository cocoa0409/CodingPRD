"""Auth headers, response envelope, RBAC, and pagination."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_site,
    create_site_payload,
    create_template,
    create_template_payload,
    setup_pending_workorder,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# 2.1 — auth header presence
# ---------------------------------------------------------------------------
def test_missing_user_id_header_returns_unauthenticated(api):
    """PRD §2.1: 'Every request must carry two headers: X-User-ID and
    X-User-Role. If either is missing or empty, the request is rejected
    with ERR_UNAUTHENTICATED and HTTP 401.'

    Claim: missing X-User-ID → ERR_UNAUTHENTICATED 401.
    """
    res = api.create_site(
        create_site_payload(),
        {"X-User-Role": "SiteManager"},  # X-User-ID absent
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_missing_user_role_header_returns_unauthenticated(api):
    """PRD §2.1: 'Every request must carry two headers: X-User-ID and
    X-User-Role. If either is missing or empty, the request is rejected
    with ERR_UNAUTHENTICATED and HTTP 401.'

    Claim: missing X-User-Role → ERR_UNAUTHENTICATED 401.
    """
    res = api.create_site(
        create_site_payload(),
        {"X-User-ID": "anyone"},  # X-User-Role absent
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_empty_user_id_header_returns_unauthenticated(api):
    """PRD §2.1: 'If either is missing or empty, the request is rejected
    with ERR_UNAUTHENTICATED and HTTP 401.'

    Claim: empty X-User-ID → ERR_UNAUTHENTICATED 401.
    """
    res = api.create_site(
        create_site_payload(),
        {"X-User-ID": "", "X-User-Role": "SiteManager"},
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ---------------------------------------------------------------------------
# 2.1 — RBAC role permission
# ---------------------------------------------------------------------------
def test_create_site_requires_site_manager_role(api,
                                                 plan_owner_headers,
                                                 dispatcher_headers,
                                                 storekeeper_headers,
                                                 technician_headers_fallback):
    """PRD §2.1 + §4: only SiteManager may invoke POST /sites. Other roles
    'is rejected with ERR_FORBIDDEN and HTTP 403.'

    Claim: every non-SiteManager role hitting POST /sites → ERR_FORBIDDEN 403.
    """
    for headers in (plan_owner_headers, dispatcher_headers,
                    storekeeper_headers, technician_headers_fallback):
        res = api.create_site(create_site_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_template_creation_requires_plan_owner(api,
                                                site_manager_headers,
                                                dispatcher_headers,
                                                storekeeper_headers):
    """PRD §4: 'POST /sites/:site_id/templates ... Authorized Role(s):
    PlanOwner.'

    Claim: non-PlanOwner roles hitting POST /templates → ERR_FORBIDDEN.
    """
    site = create_site()
    for headers in (site_manager_headers, dispatcher_headers,
                    storekeeper_headers):
        res = api.create_template(
            site["id"], create_template_payload(), headers,
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------------
# 2.2 — response envelope
# ---------------------------------------------------------------------------
def test_success_response_envelope(api, site_manager_headers):
    """PRD §2.2: success envelope carries
    meta.api_request_id (starting with 'req_'),
    meta.api_request_timestamp (ISO 8601 UTC with three fractional digits),
    response_type ('object' or 'array'), and a data payload.
    """
    res = api.create_site(create_site_payload(), site_manager_headers)
    body = res.json()
    assert "meta" in body
    assert body["meta"]["api_request_id"].startswith("req_"), \
        "PRD §2.2: api_request_id starts with 'req_'"
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] in ("object", "array")
    assert "data" in body


def test_error_response_envelope(api):
    """PRD §2.2: error envelope carries data.error_id and data.message.
    """
    res = api.create_site(
        create_site_payload(),
        {"X-User-Role": "SiteManager"},  # missing X-User-ID
    )
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["error_id"], str) \
        and body["data"]["error_id"]
    assert isinstance(body["data"]["message"], str)


# ---------------------------------------------------------------------------
# 2.3 — pagination
# ---------------------------------------------------------------------------
def test_pagination_defaults_and_meta(api, dispatcher_headers,
                                       site_manager_headers):
    """PRD §2.3: 'List endpoints accept two query parameters, limit and
    offset. The default limit is 10, the minimum is 1, the maximum is 100;
    values outside this range are rejected with ERR_BAD_REQUEST. The
    default offset is 0 and must be non-negative.' meta carries
    total_count and has_more, where 'has_more is true precisely when
    offset + limit < total_count.'
    """
    bag = setup_pending_workorder()
    site_id = bag["site"]["id"]
    # Create one more so we have at least 2.
    eq2_template = bag["template"]
    # Listing should return at least the one WO created above.
    res = api.list_work_orders(site_id, dispatcher_headers)
    data, meta = validate_paginated(res)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] >= 1
    assert meta["has_more"] is (meta["offset"] + meta["limit"]
                                 < meta["total_count"])


def test_pagination_invalid_limit_below_minimum(api, dispatcher_headers):
    """PRD §2.3: 'values outside this range are rejected with
    ERR_BAD_REQUEST.' Lower bound is 1.
    """
    bag = setup_pending_workorder()
    res = api.list_work_orders(
        bag["site"]["id"], dispatcher_headers, params={"limit": 0},
    )
    validate_error(res, "ERR_BAD_REQUEST", expected_status=400)


def test_pagination_invalid_limit_above_maximum(api, dispatcher_headers):
    """PRD §2.3: 'the maximum is 100; values outside this range are
    rejected with ERR_BAD_REQUEST.'
    """
    bag = setup_pending_workorder()
    res = api.list_work_orders(
        bag["site"]["id"], dispatcher_headers, params={"limit": 101},
    )
    validate_error(res, "ERR_BAD_REQUEST", expected_status=400)


def test_pagination_negative_offset_rejected(api, dispatcher_headers):
    """PRD §2.3: 'The default offset is 0 and must be non-negative.'
    """
    bag = setup_pending_workorder()
    res = api.list_work_orders(
        bag["site"]["id"], dispatcher_headers, params={"offset": -1},
    )
    validate_error(res, "ERR_BAD_REQUEST", expected_status=400)


# ---------------------------------------------------------------------------
# 2.6 — site-scoped path validation
# ---------------------------------------------------------------------------
def test_path_validation_left_to_right_unknown_site(api,
                                                     site_manager_headers):
    """PRD §2.6: 'Path segments are validated left to right: if :site_id
    does not exist, the response is ERR_NOT_FOUND with HTTP 404 regardless
    of subsequent segments.'
    """
    res = api.get_equipment(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, site_manager_headers,
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_path_validation_unknown_equipment_within_site(api,
                                                        site_manager_headers):
    """PRD §2.6: 'if the site exists but :equipment_id ... does not exist
    within that site, the response is again ERR_NOT_FOUND.'
    """
    site = create_site()
    res = api.get_equipment(site["id"], NON_EXISTENT_UUID,
                             site_manager_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
