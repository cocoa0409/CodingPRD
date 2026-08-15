"""Access control and validation-order surface (PRD §2.1, §2.7, §2.8)."""
from test_helpers import (
    validate_error, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_account, create_product_payload,
)

CM = TEST_USERS["credit_manager_headers"]
EST = TEST_USERS["estimator_headers"]
FORE = TEST_USERS["foreman_headers"]


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    match one of the declared roles is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401); a request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/auth_unauthenticated_request_rejected
    """
    res = api.list_products(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_forbidden_role_cannot_create_product(api, estimator_headers):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    match one of the declared roles is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401); a request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "A `WarehouseManager` is the warehouse lead who registers and
    updates products and files, accepts, and rejects bundle returns."

    Design: Corner/validations/forbidden_role_cannot_create_product
    """
    res = api.create_product(create_product_payload(sku="X"), estimator_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_estimator_cannot_suspend_account(api, estimator_headers):
    """PRD §2.1: "A `CreditManager` is the supply house's credit and receivables
    officer: they open, suspend, reinstate, and close contractor accounts, void
    draw requests, and are the only role permitted to drive the test clock."
    PRD §2.1: "a request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/estimator_cannot_suspend_account
    """
    account = create_account(company_name="X Co", credit_limit_cents=100000)
    res = api.suspend_contractor_account(account["id"], estimator_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_foreman_cannot_apply_payment(api, foreman_headers):
    """PRD §2.1: "An `AccountsReceivableUser` is the AR clerk who applies
    payments to draw requests."
    PRD §2.8: "The order is: authentication (`ERR_UNAUTHENTICATED`) first, then
    authorization (`ERR_FORBIDDEN`), then path resolution (`ERR_NOT_FOUND`),
    then the account-posture guard (`ERR_ACCOUNT_SUSPENDED`), then generic
    state guards (`ERR_INVALID_STATE`), and only then the business rules."

    Authorization precedes path resolution, so a Foreman posting to a
    non-existent draw id still gets ERR_FORBIDDEN.

    Design: Corner/rbac/foreman_cannot_apply_payment
    """
    res = api.apply_payment(
        NON_EXISTENT_UUID,
        {"amount_cents": 100, "method": "ACH", "received_at": "2026-08-01T00:00:00Z"},
        foreman_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_payment_on_nonexistent_draw_rejected_before_overpayment(api, accounts_receivable_headers):
    """PRD §2.8: "The order is: authentication (`ERR_UNAUTHENTICATED`) first,
    then authorization (`ERR_FORBIDDEN`), then path resolution
    (`ERR_NOT_FOUND`), then the account-posture guard
    (`ERR_ACCOUNT_SUSPENDED`), then generic state guards (`ERR_INVALID_STATE`),
    and only then the business rules."
    PRD §2.7: "The first segment that fails to resolve — or a child found to
    belong to a different parent — yields `ERR_NOT_FOUND` (HTTP 404), and no
    business validation runs before path resolution completes."

    The amount (99,999,999 cents) would exceed any plausible remaining balance,
    yet path resolution fires first.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_payment
    """
    res = api.apply_payment(
        NON_EXISTENT_UUID,
        {"amount_cents": 99999999, "method": "ACH", "received_at": "2026-08-01T00:00:00Z"},
        accounts_receivable_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_payment_on_nonexistent_draw_rejected_even_for_small_amount(api, accounts_receivable_headers):
    """PRD §2.7: "The first segment that fails to resolve — or a child found to
    belong to a different parent — yields `ERR_NOT_FOUND` (HTTP 404), and no
    business validation runs before path resolution completes."

    A small, otherwise-valid amount does not change the outcome: the unresolved
    draw id dominates the fiscal checks.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_payment
    """
    res = api.apply_payment(
        NON_EXISTENT_UUID,
        {"amount_cents": 100, "method": "ACH", "received_at": "2026-08-01T00:00:00Z"},
        accounts_receivable_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
