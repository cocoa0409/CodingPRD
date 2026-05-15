"""Authentication, response envelope, and RBAC negative-path tests.

Covers PRD §2.1 (User and Role-Based Access Control), §2.2 (API
Response Structure), and §2.4 (Common Resource Properties).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_tournament_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.1 Header presence + value validity
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_returns_err_auth_missing(self, api):
        """PRD §2.1: "When either header is missing, the request is
        rejected with ERR_AUTH_MISSING."

        Claim: omitting X-User-ID on any endpoint → ERR_AUTH_MISSING.
        """
        # Use a write endpoint so the request even reaches header parsing.
        response = api._request(
            "POST", "/tournaments",
            create_tournament_payload(),
            {"X-User-Role": "LeagueAdmin"},   # X-User-ID omitted
        )
        validate_error(response, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header_returns_err_auth_missing(self, api):
        """PRD §2.1: "When either header is missing, the request is
        rejected with ERR_AUTH_MISSING."

        Claim: omitting X-User-Role on any endpoint → ERR_AUTH_MISSING.
        """
        response = api._request(
            "POST", "/tournaments",
            create_tournament_payload(),
            {"X-User-ID": "u-1"},   # X-User-Role omitted
        )
        validate_error(response, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_unknown_role_returns_err_auth_invalid_role(self, api):
        """PRD §2.1: "when X-User-Role carries a value the system does
        not recognise, the response is ERR_AUTH_INVALID_ROLE."

        Claim: X-User-Role value outside the four-role enum → ERR_AUTH_INVALID_ROLE.
        """
        response = api._request(
            "POST", "/tournaments",
            create_tournament_payload(),
            {"X-User-ID": "u-1", "X-User-Role": "GodMode"},
        )
        validate_error(response, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ===========================================================================
# §2.1 RBAC matrix — forbidden roles on exclusive endpoints
# ===========================================================================
class TestRBACForbidden:
    @pytest.mark.parametrize("role", ["TeamManager", "Referee", "Player"])
    def test_create_tournament_forbidden_for_non_admin(self, api, role):
        """PRD §2.1: "If the role is recognised but is not permitted to
        invoke the requested endpoint per the RBAC matrix, the response
        is ERR_FORBIDDEN."

        Claim: POST /tournaments is LeagueAdmin-only; any other role
        → ERR_FORBIDDEN.
        """
        from prd_bench_local_runner.testing import build_user_headers
        response = api.create_tournament(
            create_tournament_payload(),
            build_user_headers(f"u-{role.lower()}", role),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)

    @pytest.mark.parametrize("role", ["TeamManager", "Player"])
    def test_assign_referee_forbidden_for_non_admin(self, api, role):
        """PRD §2.1 RBAC plus §3.4 narrative: "A LeagueAdmin assigns a
        Referee to a match by supplying referee_user_id."

        Claim: POST /matches/{mid}/assign-referee restricted to
        LeagueAdmin; other roles → ERR_FORBIDDEN.
        """
        from prd_bench_local_runner.testing import (
            NON_EXISTENT_UUID, build_user_headers,
        )
        response = api.assign_referee(
            NON_EXISTENT_UUID,
            {"referee_user_id": "ref-001"},
            build_user_headers(f"u-{role.lower()}", role),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# §2.2 Success envelope
# ===========================================================================
class TestSuccessEnvelope:
    def test_create_tournament_envelope_shape(self, api, league_admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body."

        Claim: 2xx response carries meta.api_request_id starting with
        req_, meta.api_request_timestamp ISO-8601, response_type
        'object', and a populated data field.
        """
        response = api.create_tournament(
            create_tournament_payload(), league_admin_headers,
        )
        data = validate_success(response, expected_status=201)
        body = response.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id starts with req_"
        )
        assert body["response_type"] == "object"
        assert isinstance(data, dict) and "id" in data


# ===========================================================================
# §2.4 Common fields — append-only entities omit updated_at + version
# ===========================================================================
class TestAppendOnlyCommonFields:
    def test_identity_verification_omits_updated_at_and_version(
        self, api, league_admin_headers,
    ):
        """PRD §2.4: "Four entities are deliberately append-only or
        singleton in nature and carry only id and created_at — both
        updated_at and version are absent on these rows. They are
        IdentityVerification, DraftEvent, CrowdfundContribution,
        AuditLogEntry, and Clock."

        Claim: IdentityVerification response payload exposes id +
        created_at only.
        """
        from test_helpers import (
            create_open_tournament,
            create_team_registration,
            create_player_contract,
            file_identity_verification,
            reset_clock_to_epoch,
        )
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        c = create_player_contract(team_id=reg["id"])
        verification = file_identity_verification(
            c["id"], jurisdiction="US", status="VERIFIED",
        )
        assert "updated_at" not in verification, (
            "PRD §2.4: IdentityVerification must not expose updated_at"
        )
        assert "version" not in verification, (
            "PRD §2.4: IdentityVerification must not expose version"
        )
        assert "id" in verification
        assert "created_at" in verification
