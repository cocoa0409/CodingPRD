"""Role-based access control denials (corner-design `roles` section)."""
from test_helpers import (
    validate_error, validate_error_is_one_of, ApiErrorId, TEST_USERS,
    make_registrant_headers, NON_EXISTENT_UUID,
)


def test_code_officer_cannot_record_lien_returns_unauthorized(api):
    """PRD §2.10: "Validation checks are applied in a fixed precedence ... The
    order is: (1) authentication (`ERR_UNAUTHENTICATED`); (2) authorization ...
    (`ERR_UNAUTHORIZED`); (3) existence of the path resources".
    PRD §4: record-lien is authorized for ProgramAdmin only.

    Design: Corner/roles/code_officer_cannot_record_lien_returns_unauthorized
    """
    resp = api.record_lien(NON_EXISTENT_UUID, TEST_USERS["code_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_registrant_cannot_demolish_returns_unauthorized(api):
    """PRD §2.1: "Every other mutating operation is exclusive to exactly one role".
    PRD §3.9: "A `ProgramAdmin` marks a property demolished."

    Design: Corner/roles/registrant_cannot_demolish_returns_unauthorized
    """
    resp = api.demolish_property(
        NON_EXISTENT_UUID, make_registrant_headers(NON_EXISTENT_UUID)
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_anonymous_cannot_read_property_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing on a protected endpoint, or if
    `X-User-Role` is not one of the roles enumerated below, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)." But PRD §2.1 also enumerates
    `Anonymous` as a *known* role and states "a caller whose role is unknown always
    sees `ERR_UNAUTHENTICATED`, never `ERR_UNAUTHORIZED`." Since `Anonymous` is a
    known enumerated role whose only permitted operation is self-registration, a
    faithful reader may return `ERR_UNAUTHORIZED` (auth passes, read not permitted)
    or `ERR_UNAUTHENTICATED` (unauthenticated caller). The PRD does not uniquely
    determine which, so either auth error is accepted.

    Design: Corner/roles/anonymous_cannot_read_property_returns_unauthenticated
    """
    resp = api.get_property(NON_EXISTENT_UUID, TEST_USERS["anonymous_headers"])
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_UNAUTHENTICATED.value, ApiErrorId.ERR_UNAUTHORIZED.value],
    )
