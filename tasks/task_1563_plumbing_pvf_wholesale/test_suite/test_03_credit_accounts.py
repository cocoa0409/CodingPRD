"""Credit policy: hold hysteresis, past-due aging, limits, payments (PRD §2.9, §3.3, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_credit_exposure,
    create_order_line_payload,
    create_order_payload,
    create_payment_payload,
    create_picked_up_order,
    create_submitted_order,
    make_account,
    make_branch,
    make_product,
    make_stock,
    set_clock,
    setup_branch_product_account,
    validate_error,
    validate_success,
)

TEST_MANAGER = TEST_USERS["manager_headers"]
TEST_REP = TEST_USERS["counterrep_headers"]
TEST_SALES = TEST_USERS["sales_headers"]


def _p1_world(stock=20, **account_overrides):
    """Branch + P1 (list 10000, cost 5000, cubes 10) + account + stock row."""
    branch, product, account = setup_branch_product_account(
        account_overrides=account_overrides, stock=stock
    )
    return branch, product, account


class TestCreditLimitGate:
    def test_credit_limit_equality_submits(self, api, counterrep_headers):
        """PRD §3.7: "the account's forward exposure plus this order's
        `total_cents` must stay within `credit_limit_cents`, with equality
        allowed — a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 402)".

        A STANDARD account with limit 50000 submits an order totalling exactly
        50000 (47500 subtotal + 2500 freight): equality is allowed.

        Design: Difficulty/boundary_precision_check/credit_limit_equality_submits
        """
        branch = make_branch()
        product = make_product(sku="PL", description="Copper elbow", category="FITTING",
                               list_price_cents=4750, cost_cents=2000, cubes_per_unit=1)
        account = make_account(company_name="Std Co", pricing_tier="STANDARD",
                               terms="COD", credit_limit_cents=50000)
        make_stock(branch["id"], product["id"], 10)
        order, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 10)])
        assert order["fulfillment_status"] in ("OPEN", "PICKING"), (
            f"equality submit must succeed, got {order['fulfillment_status']}"
        )
        assert order["total_cents"] == 50000

    def test_credit_limit_equality_zeroes_available_credit(self, api, sales_headers):
        """PRD §2.9: "The account's headroom is `available_credit_cents`, defined
        as `credit_limit_cents` minus `forward_exposure_cents`; it may
        legitimately go negative."
        PRD §3.7: "The account's `forward_exposure_cents` now counts the order."

        After the equality submit, forward exposure equals the limit, so
        available credit reads exactly 0.

        Design: Difficulty/boundary_precision_check/credit_limit_equality_submits
        """
        branch = make_branch()
        product = make_product(sku="PL", description="Copper elbow", category="FITTING",
                               list_price_cents=4750, cost_cents=2000, cubes_per_unit=1)
        account = make_account(company_name="Std Co", pricing_tier="STANDARD",
                               terms="COD", credit_limit_cents=50000)
        make_stock(branch["id"], product["id"], 10)
        create_submitted_order(account["id"], branch["id"], [(product["id"], 10)])
        exposure = validate_success(api.get_credit_exposure(account["id"], sales_headers))
        assert_credit_exposure(exposure)
        assert exposure["available_credit_cents"] == 0, (
            f"available credit must be exactly 0 after the equality submit, got {exposure['available_credit_cents']}"
        )

    def test_credit_exceeded_by_one_cent_rejected(self, api, counterrep_headers, sales_headers):
        """PRD §3.7: "the account's forward exposure plus this order's
        `total_cents` must stay within `credit_limit_cents`, with equality
        allowed — a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 402)".

        Total 50001 against a 50000 limit breaches by one cent; the order stays
        DRAFT.

        Design: Corner/validations/credit_exceeded_by_one_cent_rejected
        """
        branch = make_branch()
        product = make_product(sku="PX", description="Pricey", category="FITTING",
                               list_price_cents=47501, cost_cents=1000, cubes_per_unit=1)
        account = make_account(company_name="Std Co", pricing_tier="STANDARD",
                               terms="COD", credit_limit_cents=50000)
        make_stock(branch["id"], product["id"], 1)
        order = validate_success(
            api.create_order(create_order_payload(account["id"], branch["id"]), counterrep_headers), 201
        )
        validate_success(
            api.add_order_line(order["id"], create_order_line_payload(product["id"], 1), counterrep_headers),
            201,
        )
        res = api.submit_order(order["id"], counterrep_headers)
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        after = validate_success(api.get_order(order["id"], sales_headers))
        assert after["fulfillment_status"] == "DRAFT"


class TestAccountHoldGatesSubmit:
    def _setup_past_due_account(self):
        """NET_15 account with a picked-up (INVOICED) order, then clock +19 days."""
        branch, product, account = _p1_world(stock=20, terms="NET_15")
        create_picked_up_order(account["id"], branch["id"], [(product["id"], 2)])
        set_clock("2026-08-20T00:00:00Z")
        return branch, product, account

    def test_past_due_invoice_engages_credit_hold(self, api, sales_headers):
        """PRD §2.9: "A hold engages automatically — after any balance recompute
        or clock advance — when the statement balance is strictly greater than
        `credit_limit_cents` (equality alone does not engage), or when any
        invoiced order has gone past due. An invoice is past due when the logical
        clock has passed its `invoiced_at` by more than the account's payment
        terms: `COD` terms allow zero days, `NET_15` allows fifteen days, and
        `NET_30` allows thirty days."

        Invoiced 2026-08-01 under NET_15; at 2026-08-20 (19 days) the sweep
        engages CREDIT_HOLD.

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_account_hold
        """
        _, _, account = self._setup_past_due_account()
        after = validate_success(api.get_account(account["id"], sales_headers))
        assert after["status"] == "CREDIT_HOLD", (
            f"past-due NET_15 invoice must engage CREDIT_HOLD, got {after['status']}"
        )

    def test_submit_on_credit_hold_rejected(self, api, counterrep_headers, sales_headers):
        """PRD §3.7: "Three gates stand in front of it, in pipeline order: the
        account must be `ACTIVE` — a `CREDIT_HOLD` or `SUSPENDED` account rejects
        the submission with `ERR_ACCOUNT_CREDIT_HOLD`".

        The second order is itself valid and far under the limit; the gate is
        the account's standing.

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_account_hold
        """
        branch, product, account = self._setup_past_due_account()
        order = validate_success(
            api.create_order(create_order_payload(account["id"], branch["id"]), counterrep_headers), 201
        )
        validate_success(
            api.add_order_line(order["id"], create_order_line_payload(product["id"], 1), counterrep_headers),
            201,
        )
        res = api.submit_order(order["id"], counterrep_headers)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_CREDIT_HOLD)
        after = validate_success(api.get_order(order["id"], sales_headers))
        assert after["fulfillment_status"] == "DRAFT"


class TestHoldHysteresis:
    def _setup_over_limit_via_tightening(self, api):
        """Balance 108000 (picked-up order), then ADJUST_LIMIT tightens to 100000."""
        branch, product, account = _p1_world(
            stock=20, terms="NET_30", credit_limit_cents=200000
        )
        picked, _ = create_picked_up_order(account["id"], branch["id"], [(product["id"], 12)])
        assert picked["payment_status"] == "INVOICED"
        mid = validate_success(api.get_account(account["id"], TEST_SALES))
        assert mid["status"] == "ACTIVE", "108000 <= 200000 and nothing past due"
        tightened = validate_success(api.credit_review(
            account["id"], {"action": "ADJUST_LIMIT", "new_credit_limit_cents": 100000},
            TEST_MANAGER,
        ))
        return branch, product, account, tightened

    def test_hold_engages_on_limit_tightening_and_persists_in_dead_band(self, api):
        """PRD §2.9: "A hold engages automatically — after any balance recompute
        or clock advance — when the statement balance is strictly greater than
        `credit_limit_cents` (equality alone does not engage)" and "Between
        eighty and one hundred percent utilization, an engaged hold persists;
        between them lies the dead band that gives the cycle its memory."

        Tightening the limit to 100000 against a 108000 balance engages the hold;
        a 20000 payment leaves 88000 > 80000 (80% threshold), so the hold
        persists.

        Design: Difficulty/non_linear_state_machine/account_credit_hold_hysteresis_cycle
        """
        _, _, account, tightened = self._setup_over_limit_via_tightening(api)
        assert tightened["status"] == "CREDIT_HOLD", (
            f"108000 > 100000 must engage the hold, got {tightened['status']}"
        )
        validate_success(api.create_payment(account["id"], create_payment_payload(20000, method="CHECK"), TEST_REP), 201)
        after = validate_success(api.get_account(account["id"], TEST_SALES))
        assert after["outstanding_balance_cents"] == 88000
        assert after["status"] == "CREDIT_HOLD", (
            f"88000 > 80000 release threshold — hold must persist, got {after['status']}"
        )

    def test_hold_releases_at_exactly_eighty_percent(self, api):
        """PRD §2.9: "A hold releases automatically only when both conditions
        clear together: the statement balance has fallen to at most eighty
        percent of `credit_limit_cents` — the threshold itself rounded half up to
        a whole cent, with a balance exactly equal to the threshold releasing —
        and no past-due invoice remains."

        A further 8000 payment lands the balance at exactly 80000 == 80% of
        100000, and the hold releases.

        Design: Difficulty/non_linear_state_machine/account_credit_hold_hysteresis_cycle
        """
        _, _, account, tightened = self._setup_over_limit_via_tightening(api)
        assert tightened["status"] == "CREDIT_HOLD"
        validate_success(api.create_payment(account["id"], create_payment_payload(20000, method="CHECK"), TEST_REP), 201)
        validate_success(api.create_payment(account["id"], create_payment_payload(8000, method="CHECK"), TEST_REP), 201)
        after = validate_success(api.get_account(account["id"], TEST_SALES))
        assert after["outstanding_balance_cents"] == 80000
        assert after["status"] == "ACTIVE", (
            f"balance exactly at the 80% threshold must release the hold, got {after['status']}"
        )


class TestPastDueHoldAndRelease:
    def test_past_due_hold_releases_after_full_payment(self, api, sales_headers):
        """PRD §2.9: "A hold releases automatically only when both conditions clear together: the statement balance has fallen to at most eighty percent of `credit_limit_cents` — the threshold itself rounded half up to a whole cent, with a balance exactly equal to the threshold releasing — and no past-due invoice remains."
        PRD §3.3: "a payment that brings the statement balance back under the
        release threshold while no invoice is past due lifts the hold."

        A NET_15 invoice goes past due at day 16 (clock sweep engages the hold);
        paying it in full flips the order PAID and the account back to ACTIVE.

        Design: Corner/cross_cutting_layers/past_due_hold_and_release_cycle
        """
        branch, product, account = _p1_world(stock=5, terms="NET_15")
        order, _ = create_picked_up_order(account["id"], branch["id"], [(product["id"], 2)])
        assert order["total_cents"] == 20500

        set_clock("2026-08-17T00:00:00Z")
        held = validate_success(api.get_account(account["id"], sales_headers))
        assert held["status"] == "CREDIT_HOLD", (
            f"16 days past NET_15 invoicing must engage the hold, got {held['status']}"
        )

        validate_success(api.create_payment(
            account["id"], create_payment_payload(20500, method="ACH"), TEST_REP
        ), 201)
        released = validate_success(api.get_account(account["id"], sales_headers))
        assert released["outstanding_balance_cents"] == 0
        assert released["status"] == "ACTIVE", (
            f"full payment with no past-due invoices must release the hold, got {released['status']}"
        )
        order_after = validate_success(api.get_order(order["id"], sales_headers))
        assert order_after["payment_status"] == "PAID"


class TestPayments:
    def test_invoice_then_payment_conserves_zero_balance(self, api, sales_headers):
        """PRD §2.9: "The statement view, exposed as `outstanding_balance_cents`,
        is the chronological ledger balance: the sum of `total_cents` over orders
        whose `payment_status` is `INVOICED` or `PAID`, minus the sum of all
        payment `amount_cents` posted to the account, minus the sum of
        `credit_cents` over return requests that have reached `CREDITED`."

        Invoicing +38500 at pickup and a compensating payment of 38500 return
        the balance to exactly 0.

        Design: Difficulty/compensating_invariant/invoice_payment_conserves_balance
        """
        branch, product, account = _p1_world(stock=10)
        order, _ = create_picked_up_order(account["id"], branch["id"], [(product["id"], 4)])
        assert order["payment_status"] == "INVOICED"
        mid = validate_success(api.get_account(account["id"], sales_headers))
        assert mid["outstanding_balance_cents"] == 38500

        validate_success(api.create_payment(
            account["id"], create_payment_payload(38500, method="ACH"), TEST_REP
        ), 201)
        after = validate_success(api.get_account(account["id"], sales_headers))
        assert after["outstanding_balance_cents"] == 0, (
            f"38500 invoiced - 38500 paid must conserve 0, got {after['outstanding_balance_cents']}"
        )

    def test_full_payment_flips_order_to_paid(self, api, sales_headers):
        """PRD §3.3: "An order whose allocations reach its `total_cents` flips
        from `INVOICED` to `PAID`, its terminal payment state."

        Design: Difficulty/compensating_invariant/invoice_payment_conserves_balance
        """
        branch, product, account = _p1_world(stock=10)
        order, _ = create_picked_up_order(account["id"], branch["id"], [(product["id"], 4)])
        validate_success(api.create_payment(
            account["id"], create_payment_payload(38500, method="ACH"), TEST_REP
        ), 201)
        after = validate_success(api.get_order(order["id"], sales_headers))
        assert after["payment_status"] == "PAID"
        assert after["fulfillment_status"] == "PICKED_UP"

    def test_payment_fifo_auto_allocation_oldest_invoice_first(self, api, sales_headers):
        """PRD §3.3: "When `allocations` is omitted, the payment spreads itself
        FIFO: the account's `INVOICED` orders are visited oldest first by
        `invoiced_at`, with ties broken by the order's `created_at` — never by
        id — and each order receives the smaller of what it is still owed (its
        `total_cents` less what prior payments already allocated to it) and the
        remaining unapplied payment."
        PRD §3.3: "Either way, explicit or automatic, the posting subtracts the
        full `amount_cents` from the account's `outstanding_balance_cents`
        exactly once".

        A 40000 payment covers order A (38500, oldest) to PAID and spills only
        1500 onto order B, which stays INVOICED; the balance drops exactly once.

        Design: Corner/calculations/payment_fifo_auto_allocation_oldest_invoice_first
        """
        branch, product, account = _p1_world(stock=20)
        order_a, _ = create_picked_up_order(account["id"], branch["id"], [(product["id"], 4)])
        order_b, _ = create_picked_up_order(account["id"], branch["id"], [(product["id"], 2)])
        mid = validate_success(api.get_account(account["id"], sales_headers))
        assert mid["outstanding_balance_cents"] == 59000

        validate_success(api.create_payment(
            account["id"], create_payment_payload(40000, method="ACH"), TEST_REP
        ), 201)
        a = validate_success(api.get_order(order_a["id"], sales_headers))
        b = validate_success(api.get_order(order_b["id"], sales_headers))
        account_after = validate_success(api.get_account(account["id"], sales_headers))
        assert a["payment_status"] == "PAID", "oldest invoice must be fully covered first"
        assert b["payment_status"] == "INVOICED", "only 1500 spills to the newer invoice"
        assert account_after["outstanding_balance_cents"] == 19000, (
            f"59000 - 40000 must be 19000, got {account_after['outstanding_balance_cents']}"
        )
