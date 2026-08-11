"""Authentication header enforcement and role-based access control."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_captive_payload,
    create_program_payload,
    get_captive_version,
    setup_capitalized_captive,
    setup_reserved_claim,
    settle_claim,
    validate_error,
)


class TestAuthentication:

    def test_auth_missing_headers_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID` (the
        acting user's identifier) and `X-User-Role` (the acting user's role). If
        either header is missing or fails validation, the server responds with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/auth_missing_headers_returns_400
        """
        resp = api.create_captive(
            create_captive_payload(captive_name="No Auth"), headers={}
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_unauthorized_role_returns_403(self, api, underwriter_headers):
        """PRD §2.1: "If the role supplied does not have permission to perform
        the requested operation, the server responds with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST | /api/captives | Create a new captive entity |
        CaptiveManager" — an Underwriter cannot create captives.

        Design: Corner/validations/unauthorized_role_returns_403
        """
        resp = api.create_captive(
            create_captive_payload(captive_name="Unauthorized"), underwriter_headers
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestProgramCreationRbac:

    def test_actuary_cannot_create_program(self, api, actuary_headers):
        """PRD §2.1: "If the role supplied does not have permission to perform
        the requested operation, the server responds with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST | /api/captives/{captiveId}/programs | Create an insurance
        program | Underwriter" — an Actuary cannot create programs.

        Design: Corner/rbac/actuary_cannot_create_program
        """
        captive = setup_capitalized_captive()
        payload = create_program_payload(program_name="RBAC Prog")
        payload["expected_captive_version"] = get_captive_version(captive["id"])
        resp = api.create_program(captive["id"], payload, actuary_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_regulator_cannot_create_programs_returns_forbidden(
        self, api, domicile_regulator_headers
    ):
        """PRD §2.1: "If the role supplied does not have permission to perform
        the requested operation, the server responds with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST | /api/captives/{captiveId}/programs | Create an insurance
        program | Underwriter" — a DomicileRegulator cannot create programs.

        Design: Corner/rbac/regulator_cannot_create_programs_returns_forbidden
        """
        captive = setup_capitalized_captive()
        payload = create_program_payload(program_name="RBAC2 Prog")
        payload["expected_captive_version"] = get_captive_version(captive["id"])
        resp = api.create_program(captive["id"], payload, domicile_regulator_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestClaimSettlementRbac:

    def test_board_director_cannot_settle_claims(self, api, board_director_headers):
        """PRD §2.1: "If the role supplied does not have permission to perform
        the requested operation, the server responds with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST | /api/captives/{captiveId}/programs/{programId}/claims/{claimId}/settle | Settle a reserved claim | ClaimsAdjuster"
        — a BoardDirector cannot settle claims.

        Design: Corner/rbac/board_director_cannot_settle_claims
        """
        ctx = setup_reserved_claim(reserve_amount_cents=45000)
        resp = settle_claim(ctx, 45000, headers=board_director_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
