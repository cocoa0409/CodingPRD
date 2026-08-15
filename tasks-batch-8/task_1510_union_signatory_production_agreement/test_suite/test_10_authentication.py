"""Authentication checks and validation ordering (PRD §2.1, §2.10)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming their operational
    capacity. ... A request missing either header, or presenting an
    `X-User-Role` value that is not one of these five, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    resp = api.create_producer_company(
        th.create_producer_company_payload(legal_name="No Auth LLC",
                                           fein="20-0000030"),
        headers={},
    )
    th.validate_error(resp, E.ERR_UNAUTHENTICATED)


def test_auth_checked_before_existence(api):
    """PRD §2.10: "Authentication comes first (`ERR_UNAUTHENTICATED`), then
    role authorization (`ERR_UNAUTHORIZED_ROLE`), then `ProducerRep` ownership
    (`ERR_NOT_RESOURCE_OWNER`). Next the body itself is validated ... followed
    by existence of path and body references (`ERR_RESOURCE_NOT_FOUND`)".
    A request with no auth headers against a non-existent production id
    surfaces ERR_UNAUTHENTICATED, not ERR_RESOURCE_NOT_FOUND.

    Design: Corner/validations/missing_auth_on_unknown_resource_returns_unauthenticated
    """
    resp = api.get_production(th.NON_EXISTENT_UUID, headers={})
    th.validate_error(resp, E.ERR_UNAUTHENTICATED)
