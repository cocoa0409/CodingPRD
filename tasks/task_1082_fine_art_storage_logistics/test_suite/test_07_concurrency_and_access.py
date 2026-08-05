"""Optimistic concurrency on artwork valuation, RBAC, ownership, and listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_client_headers,
    make_client, make_artwork, make_appraisal, make_policy, make_viewing_room,
    artwork_version,
    appraisal_payload, policy_payload, client_payload, viewing_booking_payload,
    REG, COORD,
    api_client as api,
)


# ==========================================================================
# OCC: stale expected_artwork_version on appraisal / policy creation
# ==========================================================================
def test_appraisal_stale_artwork_version_returns_412():
    """PRD §2.5: "When the submitted `expected_artwork_version` does not equal the
    artwork's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting/appraisal_stale_artwork_version_returns_412
    """
    c = make_client()
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    v1 = artwork_version(a["id"])
    # First appraisal advances the artwork's version past v1.
    get_success_data(api.create_appraisal(
        appraisal_payload(a["id"], v1, method="FAIR_MARKET", comparable_base_cents=1000000), REG))
    resp = api.create_appraisal(
        appraisal_payload(a["id"], v1, method="FAIR_MARKET", comparable_base_cents=900000), REG)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_policy_stale_artwork_version_returns_412():
    """PRD §2.5: "When the submitted `expected_artwork_version` does not equal the
    artwork's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting/policy_stale_artwork_version_returns_412
    """
    c = make_client()
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    v1 = artwork_version(a["id"])
    # First policy advances the artwork's version past v1.
    get_success_data(api.create_policy(
        policy_payload(a["id"], v1, coverage_type="STORAGE_ONLY", insured_value_cents=1000000), REG))
    resp = api.create_policy(
        policy_payload(a["id"], v1, coverage_type="ALL_RISK", insured_value_cents=1200000), REG)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


# ==========================================================================
# RBAC: role restriction
# ==========================================================================
def test_coordinator_cannot_create_client_returns_unauthorized():
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/coordinator_cannot_create_client_returns_unauthorized
    """
    resp = api.create_client(
        client_payload(name="Nope", client_type="INDIVIDUAL", billing_email="n@x.example"), COORD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_client_books_other_clients_artwork_returns_forbidden():
    """PRD §2.1: "A `Client` may create a viewing booking only for its own
    `client_id` and its own artwork."
    PRD §2.1: "only when the referenced client identifier equals `X-User-ID`;
    otherwise the request is rejected with `ERR_OWNERSHIP_REQUIRED` (HTTP 403)."

    Design: Corner/rbac/client_books_other_clients_artwork_returns_forbidden
    """
    self_client = make_client(name="Self", client_type="INDIVIDUAL", billing_email="self@x.example")
    other_client = make_client(name="Other", client_type="INDIVIDUAL", billing_email="other@x.example")
    art = make_artwork(other_client["id"], size_class="SMALL", fragility_class="LOW")
    room = make_viewing_room()
    resp = api.create_viewing_booking(
        viewing_booking_payload(art["id"], room["id"], other_client["id"],
                                scheduled_start="2026-05-02T10:00:00Z",
                                scheduled_end="2026-05-02T11:00:00Z"),
        make_client_headers(self_client["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_REQUIRED.value, 403)


# ==========================================================================
# Listing: filtered artwork list returns an array with pagination meta
# ==========================================================================
def test_artworks_filtered_list_by_client_id():
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.3: "Every list response echoes `limit` and `offset` in `meta` alongside
    `total_count` (the total number of matching records before the page window is
    applied) and `has_more` (true when records remain beyond the current window)."

    Design: Corner/endpoints/artworks_filtered_list_by_client_id
    """
    c = make_client()
    a1 = make_artwork(c["id"], title="L1", size_class="SMALL", fragility_class="LOW")
    a2 = make_artwork(c["id"], title="L2", size_class="SMALL", fragility_class="LOW")
    resp = api.list_artworks(REG, params={"client_id": c["id"]})
    data, meta = validate_paginated(resp)
    ids = {row["id"] for row in data}
    assert a1["id"] in ids and a2["id"] in ids, (ids, a1["id"], a2["id"])
    assert "total_count" in meta and "has_more" in meta, meta
