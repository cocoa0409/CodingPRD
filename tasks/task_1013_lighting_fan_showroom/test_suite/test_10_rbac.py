"""Role-based access control and Designer ownership isolation (PRD §2.1)."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS, build_user_headers, make_designer_headers,
    create_account, create_fixture, create_order,
)

SM = TEST_USERS["sm_headers"]


def test_associate_cannot_create_fixture_model(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/associate_create_fixture_model_returns_unauthorized
    """
    resp = api.create_fixture_model(
        {"sku_base": "F-UZ", "category": "SCONCE", "base_price_cents": 5000, "base_wattage": 40},
        TEST_USERS["associate_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_designer_acting_on_other_accounts_order_forbidden(api):
    """PRD §2.1: "A `Designer` may act only on resources belonging to their own account, and
    only while that account is `ACTIVE`; acting on a resource they do not own, or from an
    account that is not `ACTIVE`, is rejected with `ERR_ACCOUNT_FORBIDDEN`."

    Design: Corner/rbac/designer_acts_on_other_accounts_order_returns_forbidden
    """
    acct_a = create_account(api, business_name="AcctA", contact_email="a@x.com", credit_limit_cents=1000000)
    acct_b = create_account(api, business_name="AcctB", contact_email="b@x.com", credit_limit_cents=1000000)
    fx = create_fixture(api, sku_base="F-OWN", base_price_cents=5000, base_wattage=40)
    order = create_order(api, customer_name="OwnedByA", trade_account_id=acct_a["id"])
    # Designer bound to account B tries to add a line to account A's order.
    resp = api.add_order_line(
        order["id"], {"fixture_model_id": fx["id"], "quantity": 1}, make_designer_headers(acct_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_FORBIDDEN.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or the role is not one of the recognized roles,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    bogus_headers = build_user_headers("test-unknown-1", "Wizard")
    resp = api.get_order("00000000-0000-0000-0000-000000000000", bogus_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
