"""Authentication, role authorization, path existence, and OCC version checks
for the Copyright Licensing API (PRD §2.1, §2.6, §2.7, §2.10).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error,
    ApiErrorId,
    create_rights_holder_payload,
    create_work_payload,
    create_rights_holder,
    create_two_rights_holders,
    create_draft_work,
    create_registered_work,
    setup_effective_license,
    setup_accepted_license,
    submit_work,
    TEST_USERS,
    make_rights_holder_headers,
    make_admin_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# Missing X-User-ID / X-User-Role headers (PRD §2.1, §2.10 priority 1)
# ---------------------------------------------------------------------------

class TestMissingAuthHeaders:
    """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID to
    identify the acting principal and X-User-Role to declare its operational
    capacity. Requests missing either header are rejected with
    ERR_UNAUTHENTICATED."
    """

    def test_create_rights_holder_no_headers_rejected(self, api):
        """PRD §2.1: ERR_UNAUTHENTICATED when both auth headers are absent."""
        resp = api.create_rights_holder(create_rights_holder_payload(),
                                          headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_create_rights_holder_missing_user_id_rejected(self, api):
        """PRD §2.1: missing X-User-ID -> ERR_UNAUTHENTICATED."""
        resp = api.create_rights_holder(create_rights_holder_payload(),
                                          headers={"X-User-Role": "PlatformAdmin"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_create_rights_holder_missing_role_rejected(self, api):
        """PRD §2.1: missing X-User-Role -> ERR_UNAUTHENTICATED."""
        resp = api.create_rights_holder(create_rights_holder_payload(),
                                          headers={"X-User-ID": "admin-001"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# RBAC role authorization (PRD §2.1, §4)
# ---------------------------------------------------------------------------

class TestRoleAuthorization:
    """PRD §2.1: "When the caller's role is not permitted for the targeted
    endpoint per the role matrix in §4, the server responds with
    ERR_FORBIDDEN."
    """

    def test_rights_holder_cannot_emit_external_event(self, api):
        """PRD §4: POST /_events/emit is PlatformAdmin only.
        PRD §2.1: 'a RightsHolder cannot exercise admin-only capabilities such
        as event injection, clock advance, ownership re-verification, or
        audit-log reads.'"""
        # Use shared-constant rights holder headers — this test is role-only,
        # not ownership-gated, so the constant is appropriate.
        resp = api.emit_event({
            "source": "PAYMENT", "event_type": "PAYMENT_RECEIVED",
            "ref_entity": "RoyaltyStatement", "ref_id": NON_EXISTENT_UUID,
            "payload": {"amount_cents": 100},
            "external_event_id": "ext-rejected-1",
        }, TEST_USERS["rights_holder_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_rights_holder_cannot_advance_clock(self, api):
        """PRD §4: POST /_clock/advance is PlatformAdmin only."""
        resp = api.advance_clock("2099-01-01T00:00:00.000Z",
                                  TEST_USERS["rights_holder_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_rights_holder_cannot_read_audit_logs(self, api):
        """PRD §4: GET /audit-logs is PlatformAdmin only.
        PRD §2.1: 'a RightsHolder cannot exercise admin-only capabilities
        such as ... audit-log reads.'"""
        resp = api.list_audit_logs(TEST_USERS["rights_holder_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_admin_cannot_create_work(self, api):
        """PRD §4: POST /works authorised role: RightsHolder only."""
        rh = create_rights_holder(api)
        payload = create_work_payload(primary_owner_id=rh["id"])
        resp = api.create_work(payload, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_admin_cannot_terminate_license(self, api):
        """PRD §4: POST /licenses/{id}/terminate authorised role: RightsHolder only."""
        bundle = setup_effective_license(api)
        # Admin attempts termination — role not permitted (PRD §4 — RightsHolder only).
        resp = api.terminate_license(bundle["license"]["id"], ADMIN_HEADERS,
                                      payload={"version": bundle["license"]["version"]})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_rights_holder_cannot_verify_ownership(self, api):
        """PRD §4: POST /infringement-cases/{id}/verify-ownership is PlatformAdmin only."""
        from test_helpers import create_reported_infringement
        licensor, alleged = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        case = create_reported_infringement(api, work, licensor, alleged)
        # Reporter (a RightsHolder) attempts to self-verify — role-rejected.
        headers = make_rights_holder_headers(licensor["id"])
        resp = api.verify_ownership(case["id"], headers,
                                     payload={"version": case["version"]})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Path-resource existence (PRD §2.6, §2.10 priority 3)
# ---------------------------------------------------------------------------

class TestPathExistence:
    """PRD §2.10: "Path existence — every path-parameter id must resolve to a
    live entity, validated left-to-right per §2.6, otherwise ERR_NOT_FOUND."
    """

    def test_get_work_not_found(self, api):
        """PRD §2.10: ERR_NOT_FOUND when path id does not resolve."""
        resp = api.get_work(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_license_not_found(self, api):
        """PRD §2.10: ERR_NOT_FOUND on missing License."""
        resp = api.get_license(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_contract_not_found(self, api):
        resp = api.get_contract(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_infringement_case_not_found(self, api):
        resp = api.get_infringement_case(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_rights_holder_not_found(self, api):
        resp = api.get_rights_holder(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_nested_royalty_statement_unknown_license(self, api):
        """PRD §2.6: 'the server validates path identifiers strictly left-to-right:
        if the first identifier does not resolve to a live entity the server
        responds with ERR_NOT_FOUND for that identifier without attempting the
        second.'"""
        resp = api.get_royalty_statement(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                          ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# OCC version mismatch (PRD §2.7, §2.10 priority 4)
# ---------------------------------------------------------------------------

class TestOptimisticConcurrency:
    """PRD §2.7: "When version is supplied it must equal the resource's
    current version; if the supplied value disagrees with the stored value
    the server rejects the request with ERR_VERSION_MISMATCH."
    """

    def test_patch_work_with_stale_version_rejected(self, api):
        """PRD §2.7: stale version in PATCH /works -> ERR_VERSION_MISMATCH."""
        rh_a, rh_b = create_two_rights_holders(api)
        work = create_draft_work(api, rh_a)
        # First, mutate the work so its version increments to 2.
        headers = make_rights_holder_headers(rh_a["id"])
        resp = api.patch_work(work["id"],
                                {"title": "First Patch", "version": work["version"]},
                                headers)
        # Now retry with the stale (original) version.
        resp = api.patch_work(work["id"],
                                {"title": "Second Patch", "version": work["version"]},
                                headers)
        validate_error(resp, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_patch_work_omitting_version_skips_check(self, api):
        """PRD §2.7: 'Omitting version skips the concurrency check entirely —
        the mutation proceeds without any version comparison.'"""
        rh_a, _ = create_two_rights_holders(api)
        work = create_draft_work(api, rh_a)
        headers = make_rights_holder_headers(rh_a["id"])
        # Patch without version — must succeed despite no version check.
        resp = api.patch_work(work["id"], {"title": "No Version Provided"}, headers)
        assert resp.status_code == 200, (
            f"PATCH without version should skip OCC and succeed; got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Public rights-chain endpoint exception (PRD §2.1, §3.2)
# ---------------------------------------------------------------------------

class TestPublicRightsChain:
    """PRD §2.1: "The single exception to the authentication requirement is
    the public rights-chain history read, which may be served without headers;
    every other endpoint, including reads, requires both headers."
    PRD §3.2: "Reading the chain is the only operation in the API that does
    not require authentication headers: the rights-chain history of a
    registered work is a public artifact that anyone can fetch."
    """

    def test_rights_chain_readable_without_auth(self, api):
        """PRD §3.2: rights-chain endpoint is publicly readable, no headers required."""
        work, _ = create_registered_work(api)
        resp = api.get_rights_chain(work["id"], headers=None,
                                     params={"limit": 10, "offset": 0})
        assert resp.status_code == 200, (
            f"GET /works/{{id}}/rights-chain must succeed without auth; got {resp.status_code}"
        )
