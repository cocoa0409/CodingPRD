"""Authentication and role-based authorization gates."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    create_plan_payload,
    create_plan, create_provider,
)

EXAMINER = TEST_USERS["claims_examiner_headers"]


def test_claims_examiner_open_fund_account_returns_unauthorized(api):
    """PRD 2.1: "Once a request is authenticated, the system verifies that the declared role
    is permitted to perform the requested operation; if it is not, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)." Opening a funding account is a `FundManager` operation.

    Design: Corner/rbac/claims_examiner_open_fund_account_returns_unauthorized
    """
    plan = create_plan()
    resp = api.create_fund_account({"plan_id": plan["id"]}, EXAMINER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_claims_examiner_generate_1099_returns_unauthorized(api):
    """PRD 2.1: "if it is not, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 3.8: "At year end an `Auditor` generates a provider 1099 by supplying the `provider_id`
    and the `tax_year`."

    Design: Corner/rbac/claims_examiner_generate_1099_returns_unauthorized
    """
    provider = create_provider(in_network=True, ppo_discount_pct=0.40)
    resp = api.generate_form_1099({"provider_id": provider["id"], "tax_year": 2026}, EXAMINER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing or invalid, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). This authentication check is the very first gate applied
    to any request, before any other consideration."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.create_plan(create_plan_payload(), {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
