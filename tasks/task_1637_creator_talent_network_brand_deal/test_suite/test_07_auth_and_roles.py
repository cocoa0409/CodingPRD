"""Authentication context and role authorization (PRD §2.1, §4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_brand_payload,
    make_headers_without_role,
    validate_error,
)

TM = TEST_USERS["talent_manager_headers"]


class TestRoleAuthorization:
    def test_brand_create_forbidden_for_talent_manager(self, api):
        """PRD §2.1: "A request whose role is not among the roles authorized
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 (endpoint table): "| POST | `/brands` | Onboard a brand
        (status `ACTIVE`) | BrandManager |"

        Design: Corner/rbac/brand_create_forbidden_for_talent_manager
        """
        res = api.create_brand(
            create_brand_payload(name="BR1", industry="CPG"), TM
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)


class TestAuthenticationContext:
    def test_creator_list_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two mandatory HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`,
        declaring the capacity in which they act. ... A request that omits
        either header, or presents a role outside this list, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/creator_list_missing_auth_header_unauthenticated
        """
        res = api.list_creators(None)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_creator_list_role_header_missing_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or presents a role
        outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        X-User-ID without X-User-Role is still an incomplete context.

        Design: Corner/rbac/creator_list_missing_auth_header_unauthenticated
        """
        res = api.list_creators(make_headers_without_role("operator-1"))
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, 401)
