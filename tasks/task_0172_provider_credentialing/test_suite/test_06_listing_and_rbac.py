"""List endpoints (reverse-reachability) and role-based access control.

Covers corner-design instances from the `endpoints` and `rbac` sections.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    make_system_admin_headers, make_specialist_headers,
    make_medical_director_headers, make_peer_reviewer_headers,
    make_enrollment_coordinator_headers, make_headers,
    ApiErrorId,
    create_org_payload, create_provider_payload, create_credential_item_payload,
    cast_vote_payload,
)
import test_helpers.fixtures as fx

ADMIN = make_system_admin_headers("admin-1")
SPEC = make_specialist_headers("spec-1")
MD = make_medical_director_headers("md-1")
REV2 = make_peer_reviewer_headers("rev-2")
ENR = make_enrollment_coordinator_headers("enr-1")


# =========================================================================
# Listing / reverse-reachability
# =========================================================================
def test_list_credential_items_reverse_reachability():
    """PRD §4 (endpoint table): "GET `/providers/{id}/credential-items` — List a
    provider's credential items".
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_credential_items_reverse_reachability
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(item_type="STATE_LICENSE", identifier="LIC-1"),
        SPEC), 201)
    validate_success(api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(item_type="DEA_REGISTRATION", identifier="DEA-1",
                                       expiration_date="2031-01-01T00:00:00.000Z"),
        SPEC), 201)
    resp = api_client.list_credential_items(provider["id"], SPEC)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert len(data) == 2


def test_list_votes_filtered_by_reviewer_reverse_reachability():
    """PRD §3.5: "Votes may be listed for a file, listed across the system
    filtered by `reviewer_id` or `credentialing_file_id`, or read individually."

    Design: Corner/endpoints/list_votes_filtered_by_reviewer_reverse_reachability
    """
    ctx = fx.setup_file_under_review()
    validate_success(api_client.cast_vote(
        ctx["file"]["id"], cast_vote_payload(ctx["rev2"]["id"], "YES"), REV2), 201)
    resp = api_client.list_votes(MD, params={"reviewer_id": ctx["rev2"]["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1


# =========================================================================
# RBAC
# =========================================================================
def test_enrollment_coordinator_cannot_create_provider():
    """PRD §4 (endpoint table): "POST `/providers` — Create a provider intake
    record — CredentialingSpecialist".
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/enrollment_coordinator_cannot_create_provider
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    resp = api_client.create_provider(create_provider_payload(org["id"]), ENR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_specialist_cannot_finalize_review():
    """PRD §4 (endpoint table): "POST `/credentialing-files/{id}/finalize` —
    Finalize the review with OCC version guard — MedicalDirector".
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/specialist_cannot_finalize_review
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    fx.cast_three_yes_votes(file_id, ctx["chair"], ctx["rev2"], ctx["rev3"])
    file = validate_success(api_client.get_credentialing_file(file_id, MD), 200)
    # CredentialingSpecialist is not authorized to finalize.
    resp = api_client.finalize_file(
        file_id, {"decision": "APPROVE", "expected_credentialing_file_version": file["version"]},
        SPEC)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_missing_user_context_returns_401():
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a
    role the system recognizes, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/rbac/missing_user_context_returns_401
    """
    validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    bogus = make_headers("BogusRole", "x")
    resp = api_client.get_provider("00000000-0000-4000-8000-000000000000", bogus)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)
