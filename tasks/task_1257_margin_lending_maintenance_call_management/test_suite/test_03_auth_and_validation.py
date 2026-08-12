"""Authentication, authorization, ownership, and clock validations."""
from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    api_client,
    create_approved_account,
    create_customer,
    create_security_profile,
    make_customer_headers,
    post_mark,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)


def test_missing_auth_headers_returns_400(api):
    """PRD §2.1: "A request missing either header, or presenting an
    unrecognized role, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    customer = create_customer()
    resp = api.get_customer(customer["id"], headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_role_denied_customer_cannot_waive_call(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint
    is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.10: "2. **Authorization** — the role is permitted on this endpoint
    (`ERR_INSUFFICIENT_PERMISSIONS`). 3. **Existence** — path identifiers
    resolve left to right (the 404 catalogue of §2.9)."

    Design: Corner/validations/role_denied_customer_cannot_waive_call
    """
    customer = create_customer()
    resp = api.waive_margin_call(ABSENT_UUID, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_ownership_mismatch_on_foreign_account_order(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `Customer` record; ownership checks on any resource that
    references a customer compare the resource's customer foreign key to
    `X-User-ID`, and a mismatch is rejected with
    `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/ownership_mismatch_on_foreign_account_order
    """
    customer_a, _app, account_id = create_approved_account()
    customer_b = create_customer()
    security = create_security_profile(symbol="ABC")
    post_mark(security["id"], "REALTIME", 10_000)
    resp = api.place_order(
        account_id,
        {"security_id": security["id"], "side": "BUY", "quantity": 1},
        make_customer_headers(customer_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_OWNERSHIP_MISMATCH)


def test_analyst_cannot_post_marks(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint
    is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4 routing table: POST /margin/market-marks is authorized for
    MarketDataOps only.

    Design: Corner/rbac/analyst_cannot_post_marks
    """
    security = create_security_profile(symbol="ABC")
    resp = api.post_market_mark(
        {"security_id": security["id"], "mark_type": "REALTIME", "price_cents": 10_000},
        TEST_USERS["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_clock_regression_rejected(api, market_ops_headers):
    """PRD §2.5: "The new time must be greater than or equal to the current
    logical time; an attempt to move it backwards is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 400)."

    Design: Corner/endpoints/clock_regression_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    resp = api.set_clock({"to_iso8601": "2026-05-09T00:00:00Z"}, market_ops_headers)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
