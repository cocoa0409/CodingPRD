"""B2B credit charging, credit-limit boundary, account-active gate, OCC on order ops.

Difficulty: credit_limit_exact_boundary_on_charge_account, order_confirm_requires_account_active.
Corner: not_b2b_account_cannot_charge_account, insufficient_points_at_confirm,
error_credit_limit_exceeded, occ_pay_stale_version_conflict, error_stale_version_on_confirm.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


def _confirmed_b2b_order(credit_limit_cents, unit_price_cents):
    """B2B account + DRY_GOOD @ unit_price; order one line confirmed. Returns (account, order, version)."""
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], account_type="LANDSCAPER_B2B",
                               display_name="Acme Land", credit_limit_cents=credit_limit_cents)
    product = X.create_product(nursery["id"], sku="DG-CL", name="Pallet", unit_price_cents=unit_price_cents)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=1)
    c = X.confirm(order["id"], order["version"])
    return account, order, c["version"]


# ---------------------------------------------------------------------------
# Difficulty: credit_limit_exact_boundary_on_charge_account
# ---------------------------------------------------------------------------
def test_charge_account_at_exact_credit_limit_succeeds(api):
    """PRD §3.6: "the account's current outstanding balance plus this order's net
    total would not exceed the account's credit limit (otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Difficulty/boundary_precision_check/credit_limit_exact_boundary_on_charge_account
    """
    account, order, v = _confirmed_b2b_order(credit_limit_cents=10000, unit_price_cents=10000)
    charged = validate_success(api.charge_account(order["id"], F.version_payload(v), CLERK))
    assert charged["payment_status"] == "ON_ACCOUNT", "net 10000 == limit 10000 allowed (inclusive)"
    acc = validate_success(api.get_account(account["id"], CLERK))
    assert acc["outstanding_balance_cents"] == 10000


def test_charge_account_one_cent_over_limit_rejected(api):
    """PRD §3.6: "the account's current outstanding balance plus this order's net
    total would not exceed the account's credit limit (otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Difficulty/boundary_precision_check/credit_limit_exact_boundary_on_charge_account
    """
    account, order, v = _confirmed_b2b_order(credit_limit_cents=10000, unit_price_cents=10001)
    resp = api.charge_account(order["id"], F.version_payload(v), CLERK)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


def test_charge_account_net_above_limit_rejected(api):
    """PRD §3.6: "the account's current outstanding balance plus this order's net
    total would not exceed the account's credit limit (otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Corner/errors/error_credit_limit_exceeded
    """
    account, order, v = _confirmed_b2b_order(credit_limit_cents=10000, unit_price_cents=10001)
    resp = api.charge_account(order["id"], F.version_payload(v), CLERK)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Difficulty: order_confirm_requires_account_active
# ---------------------------------------------------------------------------
def test_credit_hold_account_blocks_confirm(api):
    """PRD §3.3: "Confirmation is permitted only when ... the account is in `ACTIVE`
    status (otherwise `ERR_ACCOUNT_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_account_active
    """
    ctx = X.setup_b2b_credit_hold(credit_limit_cents=5000)
    # Account is now CREDIT_HOLD. Open a fresh order and try to confirm it.
    order2 = X.create_order(ctx["account"]["id"])
    X.add_line(order2["id"], ctx["product"]["id"], qty=1)
    resp = api.confirm_order(order2["id"], F.confirm_payload(order2["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


def test_charge_to_full_credit_limit_sets_credit_hold(api):
    """PRD §3.6: "If the new outstanding balance exactly equals the account's credit
    limit — the account is now fully drawn — the account is placed on `CREDIT_HOLD`,
    which blocks further order confirmations on that account until it is paid down."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_account_active
    """
    ctx = X.setup_b2b_credit_hold(credit_limit_cents=5000)
    acc = validate_success(api.get_account(ctx["account"]["id"], CLERK))
    assert acc["status"] == "CREDIT_HOLD"
    assert acc["outstanding_balance_cents"] == 5000


# ---------------------------------------------------------------------------
# Corner: charge / redemption validations
# ---------------------------------------------------------------------------
def test_retail_account_cannot_charge_account(api):
    """PRD §3.6: "This is permitted only when ... the account is of type
    `LANDSCAPER_B2B` (otherwise `ERR_NOT_B2B_ACCOUNT`)".

    Design: Corner/validations/not_b2b_account_cannot_charge_account
    """
    ctx = X.setup_confirmed_order(unit_price_cents=500, qty=1)  # RETAIL account
    resp = api.charge_account(ctx["order"]["id"], F.version_payload(ctx["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_B2B_ACCOUNT.value)


def test_confirm_redeeming_more_than_balance_rejected(api):
    """PRD §3.3: "the requested redemption does not exceed the account's redeemable
    balance (otherwise `ERR_INSUFFICIENT_POINTS`)".

    Design: Corner/validations/insufficient_points_at_confirm
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])  # fresh, points_balance 0
    product = X.create_product(nursery["id"], sku="DG-IP", name="Label", unit_price_cents=5000)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=1)
    resp = api.confirm_order(order["id"], F.confirm_payload(order["version"], requested_redeem_points=10), CLERK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


# ---------------------------------------------------------------------------
# Corner: OCC stale-version
# ---------------------------------------------------------------------------
def test_pay_with_stale_version_rejected(api):
    """PRD §2.7: "the server compares `expected_order_version` to the order's
    current `version`; if they do not match ... the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and no change is made."

    Design: Corner/cross_cutting_complexity_layers/occ_pay_stale_version_conflict
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-OCC", name="Bolt", unit_price_cents=300)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=1)
    c = X.confirm(order["id"], order["version"])  # version advanced past the pre-confirm value
    stale = c["version"] - 1
    resp = api.pay_order(order["id"], F.version_payload(stale), CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_confirm_with_stale_version_rejected(api):
    """PRD §2.7: "In particular, a confirm request that arrives with a stale
    `expected_order_version` is rejected before the order's pricing and redemption
    totals are locked".

    Design: Corner/errors/error_stale_version_on_confirm
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-OC2", name="Pin", unit_price_cents=300)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=1)
    current = validate_success(api.get_order(order["id"], CLERK))["version"]
    resp = api.confirm_order(order["id"], F.confirm_payload(current - 1), CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
