"""Auth header presence, role validity, and RBAC enforcement (PRD §2.1, §2.7).

PRD §2.1 prescribes three pre-business checks evaluated in this strict
order: ERR_AUTH_MISSING, then ERR_AUTH_INVALID, then ERR_FORBIDDEN. We
exercise each in isolation so the test pinpoints the priority root cause.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    build_user_headers,
    create_client_payload,
    create_sample_payload,
    create_tester_payload,
    setup_assigned_task,
    setup_completed_task,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Missing header (PRD §2.1 — ERR_AUTH_MISSING)
# ---------------------------------------------------------------------------
class TestAuthMissingHeaders:
    """PRD §2.1: 'Every request to the API MUST carry two headers:
    X-User-ID and X-User-Role. If either header is missing or empty, the
    server rejects the request with ERR_AUTH_MISSING (HTTP 401).'"""

    def test_missing_user_id_returns_auth_missing(self, api):
        """PRD §2.1: 'If either header is missing or empty, the server
        rejects the request with ERR_AUTH_MISSING (HTTP 401).'

        Claim: omitting X-User-ID yields ERR_AUTH_MISSING (401).
        """
        headers = {"X-User-Role": "LabManager"}
        resp = api.create_tester(create_tester_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_returns_auth_missing(self, api):
        """PRD §2.1: 'If either header is missing or empty, the server
        rejects the request with ERR_AUTH_MISSING (HTTP 401).'

        Claim: omitting X-User-Role yields ERR_AUTH_MISSING.
        """
        headers = {"X-User-ID": "anyone"}
        resp = api.create_tester(create_tester_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_returns_auth_missing(self, api):
        """PRD §2.1: 'If either header is missing or empty, the server
        rejects the request with ERR_AUTH_MISSING.'

        Claim: an empty X-User-ID is treated as missing.
        """
        headers = {"X-User-ID": "", "X-User-Role": "LabManager"}
        resp = api.create_tester(create_tester_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ---------------------------------------------------------------------------
# Invalid role (PRD §2.1 — ERR_AUTH_INVALID)
# ---------------------------------------------------------------------------
class TestAuthInvalidRole:
    """PRD §2.1: 'If X-User-Role is present but does not exactly match
    one of the five declared role names — LabClerk, Tester, Reviewer,
    Signatory, LabManager — the request is rejected with ERR_AUTH_INVALID
    (HTTP 401).'"""

    def test_unknown_role_returns_auth_invalid(self, api):
        """Claim: an unknown role string yields ERR_AUTH_INVALID."""
        headers = build_user_headers("u1", "SuperUser")
        resp = api.create_tester(create_tester_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID.value)

    @pytest.mark.parametrize("role", [
        "labmanager", "LABMANAGER", "Lab Manager", "labclerk",
    ])
    def test_case_or_whitespace_variant_role_rejected(self, api, role):
        """PRD §2.1: 'X-User-Role MUST exactly match one of the five
        declared role names.'

        Claim: any case- or whitespace-variant role yields
        ERR_AUTH_INVALID.
        """
        headers = build_user_headers("u1", role)
        resp = api.create_tester(create_tester_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID.value)


# ---------------------------------------------------------------------------
# Forbidden (PRD §2.1 — ERR_FORBIDDEN)
# ---------------------------------------------------------------------------
class TestRoleBasedAccess:
    """PRD §2.1: 'Once the role is recognised, the server checks the
    role-based access matrix for the targeted endpoint; if the role
    lacks permission, the request is rejected with ERR_FORBIDDEN
    (HTTP 403).'"""

    def test_lab_clerk_cannot_create_client(self, api, lab_clerk_headers):
        """PRD §4 endpoint table: POST /clients is LabManager-exclusive.

        Claim: LabClerk attempting to create a client is rejected with
        ERR_FORBIDDEN.
        """
        resp = api.create_client(create_client_payload(), lab_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_lab_clerk_cannot_create_tester(self, api, lab_clerk_headers):
        """PRD §4 endpoint table: POST /testers is LabManager-only.

        Claim: LabClerk creating a tester is ERR_FORBIDDEN.
        """
        resp = api.create_tester(
            create_tester_payload(), lab_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_tester_cannot_create_sample(self, api, tester_fallback_headers):
        """PRD §4 endpoint table: POST /samples is LabClerk-exclusive.

        Claim: Tester attempting to register a sample yields
        ERR_FORBIDDEN.
        """
        # We need a real client_id for the request body to be otherwise
        # syntactically valid; but the RBAC check (priority 3) fires
        # before path/body resolution (priority 4-5).
        resp = api.create_sample(
            create_sample_payload(client_id=NON_EXISTENT_UUID),
            tester_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_lab_manager_cannot_start_task(self, api, lab_manager_headers):
        """PRD §4 endpoint table: POST /tasks/{id}/start is Tester-only.

        Claim: LabManager attempting to start a task is ERR_FORBIDDEN.
        """
        env = setup_assigned_task()
        resp = api.start_task(env["task"]["id"], lab_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_reviewer_cannot_sign_report(self, api):
        """PRD §4 endpoint table: POST /reports/{id}/sign is Signatory-only.

        Claim: Reviewer attempting to sign is ERR_FORBIDDEN.
        """
        from test_helpers import (
            make_reviewer_headers, mint_report, submit_for_review,
            approve_review,
        )
        env = setup_completed_task()
        report = mint_report(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
        )
        submit_for_review(
            report_id=report["id"], tester_id=env["tester"]["id"],
        )
        approve_review(
            report_id=report["id"], reviewer_id=env["reviewer"]["id"],
        )
        resp = api.sign_report(
            report["id"],
            make_reviewer_headers(env["reviewer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Tester self-only read on GET /testers/{id}
# ---------------------------------------------------------------------------
class TestTesterSelfReadScope:
    """PRD §2.1: 'a Tester reading GET /testers/{id} may only read their
    own row (the path id must equal X-User-ID).'"""

    def test_tester_reading_other_tester_is_forbidden(self, api):
        """PRD §2.1: 'a Tester reading GET /testers/{id} may only read
        their own row (the path id must equal X-User-ID).'

        Claim: a Tester accessing another tester's row is rejected.
        """
        from test_helpers import create_tester, make_tester_headers
        t1 = create_tester()
        t2 = create_tester()
        resp = api.get_tester(t2["id"], make_tester_headers(t1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_tester_reading_own_row_succeeds(self, api):
        """PRD §2.1: 'a Tester reading GET /testers/{id} may only read
        their own row (the path id must equal X-User-ID).'

        Claim: a Tester reading their OWN row succeeds.
        """
        from test_helpers import create_tester, make_tester_headers
        t1 = create_tester()
        resp = api.get_tester(t1["id"], make_tester_headers(t1["id"]))
        data = validate_success(resp)
        assert data["id"] == t1["id"]


# ---------------------------------------------------------------------------
# Priority ordering of the three pre-business checks
# (PRD §2.7: 'These three checks are evaluated strictly in this order,
#  before any business validation runs.')
# ---------------------------------------------------------------------------
class TestAuthPriorityOrdering:
    def test_missing_header_beats_invalid_role(self, api):
        """PRD §2.7: 'First come the three auth checks already described:
        header presence (ERR_AUTH_MISSING), role-name validity
        (ERR_AUTH_INVALID), then per-endpoint RBAC (ERR_FORBIDDEN).'

        Claim: when X-User-ID is missing AND X-User-Role is invalid,
        ERR_AUTH_MISSING fires first.
        """
        headers = {"X-User-Role": "Bogus"}
        resp = api.create_tester(create_tester_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_invalid_role_beats_forbidden(self, api):
        """PRD §2.7: 'header presence (ERR_AUTH_MISSING), role-name
        validity (ERR_AUTH_INVALID), then per-endpoint RBAC
        (ERR_FORBIDDEN).'

        Claim: when role is invalid AND endpoint is also out of scope,
        ERR_AUTH_INVALID fires before ERR_FORBIDDEN.
        """
        headers = build_user_headers("u1", "Bogus")
        resp = api.create_tester(create_tester_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID.value)
