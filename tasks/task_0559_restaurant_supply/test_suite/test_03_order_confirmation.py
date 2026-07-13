"""Order confirmation: allocation/backorder cascade into inventory and reorder
signals, compensating cancellation invariants, precondition ordering, credit
reservation, optimistic concurrency, and the parallel payment dimension.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_buyer_headers,
    fixtures,
)

AM = TEST_USERS["account_manager_headers"]
WH = TEST_USERS["warehouse_headers"]


# --------------------------------------------------------------------------- #
# transitive_cascade / confirm_allocates_decrements_stock_flags_reorder
# --------------------------------------------------------------------------- #
def test_confirm_allocates_and_decrements_on_hand(api):
    """PRD §3.5: "For each `STOCK` line, the allocated quantity is the smaller of the line's
    `quantity` and the product's current `on_hand_qty`; the backordered quantity is the line's
    `quantity` minus that allocated amount; and the product's `on_hand_qty` is decremented by the
    allocated amount."

    Design: Difficulty/transitive_cascade/confirm_allocates_decrements_stock_flags_reorder
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="CASCA-1", unit_price_cents=500, on_hand_qty=5,
                                   par_level=20, reorder_point=4)
    order = fixtures.create_order(api, acct["id"])
    line = fixtures.add_line(api, order["id"], acct["id"], prod["id"], 2)
    fixtures.confirm_order(api, order["id"], acct["id"])
    line_after = validate_success(api.get_order_line(line["id"], WH))
    prod_after = validate_success(api.get_product(prod["id"], WH))
    assert line_after["allocated_qty"] == 2
    assert prod_after["on_hand_qty"] == 3


def test_confirm_stock_decrement_flips_reorder_signal(api):
    """PRD §3.3: "The `needs_reorder` flag is true exactly when `on_hand_qty` is less than or equal
    to `reorder_point`."
    PRD §3.3: "Equivalently, when `needs_reorder` holds, the suggested quantity is the larger of
    zero and `par_level` minus `on_hand_qty`, and otherwise it is zero."

    Design: Difficulty/transitive_cascade/confirm_allocates_decrements_stock_flags_reorder
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="CASCA-1b", unit_price_cents=500, on_hand_qty=5,
                                   par_level=20, reorder_point=4)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 2)
    fixtures.confirm_order(api, order["id"], acct["id"])
    prod_after = validate_success(api.get_product(prod["id"], WH))
    assert prod_after["needs_reorder"] is True
    assert prod_after["reorder_suggested_qty"] == 17  # par 20 - on_hand 3


# --------------------------------------------------------------------------- #
# compensating_invariant / confirm_cancel_conserves_inventory_units
# --------------------------------------------------------------------------- #
def test_cancel_confirmed_order_restores_on_hand(api):
    """PRD §3.5: "Cancelling a `CONFIRMED` order additionally compensates the earlier allocation:
    for each `STOCK` line, the product's `on_hand_qty` is increased by that line's `allocated_qty`,
    and the line's `allocated_qty` and `backordered_qty` are reset to 0".

    Design: Difficulty/compensating_invariant/confirm_cancel_conserves_inventory_units
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="BOWL-1", unit_price_cents=500, on_hand_qty=10,
                                   par_level=20, reorder_point=2)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 4)
    fixtures.confirm_order(api, order["id"], acct["id"])
    validate_success(api.cancel_order(order["id"], make_buyer_headers(acct["id"])))
    prod_after = validate_success(api.get_product(prod["id"], WH))
    assert prod_after["on_hand_qty"] == 10


def test_cancel_confirmed_order_zeroes_allocation_and_cancels(api):
    """PRD §3.5: "every non-cancelled line becomes `CANCELLED`; the account's outstanding and
    available credit are recomputed because the order no longer counts; and the order moves
    `CONFIRMED → CANCELLED`."

    Design: Difficulty/compensating_invariant/confirm_cancel_conserves_inventory_units
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="BOWL-1b", unit_price_cents=500, on_hand_qty=10,
                                   par_level=20, reorder_point=2)
    order = fixtures.create_order(api, acct["id"])
    line = fixtures.add_line(api, order["id"], acct["id"], prod["id"], 4)
    fixtures.confirm_order(api, order["id"], acct["id"])
    cancelled = validate_success(api.cancel_order(order["id"], make_buyer_headers(acct["id"])))
    line_after = validate_success(api.get_order_line(line["id"], WH))
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert line_after["allocated_qty"] == 0


# --------------------------------------------------------------------------- #
# compensating_invariant / confirm_cancel_conserves_account_outstanding
# --------------------------------------------------------------------------- #
def test_cancel_confirmed_order_restores_outstanding_to_zero(api):
    """PRD §2.10: "The `outstanding_cents` figure is the sum of `total_cents` across the account's
    orders whose `lifecycle_status` is `CONFIRMED`, `SHIPPED`, or `COMPLETED` and whose
    `payment_status` is `UNPAID` or `INVOICED`, reduced by the sum of `refund_cents` across the
    account's returns whose `status` is `REFUNDED`."

    Design: Difficulty/compensating_invariant/confirm_cancel_conserves_account_outstanding
    """
    acct = fixtures.create_account(api, credit_limit_cents=100000)
    prod = fixtures.create_product(api, sku="OUT-1", unit_price_cents=1000, on_hand_qty=100,
                                   par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 2)
    fixtures.confirm_order(api, order["id"], acct["id"])
    validate_success(api.cancel_order(order["id"], make_buyer_headers(acct["id"])))
    acct_after = validate_success(api.get_account(acct["id"], WH))
    assert acct_after["outstanding_cents"] == 0


def test_cancel_confirmed_order_restores_credit_available(api):
    """PRD §2.10: "The `credit_available_cents` figure is the account's `credit_limit_cents` minus
    its `outstanding_cents`." PRD §2.10: "and neither does a draft or cancelled order."

    Design: Difficulty/compensating_invariant/confirm_cancel_conserves_account_outstanding
    """
    acct = fixtures.create_account(api, credit_limit_cents=100000)
    prod = fixtures.create_product(api, sku="OUT-1b", unit_price_cents=1000, on_hand_qty=100,
                                   par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 2)
    fixtures.confirm_order(api, order["id"], acct["id"])
    validate_success(api.cancel_order(order["id"], make_buyer_headers(acct["id"])))
    acct_after = validate_success(api.get_account(acct["id"], WH))
    assert acct_after["credit_available_cents"] == 100000


# --------------------------------------------------------------------------- #
# boundary_precision_check / confirm_empty_order_rejected
# --------------------------------------------------------------------------- #
def test_confirm_order_with_no_lines_rejected(api):
    """PRD §3.5: "the order must have at least one non-cancelled line (`ERR_ORDER_HAS_NO_LINES`)".

    Design: Difficulty/boundary_precision_check/confirm_empty_order_rejected
    """
    acct = fixtures.create_account(api)
    order = fixtures.create_order(api, acct["id"])
    version = fixtures.account_version(api, acct["id"])
    resp = api.confirm_order(order["id"], {"expected_account_version": version},
                             make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_HAS_NO_LINES.value)


def test_confirm_empty_order_leaves_order_draft(api):
    """PRD §3.5: "Confirmation is the pivotal transition in an order's life, moving it
    `DRAFT → CONFIRMED`." PRD §3.5: "The system evaluates the following preconditions in this
    order, stopping at the first that fails:".

    Design: Difficulty/boundary_precision_check/confirm_empty_order_rejected
    """
    acct = fixtures.create_account(api)
    order = fixtures.create_order(api, acct["id"])
    version = fixtures.account_version(api, acct["id"])
    api.confirm_order(order["id"], {"expected_account_version": version},
                      make_buyer_headers(acct["id"]))
    after = validate_success(api.get_order(order["id"], WH))
    assert after["lifecycle_status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / confirm_requires_account_active
# --------------------------------------------------------------------------- #
def _suspended_account_with_affordable_order(api, credit_limit_cents=100_000_000):
    acct = fixtures.create_account(api, credit_limit_cents=credit_limit_cents)
    prod = fixtures.create_product(api, sku="SPOON-1", unit_price_cents=300, case_qty=12,
                                   case_price_cents=3200, pallet_case_qty=10, pallet_price_cents=30000,
                                   par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 3)
    validate_success(api.suspend_account(acct["id"], AM))
    return acct, order


def test_confirm_on_suspended_account_rejected(api):
    """PRD §3.5: "the owning account's `status` must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`)".

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_account_active
    """
    acct, order = _suspended_account_with_affordable_order(api)
    version = fixtures.account_version(api, acct["id"])
    resp = api.confirm_order(order["id"], {"expected_account_version": version},
                             make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)


def test_confirm_on_suspended_account_leaves_order_draft(api):
    """PRD §3.1: "A suspended account cannot have new orders confirmed against it, as described in
    §3.5." PRD §3.5: "The system evaluates the following preconditions in this order, stopping at
    the first that fails:".

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_account_active
    """
    acct, order = _suspended_account_with_affordable_order(api)
    version = fixtures.account_version(api, acct["id"])
    api.confirm_order(order["id"], {"expected_account_version": version},
                      make_buyer_headers(acct["id"]))
    after = validate_success(api.get_order(order["id"], WH))
    assert after["lifecycle_status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict / confirm_suspended_beats_credit
# --------------------------------------------------------------------------- #
def test_suspended_account_error_precedes_credit_check(api):
    """PRD §3.5: "the owning account's `status` must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`); the
    order's `total_cents` computed as merchandise subtotal plus tax, with freight still 0, must be
    less than or equal to the account's `credit_available_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/confirm_suspended_beats_credit
    """
    acct = fixtures.create_account(api, credit_limit_cents=1000)
    prod = fixtures.create_product(api, sku="BIG-1", unit_price_cents=6000, case_qty=100,
                                   case_price_cents=500000, pallet_case_qty=10,
                                   pallet_price_cents=4500000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 1)  # 6000 + 480 tax > 1000 credit
    validate_success(api.suspend_account(acct["id"], AM))
    version = fixtures.account_version(api, acct["id"])
    resp = api.confirm_order(order["id"], {"expected_account_version": version},
                             make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)


def test_suspended_beats_credit_leaves_order_draft(api):
    """PRD §3.5: "The system evaluates the following preconditions in this order, stopping at the
    first that fails:".

    Design: Difficulty/priority_pair_validation_conflict/confirm_suspended_beats_credit
    """
    acct = fixtures.create_account(api, credit_limit_cents=1000)
    prod = fixtures.create_product(api, sku="BIG-1b", unit_price_cents=6000, case_qty=100,
                                   case_price_cents=500000, pallet_case_qty=10,
                                   pallet_price_cents=4500000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 1)
    validate_success(api.suspend_account(acct["id"], AM))
    version = fixtures.account_version(api, acct["id"])
    api.confirm_order(order["id"], {"expected_account_version": version},
                      make_buyer_headers(acct["id"]))
    after = validate_success(api.get_order(order["id"], WH))
    assert after["lifecycle_status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# calculations / dropship_line_does_not_touch_on_hand (corner)
# --------------------------------------------------------------------------- #
def test_dropship_line_confirms_without_touching_stock(api):
    """PRD §3.5: "Each `DROPSHIP` line instead moves to `DROPSHIP_PENDING` and never draws from
    `on_hand_qty`."

    Design: Corner/calculations/dropship_line_does_not_touch_on_hand
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="DS-1", name="Custom Signage", category="CONSUMABLE",
                                   unit_price_cents=700, case_qty=100, case_price_cents=65000,
                                   pallet_case_qty=10, pallet_price_cents=600000,
                                   fulfillment_type="DROPSHIP", on_hand_qty=0, par_level=0,
                                   reorder_point=0)
    order = fixtures.create_order(api, acct["id"])
    line = fixtures.add_line(api, order["id"], acct["id"], prod["id"], 5)
    fixtures.confirm_order(api, order["id"], acct["id"])
    line_after = validate_success(api.get_order_line(line["id"], WH))
    prod_after = validate_success(api.get_product(prod["id"], WH))
    assert line_after["status"] == "DROPSHIP_PENDING"
    assert line_after["allocated_qty"] == 0
    assert prod_after["on_hand_qty"] == 0


# --------------------------------------------------------------------------- #
# cross_cutting / credit_limit_exceeded_alone_rejected (corner)
# --------------------------------------------------------------------------- #
def test_confirm_over_credit_limit_rejected(api):
    """PRD §3.5: "the order's `total_cents` computed as merchandise subtotal plus tax, with freight
    still 0, must be less than or equal to the account's `credit_available_cents`
    (`ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Corner/cross_cutting_complexity_layers/credit_limit_exceeded_alone_rejected
    """
    acct = fixtures.create_account(api, credit_limit_cents=5000)
    prod = fixtures.create_product(api, sku="CR-1", unit_price_cents=6000, case_qty=100,
                                   case_price_cents=500000, pallet_case_qty=10,
                                   pallet_price_cents=4500000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 1)  # 6000 + 480 tax = 6480 > 5000
    version = fixtures.account_version(api, acct["id"])
    resp = api.confirm_order(order["id"], {"expected_account_version": version},
                             make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


# --------------------------------------------------------------------------- #
# cross_cutting / confirm_stale_account_version_conflict (corner)
# --------------------------------------------------------------------------- #
def test_confirm_with_stale_account_version_rejected(api):
    """PRD §2.9: "a confirm still carrying the earlier `expected_account_version` is rejected as
    stale with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/confirm_stale_account_version_conflict
    """
    acct = fixtures.create_account(api)
    v0 = acct["version"]
    prod = fixtures.create_product(api, sku="OCC-1", unit_price_cents=500, case_qty=100,
                                   case_price_cents=45000, pallet_case_qty=10,
                                   pallet_price_cents=420000, par_level=50)
    order1 = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order1["id"], acct["id"], prod["id"], 2)
    order2 = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order2["id"], acct["id"], prod["id"], 2)
    # First confirm succeeds and advances Account.version past v0.
    validate_success(api.confirm_order(order1["id"], {"expected_account_version": v0},
                                       make_buyer_headers(acct["id"])))
    resp = api.confirm_order(order2["id"], {"expected_account_version": v0},
                             make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)
    order2_after = validate_success(api.get_order(order2["id"], WH))
    assert order2_after["lifecycle_status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# state_machines / confirm_already_confirmed_order_returns_not_draft (corner)
# --------------------------------------------------------------------------- #
def test_reconfirm_confirmed_order_rejected_not_draft(api):
    """PRD §3.5: "the order must be in `DRAFT` (`ERR_ORDER_NOT_DRAFT`)".

    Design: Corner/state_machines/confirm_already_confirmed_order_returns_not_draft
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="SM-1", unit_price_cents=300, case_qty=12,
                                   case_price_cents=3200, pallet_case_qty=10, pallet_price_cents=30000,
                                   par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 3)
    version = fixtures.account_version(api, acct["id"])
    validate_success(api.confirm_order(order["id"], {"expected_account_version": version},
                                       make_buyer_headers(acct["id"])))
    resp = api.confirm_order(order["id"], {"expected_account_version": version},
                             make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT.value)


# --------------------------------------------------------------------------- #
# state_machines / cancel_cancelled_order_terminal_lockdown (corner)
# --------------------------------------------------------------------------- #
def test_cancel_already_cancelled_order_rejected(api):
    """PRD §3.5: "Cancellation is available while an order is `DRAFT` or `CONFIRMED`; attempting it
    in any other state is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_cancelled_order_terminal_lockdown
    """
    acct = fixtures.create_account(api, credit_limit_cents=100000)
    order = fixtures.create_order(api, acct["id"])
    validate_success(api.cancel_order(order["id"], make_buyer_headers(acct["id"])))
    resp = api.cancel_order(order["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)


# --------------------------------------------------------------------------- #
# state_machines / payment_dimension_advances_independently (corner)
# --------------------------------------------------------------------------- #
def test_invoice_then_pay_advances_payment_dimension(api):
    """PRD §3.6: "An `AccountManager` invoices an order whose `lifecycle_status` is `CONFIRMED` or
    `SHIPPED` (otherwise `ERR_ORDER_NOT_CONFIRMED`) and whose `payment_status` is `UNPAID`
    (otherwise `ERR_PAYMENT_NOT_UNPAID`); this moves the payment dimension to `INVOICED` while
    leaving `lifecycle_status` untouched."
    PRD §3.6: "The owning `Buyer` then records payment on an order whose `payment_status` is
    `INVOICED` (otherwise `ERR_PAYMENT_NOT_INVOICED`); this moves the payment dimension to `PAID`".

    Design: Corner/state_machines/payment_dimension_advances_independently
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="PAY-1", unit_price_cents=200, case_qty=12,
                                   case_price_cents=2100, pallet_case_qty=10, pallet_price_cents=20000,
                                   par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 3)
    fixtures.confirm_order(api, order["id"], acct["id"])
    validate_success(api.invoice_order(order["id"], AM))
    paid = validate_success(api.pay_order(order["id"], make_buyer_headers(acct["id"])))
    assert paid["payment_status"] == "PAID"
    assert paid["lifecycle_status"] == "CONFIRMED"
