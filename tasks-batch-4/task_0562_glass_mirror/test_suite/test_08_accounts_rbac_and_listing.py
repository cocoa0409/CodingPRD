"""Account creation, not-found reads, RBAC denials, and list-envelope / pagination rules."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid, ApiErrorId,
    TEST_USERS, make_contractor_headers, make_unknown_role_headers,
    create_contractor_account_payload, create_quote_payload,
)
from test_helpers import fixtures as fx


# ==========================================================================
# entities / create_contractor_account_returns_201_with_fields
# ==========================================================================
def test_create_contractor_account_returns_defaults(api):
    """PRD §3.1: "A new account is born with `status` `ACTIVE`, `credit_used_cents` of 0, and
    `version` 1; its `available_credit_cents` therefore equals its `credit_limit_cents`."
    PRD §2.4: "`id`: a server-minted UUID with no type prefix."

    Design: Corner/entities/create_contractor_account_returns_201_with_fields
    """
    resp = api.create_contractor_account(
        create_contractor_account_payload(company_name="Acme Glazing", tier="GOLD",
                                           credit_limit_cents=5_000_000),
        TEST_USERS["shop_admin_headers"])
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]), data["id"]
    assert data["status"] == "ACTIVE", data["status"]
    assert data["credit_used_cents"] == 0, data["credit_used_cents"]
    assert data["version"] == 1, data["version"]
    assert data["available_credit_cents"] == 5_000_000, data["available_credit_cents"]


# ==========================================================================
# entities / get_contractor_account_not_found_returns_404
# ==========================================================================
def test_get_contractor_account_not_found(api):
    """PRD §2.8: "every path and body foreign-key id resolves to an existing resource. Ids
    are validated left-to-right in the order they appear in the path, then the body; the
    first unresolved id yields `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/get_contractor_account_not_found_returns_404
    """
    resp = api.get_contractor_account("00000000-0000-4000-8000-000000000000",
                                      TEST_USERS["shop_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ==========================================================================
# endpoints / list_quotes_pagination_envelope
# ==========================================================================
def test_list_quotes_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of any list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/list_quotes_pagination_envelope
    """
    account = fx.create_account(api, tier="SILVER")
    fx.create_draft_quote(api, account["id"])
    fx.create_draft_quote(api, account["id"])
    data, meta = validate_paginated(api.list_quotes(
        TEST_USERS["estimator_headers"],
        params={"contractor_account_id": account["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert len(data) == 1, data
    assert meta["has_more"] is True, meta


# ==========================================================================
# endpoints / pagination_limit_out_of_bounds_returns_error
# ==========================================================================
def test_pagination_limit_zero_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is
    rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/endpoints/pagination_limit_out_of_bounds_returns_error
    """
    resp = api.list_jobs(TEST_USERS["shop_admin_headers"], params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID)


# ==========================================================================
# rbac / estimator_cannot_create_account_returns_forbidden
# ==========================================================================
def test_estimator_cannot_create_account(api):
    """PRD §2.1: "When the header is present and valid but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.1: "A `ShopAdmin` onboards a B2B customer by creating a `ContractorAccount` with a
    `company_name`, a `tier`, and a `credit_limit_cents` (which must be at least 0)."

    Design: Corner/rbac/estimator_cannot_create_account_returns_forbidden
    """
    resp = api.create_contractor_account(
        create_contractor_account_payload(company_name="Acme", tier="SILVER",
                                           credit_limit_cents=100000),
        TEST_USERS["estimator_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ==========================================================================
# rbac / contractor_cannot_accept_other_accounts_quote
# ==========================================================================
def test_contractor_cannot_accept_other_accounts_quote(api):
    """PRD §3.4: "only the owning `Contractor` may accept — the acting `X-User-ID` must equal
    the quote's `contractor_account_id`, else `ERR_FORBIDDEN`."
    PRD §2.1: "Any ownership check on a resource that references a contractor account compares
    that resource's `contractor_account_id` to `X-User-ID`; a mismatch is an `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/contractor_cannot_accept_other_accounts_quote
    """
    account_a = fx.create_account(api, tier="SILVER", company_name="AcmeA")
    account_b = fx.create_account(api, tier="SILVER", company_name="AcmeB")
    quote = fx.create_draft_quote(api, account_a["id"])
    fx.add_line(api, quote["id"], **fx.LINE_TABLETOP)
    fx.send_quote(api, quote["id"])
    # Contractor whose X-User-ID is account B tries to accept account A's quote.
    resp = api.accept_quote(quote["id"], {"expected_account_version": account_a["version"]},
                            make_contractor_headers(account_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ==========================================================================
# rbac / missing_role_header_returns_unauthenticated
# ==========================================================================
def test_unknown_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognized roles, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.list_jobs(make_unknown_role_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
