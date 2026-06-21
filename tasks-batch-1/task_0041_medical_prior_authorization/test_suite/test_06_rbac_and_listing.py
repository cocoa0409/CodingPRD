"""Role-based access control and list/pagination envelope behavior.

Translates queue B (rbac, endpoints) instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    register_actors,
    set_clock,
    create_under_review_request,
    create_draft_request,
    create_tier3_open_appeal,
    make_provider_headers,
    make_payer_headers,
)


# --------------------------------------------------------------------------
# rbac (queue B)
# --------------------------------------------------------------------------

def test_provider_cannot_render_review_decision(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." The endpoint table authorizes only `Payer` for
    POST `/review-decisions`.

    Design: Corner/rbac/provider_cannot_render_review_decision
    """
    actors = register_actors()
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    ur = create_under_review_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    resp = api.create_review_decision(
        {"request_id": ur["id"], "reviewer_id": actors["reviewer"]["id"],
         "outcome": "APPROVE", "approved_units": 1, "rationale": "OK"},
        make_provider_headers(actors["provider"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_payer_cannot_external_decide_tier3(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." The endpoint table authorizes only
    `ExternalReviewer` for POST `/appeals/{id}/external-decide`.

    Design: Corner/rbac/payer_cannot_external_decide_tier3
    """
    actors = register_actors()
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    denied, appeal_t3 = create_tier3_open_appeal(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    resp = api.external_decide_appeal(
        appeal_t3["id"], {"decision": "OVERTURNED", "decision_rationale": "trying as payer"},
        make_payer_headers(actors["payer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "When either header is missing or malformed on a protected
    endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_authorization_requests(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --------------------------------------------------------------------------
# listing / pagination (queue B)
# --------------------------------------------------------------------------

def test_list_authorization_requests_pagination_envelope(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope." PRD §2.2: "The
    `response_type` is either "object" for a single resource or "array" for a list
    of resources."

    Design: Corner/endpoints/list_authorization_requests_pagination_envelope
    """
    actors = register_actors(with_reviewer=False)
    create_draft_request(
        actors, request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                                   "requested_units": 1, "unit_cost_cents": 5000}
    )
    resp = api.list_authorization_requests(
        make_provider_headers(actors["provider"]["id"]), params={"limit": 10, "offset": 0}
    )
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1, f"expected at least 1 request, got {meta['total_count']}"
    assert meta["has_more"] is False, f"one request fits in limit 10, has_more should be False"


def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. ... A `limit` or
    `offset` outside these bounds is rejected with `ERR_PAGINATION_INVALID`
    (HTTP 400)."

    Design: Corner/endpoints/pagination_limit_over_max_rejected
    """
    actors = register_actors(with_reviewer=False)
    resp = api.list_authorization_requests(
        make_provider_headers(actors["provider"]["id"]), params={"limit": 101, "offset": 0}
    )
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)
