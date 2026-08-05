"""Commissary accounts, order pricing, fulfillment, refunds, and money conservation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, fixtures, assert_ledger_conserved,
)
from test_helpers import factories as f

INTAKE = TEST_USERS["intake_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ---------------------------------------------------------------------------
# combinatorial_formula / commissary_order_round_per_line_then_sum_mode_b
# ---------------------------------------------------------------------------
def test_order_total_rounds_per_line_then_sums(api):
    """PRD §3.4: "each line's raw amount is then rounded half-up to whole cents to yield the
    line total. The `order_total_cents` is the sum of the per-line totals plus a flat service
    fee of 25 cents. This per-line-then-sum ordering is mandatory; summing raw amounts before
    rounding is incorrect."

    Design: Difficulty/combinatorial_formula/commissary_order_round_per_line_then_sum_mode_b
    """
    booking, account = fixtures.setup_account_with_deposit(api, 1000)
    order = fixtures.place_order(api, account["id"], fixtures.three_taxable_lines(), account["version"])
    assert order["order_total_cents"] == 364, (
        f"expected 364 (round(112.6125)=113 x3 + 25), got {order['order_total_cents']}"
    )


def test_order_total_not_sum_then_round(api):
    """PRD §2.9: "rounding happens per line before the lines are summed, never after."

    Design: Difficulty/combinatorial_formula/commissary_order_round_per_line_then_sum_mode_b
    """
    booking, account = fixtures.setup_account_with_deposit(api, 1000)
    order = fixtures.place_order(api, account["id"], fixtures.three_taxable_lines(), account["version"])
    # sum-then-round would give round(315 * 1.0725)=338, +25 = 363 (the wrong answer).
    assert order["order_total_cents"] == 364, f"got {order['order_total_cents']}"
    assert order["order_total_cents"] != 363, "must not be the sum-then-round result"


# ---------------------------------------------------------------------------
# boundary_precision_check / order_empty_lines_zero_edge
# ---------------------------------------------------------------------------
def test_order_empty_lines_rejected(api):
    """PRD §3.4: "An order with an empty `lines` array or a non-positive `quantity` is rejected
    with `ERR_VALIDATION`."

    Design: Difficulty/boundary_precision_check/order_empty_lines_zero_edge
    """
    booking, account = fixtures.setup_account_with_deposit(api, 1000)
    resp = api.create_order(account["id"], f.create_order_payload([], account["version"]), INTAKE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_order_empty_lines_creates_no_order(api):
    """PRD §3.4: "An order with an empty `lines` array or a non-positive `quantity` is rejected
    with `ERR_VALIDATION`."

    Design: Difficulty/boundary_precision_check/order_empty_lines_zero_edge
    """
    booking, account = fixtures.setup_account_with_deposit(api, 1000)
    api.create_order(account["id"], f.create_order_payload([], account["version"]), INTAKE)
    data, meta = validate_paginated(api.list_orders(account["id"], INTAKE))
    assert meta["total_count"] == 0, f"a rejected order must not be persisted, got {meta['total_count']}"


# ---------------------------------------------------------------------------
# validations / order_insufficient_funds_at_create
# ---------------------------------------------------------------------------
def test_order_insufficient_funds_at_create(api):
    """PRD §3.4: "The system also verifies at create time that the account's `balance_cents`
    covers the computed `order_total_cents`; if it does not, the order is rejected with
    `ERR_INSUFFICIENT_FUNDS`."

    Design: Corner/validations/order_insufficient_funds_at_create
    """
    booking, account = fixtures.setup_account_with_deposit(api, 300)
    resp = api.create_order(
        account["id"], f.create_order_payload(fixtures.three_taxable_lines(), account["version"]), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / order_released_booking_beats_insufficient_funds
# ---------------------------------------------------------------------------
def _setup_released_booking_with_account(api):
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=40)
    account = fixtures.get_account_for_booking(api, booking["id"])  # balance 0, version 1
    validate_success(api.release_booking(booking["id"], f.release_payload("COURT_ORDER"), SUPERVISOR))
    return account


def test_order_on_released_booking_returns_booking_released(api):
    """PRD §3.8: "Attempting to place a commissary order, schedule a court event, create a
    housing assignment, request a visit, or file a request against a `RELEASED` booking is
    rejected with `ERR_BOOKING_RELEASED`."

    Design: Difficulty/priority_pair_validation_conflict/order_released_booking_beats_insufficient_funds
    """
    account = _setup_released_booking_with_account(api)
    lines = [f.order_line("chips", 1, 500, False)]
    resp = api.create_order(account["id"], f.create_order_payload(lines, account["version"]), INTAKE)
    validate_error(resp, ApiErrorId.ERR_BOOKING_RELEASED.value)


def test_released_booking_check_precedes_insufficient_funds(api):
    """PRD §2.6: precedence begins the §3 rules with "booking-not-released, ... sufficient
    funds, and finally release eligibility", so the released-booking state check outranks the
    funds check even when the balance cannot cover the order.

    Design: Difficulty/priority_pair_validation_conflict/order_released_booking_beats_insufficient_funds
    """
    account = _setup_released_booking_with_account(api)
    lines = [f.order_line("chips", 1, 500, False)]  # 500c > balance 0
    resp = api.create_order(account["id"], f.create_order_payload(lines, account["version"]), INTAKE)
    err = validate_error(resp, ApiErrorId.ERR_BOOKING_RELEASED.value)
    assert err["error_id"] != ApiErrorId.ERR_INSUFFICIENT_FUNDS.value, (
        "released-booking state check must pre-empt the funds check"
    )


# ---------------------------------------------------------------------------
# compensating_invariant / commissary_money_conservation
# ---------------------------------------------------------------------------
def test_fulfill_debits_balance_and_conserves_ledger(api):
    """PRD §3.4: "moves the order from `PENDING` to `FULFILLED`, debits the account's
    `balance_cents` by the `order_total_cents`, and increments the account's `version`."
    PRD §2.9: "the sum of an account's funds plus the value tied up in fulfilled-but-not-refunded
    orders is preserved across every legal transition".

    Design: Difficulty/compensating_invariant/commissary_money_conservation
    """
    account_id, order = fixtures.setup_fulfilled_order(api, deposit_cents=1000)
    account = get_success_data(api.get_commissary_account_by_id(account_id, INTAKE))
    assert account["balance_cents"] == 636, f"expected 636 (1000-364), got {account['balance_cents']}"
    assert_ledger_conserved(account, expected_fulfilled_total=364)


def test_refund_restores_balance_and_conserves_ledger(api):
    """PRD §3.4: "refunding moves it from `FULFILLED` to `REFUNDED`, credits the account's
    `balance_cents` back by exactly the `order_total_cents`, and increments the account's
    `version` — restoring the ledger-conservation invariant of §2.9."

    Design: Difficulty/compensating_invariant/commissary_money_conservation
    """
    account_id, order = fixtures.setup_fulfilled_order(api, deposit_cents=1000)
    validate_success(api.refund_order(order["id"], SUPERVISOR))
    account = get_success_data(api.get_commissary_account_by_id(account_id, INTAKE))
    assert account["balance_cents"] == 1000, f"expected 1000 restored, got {account['balance_cents']}"
    assert_ledger_conserved(account, expected_fulfilled_total=0)


# ---------------------------------------------------------------------------
# state_machines / fulfill_already_fulfilled_order_returns_invalid_state
# ---------------------------------------------------------------------------
def test_fulfill_already_fulfilled_order_rejected(api):
    """PRD §3.4: "An `IntakeOfficer` fulfills an order that is currently `PENDING`".
    PRD §3.5: "Acting on an event that is not in a valid source state for the requested
    transition is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/fulfill_already_fulfilled_order_returns_invalid_state
    """
    account_id, order = fixtures.setup_fulfilled_order(api, deposit_cents=1000)
    resp = api.fulfill_order(order["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    account = get_success_data(api.get_commissary_account_by_id(account_id, INTAKE))
    assert account["balance_cents"] == 636, (
        f"balance must be debited once only, got {account['balance_cents']}"
    )


# ---------------------------------------------------------------------------
# cross_cutting / order_stale_account_version_conflict
# ---------------------------------------------------------------------------
def test_order_off_stale_account_version_rejected(api):
    """PRD §2.5: "Deposits, fulfillments, and refunds all advance the account's `version`; if
    the supplied value does not equal the account's current `version`, the order is rejected
    with `ERR_STALE_VERSION` (HTTP 412) so the client re-reads the current balance before
    committing."

    Design: Corner/cross_cutting/order_stale_account_version_conflict
    """
    booking, account = fixtures.setup_account_with_deposit(api, 2000)
    stale_version = account["version"]
    # First order off the current version advances it to a new value.
    fixtures.place_order(api, account["id"], [f.order_line("soap", 1, 105, True)], stale_version)
    resp = api.create_order(
        account["id"], f.create_order_payload([f.order_line("pen", 1, 105, True)], stale_version), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# cross_cutting / version_increments_on_deposit
# ---------------------------------------------------------------------------
def test_each_deposit_increments_account_version(api):
    """PRD §3.4: "a deposit adds that amount to `balance_cents`, adds the same amount to the
    lifetime `total_deposited_cents`, and increments the account's `version`."
    PRD §2.4: "an integer `version` that starts at 1 and increments by 1 on every mutation."

    Design: Corner/cross_cutting/version_increments_on_deposit
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=60)
    account = fixtures.get_account_for_booking(api, booking["id"])  # version 1 at auto-create
    after1 = get_success_data(api.deposit(account["id"], f.deposit_payload(100), INTAKE))
    assert after1["version"] == 2, f"expected 2 after first deposit, got {after1['version']}"
    after2 = get_success_data(api.deposit(account["id"], f.deposit_payload(100), INTAKE))
    assert after2["version"] == 3, f"expected 3 after second deposit, got {after2['version']}"


# ---------------------------------------------------------------------------
# consistency_model / deposit_immediately_visible_in_balance
# ---------------------------------------------------------------------------
def test_deposit_immediately_visible_in_balance(api):
    """PRD §3.4: "An `IntakeOfficer` deposits funds by supplying an `amount_cents`; a deposit
    adds that amount to `balance_cents`".

    Design: Corner/consistency_model/deposit_immediately_visible_in_balance
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=30)
    account = fixtures.get_account_for_booking(api, booking["id"])
    api.deposit(account["id"], f.deposit_payload(500), INTAKE)
    fetched = get_success_data(api.get_commissary_account_by_id(account["id"], INTAKE))
    assert fetched["balance_cents"] == 500, f"expected 500, got {fetched['balance_cents']}"
