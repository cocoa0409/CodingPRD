"""Access control, pagination, existence, and required-field validation.

All corner-queue (breadth) coverage over the RBAC / endpoints / entities surface.
"""
from test_helpers import (
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
    make_curb_planner_headers,
    make_permittee_headers,
    advance_clock,
    make_policy,
    make_zone,
    make_permittee,
    create_zone_payload,
)


def test_request_without_known_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    resp = api.list_zones(headers={}, params=None)  # no X-User-Role / X-User-ID
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_permittee_cannot_create_zone(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/permittee_cannot_create_zone
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    permittee = make_permittee(api)
    resp = api.create_zone(
        create_zone_payload(policy["id"], name="Zx"),
        make_permittee_headers(permittee["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_permit_create_missing_designation_rejected(api):
    """PRD §2.9: "A required body field that is entirely absent is reported as
    ERR_MISSING_FIELD (HTTP 422)."

    Design: Corner/endpoints/permit_create_missing_required_field
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    permittee = make_permittee(api)
    resp = api.create_permit(
        {"permittee_id": permittee["id"], "purpose": "d", "zone_ids": []},  # requested_designation absent
        make_permittee_headers(permittee["id"]))
    validate_error(resp, ApiErrorId.ERR_MISSING_FIELD)


def test_list_zones_pagination_envelope_defaults(api):
    """PRD §2.3: "Each list response echoes limit, offset, total_count, and has_more inside
    the meta object, where total_count reflects the full number of matching resources
    before the page window is applied and has_more is true exactly when unreturned matches
    remain beyond the current page."

    Design: Corner/endpoints/list_zones_pagination_defaults
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    make_zone(api, policy["id"], name="Z1")
    make_zone(api, policy["id"], name="Z2", block_face="OAK-200", length_meters=8,
              designation="TNC", capacity_slots=2)
    resp = api.list_zones(make_curb_planner_headers("planner1"))
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_list_zones_limit_above_max_rejected(api):
    """PRD §2.3: "A limit below 1 or above 100, or a negative offset, is rejected with
    ERR_INVALID_PAGINATION (HTTP 422)."

    Design: Corner/endpoints/list_zones_invalid_pagination
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    resp = api.list_zones(make_curb_planner_headers("planner1"), params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION)


def test_get_unknown_zone_not_found(api):
    """PRD §2.5: "rejects the request with ERR_NOT_FOUND (HTTP 404) at the first identifier
    that does not resolve to an existing resource."

    Design: Corner/entities/get_zone_not_found
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    resp = api.get_zone(NON_EXISTENT_UUID, make_curb_planner_headers("planner1"))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
