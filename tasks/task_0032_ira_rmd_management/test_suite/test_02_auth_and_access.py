"""Authentication, authorization, and role-based access control (PRD §2.1, §2.6)."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    set_clock,
    create_owner,
    create_account,
    make_account_owner_headers,
)


def test_missing_user_role_header_returns_missing_auth(api):
    """PRD §2.1: "If `X-User-Role` is missing or empty the request is rejected
    with `ERR_MISSING_AUTH` (HTTP 401)."

    Design: Corner/validations/missing_x_user_role_header_returns_missing_auth
    """
    set_clock("2026-06-01T00:00:00Z")
    # Send a header dict with X-User-ID present but no X-User-Role (simulate
    # missing/empty role). build_user_headers stamps both — use an empty role.
    headers = build_user_headers("test-user", "")
    res = api.list_owners(headers)
    validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value)


def test_unknown_role_header_returns_invalid_role(api):
    """PRD §2.1: "If `X-User-Role` is present but is not one of the three role
    names enumerated below, the request is rejected with `ERR_INVALID_ROLE`
    (also HTTP 401)."

    Design: Corner/errors/error_invalid_role_header_returns_401
    """
    set_clock("2026-06-01T00:00:00Z")
    headers = build_user_headers("test-user", "SomeBogusRole")
    res = api.list_owners(headers)
    validate_error(res, ApiErrorId.ERR_INVALID_ROLE.value)


def test_account_owner_cannot_act_on_another_owners_account(api):
    """PRD §2.1: "when an `AccountOwner` caller's `X-User-ID` does not match
    the owner of the resource being acted on, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/error_unauthorized_account_owner_cannot_act_on_another_owners_account
    """
    set_clock("2026-06-01T00:00:00Z")
    eli = create_owner(full_name="Eli", date_of_birth="1981-11-11", tax_id_last4="3131")
    fritz = create_owner(
        full_name="Fritz", date_of_birth="1981-12-12", tax_id_last4="3232"
    )
    fritz_trad = create_account(fritz["id"], "TRADITIONAL")

    # Eli posts against Fritz's account (ownership mismatch).
    payload = {
        "account_id": fritz_trad["id"],
        "tax_year": 2026,
        "amount_cents": 100_000,
        "contribution_kind": "PRETAX",
    }
    res = api.create_contribution(payload, make_account_owner_headers(eli["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)
