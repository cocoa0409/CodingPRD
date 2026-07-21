"""Wholesale credit: committed vs projected exposure, the credit gate boundary,
credit conservation on cancel, and optimistic concurrency on confirm."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    new_product, new_account, new_order, new_line, do_price, do_confirm, account_version,
    setup_two_orders_committed_and_priced, assert_credit_conserved,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_headers"]


# ---- dual_variant_calc / account_committed_vs_projected_exposure ----

def test_committed_exposure_counts_only_confirmed_holds(api):
    """PRD §3.5: "The `committed_exposure_cents` is the sum of `held_exposure_cents` over
    the account's orders whose `fulfillment_status` is `CONFIRMED`, `PACKED`, or `SHIPPED`."

    Design: Difficulty/dual_variant_calc/account_committed_vs_projected_exposure
    """
    ctx = setup_two_orders_committed_and_priced(api)
    account = validate_success(api.get_wholesale_account(ctx["account"]["id"], SALES))
    # Only order A is CONFIRMED (hold 250); order B is merely PRICED.
    assert account["committed_exposure_cents"] == 250, account["committed_exposure_cents"]
    assert account["available_credit_cents"] == 99750, account["available_credit_cents"]


def test_projected_exposure_adds_priced_orders(api):
    """PRD §3.5: "The `projected_exposure_cents` is a forward-looking what-if: it is the
    committed exposure plus the `provisional_total_cents` of the account's orders that are
    `PRICED` but not yet confirmed, and it therefore exceeds committed exposure whenever
    any priced order is outstanding."

    Design: Difficulty/dual_variant_calc/account_committed_vs_projected_exposure
    """
    ctx = setup_two_orders_committed_and_priced(api)
    account = validate_success(api.get_wholesale_account(ctx["account"]["id"], SALES))
    # committed 250 + PRICED order B provisional (200*3.5=700) = 950.
    assert account["projected_exposure_cents"] == 950, account["projected_exposure_cents"]


# ---- boundary_precision_check / credit_limit_exact_boundary_on_confirm ----

def _boundary_setup(api):
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api, credit_limit_cents=1000)
    order_a = new_order(api, account["id"])
    new_line(api, order_a["id"], cham["id"], 400)  # 400*2.5 = 1000 exactly
    do_price(api, order_a["id"])
    do_confirm(api, order_a["id"], account["id"])  # commits exactly the 1000 limit
    order_b = new_order(api, account["id"])
    new_line(api, order_b["id"], cham["id"], 100)  # 100*2.5 = 250
    do_price(api, order_b["id"])
    return account, order_a, order_b


def test_confirm_at_exact_credit_limit_succeeds(api):
    """PRD §3.6: "that the order's `provisional_total_cents` not exceed the account's
    `available_credit_cents` (else `ERR_CREDIT_LIMIT_EXCEEDED` at HTTP 402)."

    Design: Difficulty/boundary_precision_check/credit_limit_exact_boundary_on_confirm
    """
    account, order_a, _order_b = _boundary_setup(api)
    a = validate_success(api.get_order(order_a["id"], SALES))
    acc = validate_success(api.get_wholesale_account(account["id"], SALES))
    # 1000 <= 1000 is accepted (inclusive at equality); available drops to exactly 0.
    assert a["fulfillment_status"] == "CONFIRMED", a["fulfillment_status"]
    assert acc["available_credit_cents"] == 0, acc["available_credit_cents"]


def test_confirm_above_available_credit_rejected(api):
    """PRD §3.6: "that the order's `provisional_total_cents` not exceed the account's
    `available_credit_cents` (else `ERR_CREDIT_LIMIT_EXCEEDED` at HTTP 402)."

    Design: Difficulty/boundary_precision_check/credit_limit_exact_boundary_on_confirm
    """
    account, _order_a, order_b = _boundary_setup(api)
    v = account_version(api, account["id"])
    # available is 0; order B provisional 250 > 0 -> strict rejection.
    resp = api.confirm_order(order_b["id"], {"expected_wholesale_account_version": v}, SALES)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


# ---- compensating_invariant / credit_conservation_confirm_cancel ----

def _confirmed_hold(api):
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api, credit_limit_cents=100000)
    order = new_order(api, account["id"])
    new_line(api, order["id"], cham["id"], 100)  # 250c
    do_price(api, order["id"])
    do_confirm(api, order["id"], account["id"])
    return account, order


def test_cancel_confirmed_releases_credit_hold(api):
    """PRD §3.8: "Cancelling a `CONFIRMED` order releases its credit hold: the account's
    committed exposure decreases by the order's `held_exposure_cents`, and that held amount
    is reset to zero."

    Design: Difficulty/compensating_invariant/credit_conservation_confirm_cancel
    """
    account, order = _confirmed_hold(api)
    validate_success(api.cancel_order(order["id"], SALES))
    acc = validate_success(api.get_wholesale_account(account["id"], SALES))
    assert acc["committed_exposure_cents"] == 0, acc["committed_exposure_cents"]
    assert acc["available_credit_cents"] == 100000, acc["available_credit_cents"]


def test_credit_conserved_across_confirm_and_cancel(api):
    """PRD §3.6: "the account's committed exposure increases by that held amount, and the
    account's `version` increments by one."
    PRD §3.8: "the account's committed exposure decreases by the order's
    `held_exposure_cents`, and that held amount is reset to zero."

    Design: Difficulty/compensating_invariant/credit_conservation_confirm_cancel
    """
    account, order = _confirmed_hold(api)
    held = validate_success(api.get_wholesale_account(account["id"], SALES))
    assert held["committed_exposure_cents"] == 250 and held["available_credit_cents"] == 99750
    assert_credit_conserved(held)
    validate_success(api.cancel_order(order["id"], SALES))
    released = validate_success(api.get_wholesale_account(account["id"], SALES))
    assert released["available_credit_cents"] == 100000
    assert_credit_conserved(released)


# ---- Corner / cross_cutting_complexity_layers ----

def test_stale_account_version_on_confirm_rejected(api):
    """PRD §2.8: "If that value does not equal the account's current `version` — because
    another confirmation has advanced it since the client last read the account — the
    confirmation is rejected with `ERR_STALE_VERSION` at HTTP 412, so a client can never
    commit a hold against a stale view of available credit."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_account_version_on_confirm
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api, credit_limit_cents=100000)
    stale_version = account["version"]  # 1
    order_a = new_order(api, account["id"])
    new_line(api, order_a["id"], cham["id"], 100)
    do_price(api, order_a["id"])
    order_b = new_order(api, account["id"])
    new_line(api, order_b["id"], cham["id"], 100)
    do_price(api, order_b["id"])
    do_confirm(api, order_a["id"], account["id"], expected_version=stale_version)  # bumps 1->2
    resp = api.confirm_order(order_b["id"],
                             {"expected_wholesale_account_version": stale_version}, SALES)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_confirm_success_bumps_account_version_and_commits_hold(api):
    """PRD §3.6: "On success, the order's `held_exposure_cents` is set to its provisional
    total, the account's committed exposure increases by that held amount, and the
    account's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/corner_order_confirm_success_bumps_account_version
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api, credit_limit_cents=100000)
    order = new_order(api, account["id"])
    new_line(api, order["id"], cham["id"], 100)
    do_price(api, order["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"],
                          {"expected_wholesale_account_version": account["version"]}, SALES))
    assert confirmed["fulfillment_status"] == "CONFIRMED"
    acc = validate_success(api.get_wholesale_account(account["id"], SALES))
    assert acc["committed_exposure_cents"] == 250, acc["committed_exposure_cents"]
    # PRD pins the increment ("increments by one"), not the initial value: assert relative.
    assert acc["version"] == account["version"] + 1, acc["version"]
