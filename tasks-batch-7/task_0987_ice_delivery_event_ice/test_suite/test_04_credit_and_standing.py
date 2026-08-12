"""Credit exposure variants, credit gates, and standing (PRD §3.5, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agent,
    confirm,
    full_book_payload,
    generate_invoice,
    get_customer,
    get_success_data,
    issue_invoice,
    make_active_book,
    make_customer,
    make_depot,
    make_order,
    make_payment,
    order_line,
    picked_up_order,
    quote,
    quoted_order,
    run_ops,
    set_logical_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK_1 = TEST_USERS["billing_clerk_1_headers"]
CLERK_2 = TEST_USERS["billing_clerk_2_headers"]

# 30x(CUBE,BAG)@300 + 2x(BLOCK,PALLET)@21000 under the full fixture book:
# merchandise 51000, discount 2550 (500bps), deposit 3000, WILL_CALL total 51450.
BIG_LINES = [order_line("CUBE", "BAG", 30), order_line("BLOCK", "PALLET", 2)]
BIG_TOTAL = 51450
# 33x(CUBE,BAG)@300 = 9900 exactly (no deposit, WILL_CALL).
SMALL_LINES = [order_line("CUBE", "BAG", 33)]
SMALL_TOTAL = 9900


# --------------------- difficulty: settled vs forward-looking exposure ----

def test_forward_looking_check_admits_equality_and_rejects_above(api):
    """PRD §3.8: "Confirmation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 402) when the forward-looking exposure plus the candidate order's
    `total_cents` exceeds the customer's `credit_limit_cents` plus the
    spendable `credit_balance_cents`; equality is admitted."

    Design: Difficulty/dual_variant_calc/credit_exposure_settled_vs_forward_looking
    """
    depot = make_depot(10, "Depot CE")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust_a = make_customer(
        account_name="Bar A", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=60000,
    )
    cust_b = make_customer(
        account_name="Bar B", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=61350,
    )

    # Both customers already hold one CONFIRMED uninvoiced order of 51450.
    order_a1 = quoted_order(
        cust_a["id"], depot["id"], BIG_LINES,
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    confirm(order_a1["id"], cust_a["id"])
    order_b1 = quoted_order(
        cust_b["id"], depot["id"], BIG_LINES,
        channel="WILL_CALL", event_date="2026-05-22",
        window_start="10:00", window_end="12:00",
    )
    confirm(order_b1["id"], cust_b["id"])

    order_a2 = quoted_order(
        cust_a["id"], depot["id"], SMALL_LINES,
        channel="WILL_CALL", event_date="2026-05-21",
        window_start="10:00", window_end="12:00",
    )
    assert order_a2["total_cents"] == SMALL_TOTAL
    order_b2 = quoted_order(
        cust_b["id"], depot["id"], SMALL_LINES,
        channel="WILL_CALL", event_date="2026-05-23",
        window_start="10:00", window_end="12:00",
    )

    resp_a = api.confirm_order(order_a2["id"], agent(cust_a["id"]))
    validate_error(resp_a, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    # forward-looking 51450 + 9900 = 61350 > 60000 + 0

    confirmed_b = confirm(order_b2["id"], cust_b["id"])
    assert confirmed_b["fulfillment_status"] == "CONFIRMED", (
        "61350 <= 61350 + 0: equality admitted"
    )

    customer_a = get_customer(cust_a["id"])
    assert customer_a["outstanding_exposure_cents"] == 0, (
        "settled variant: no issued invoices exist, so the display stays zero"
    )


def test_settled_display_ignores_confirmed_uninvoiced_pipeline(api):
    """PRD §3.8: "The settled variant sums `balance_due_cents` over the
    customer's invoices in `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE`; this is
    what `outstanding_exposure_cents` displays, so a customer with large
    confirmed-but-uninvoiced orders still shows zero."

    Design: Difficulty/dual_variant_calc/credit_exposure_settled_vs_forward_looking
    """
    depot = make_depot(10, "Depot CE2b")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="Bar Settled", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=52000,
    )
    order1 = quoted_order(
        cust["id"], depot["id"], BIG_LINES,
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    confirm(order1["id"], cust["id"])
    # 51450 (pipeline) + 350 (candidate) = 51800 <= 52000: admitted.
    order2 = quoted_order(
        cust["id"], depot["id"], [order_line("CUBE", "BAG", 1)],
        channel="WILL_CALL", event_date="2026-05-21",
        window_start="10:00", window_end="12:00",
    )
    confirmed = confirm(order2["id"], cust["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED"

    customer = get_customer(cust["id"])
    assert customer["outstanding_exposure_cents"] == 0, (
        "no invoice has been issued: settled exposure displays zero despite "
        "51800 of confirmed-uninvoiced pipeline"
    )
    assert customer["standing"] == "GOOD"


# --------------------- difficulty: credit-limit boundary ----------------------

def test_credit_limit_exact_equality_admitted(api):
    """PRD §3.8: "Confirmation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 402) when the forward-looking exposure plus the candidate order's
    `total_cents` exceeds the customer's `credit_limit_cents` plus the
    spendable `credit_balance_cents`; equality is admitted."

    Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_admitted
    """
    depot = make_depot(10, "Depot BP1")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust_a = make_customer(
        account_name="BP1 A", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=51450,
    )
    cust_b = make_customer(
        account_name="BP1 B", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=51449,
    )
    order_a = quoted_order(
        cust_a["id"], depot["id"], BIG_LINES,
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    assert order_a["total_cents"] == 51450
    order_b = quoted_order(
        cust_b["id"], depot["id"], BIG_LINES,
        channel="WILL_CALL", event_date="2026-05-21",
        window_start="10:00", window_end="12:00",
    )

    confirmed_a = confirm(order_a["id"], cust_a["id"])
    assert confirmed_a["fulfillment_status"] == "CONFIRMED", (
        "boundary: 51450 == 51450 + 0 is admitted"
    )

    resp_b = api.confirm_order(order_b["id"], agent(cust_b["id"]))
    validate_error(resp_b, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    # 51450 > 51449 by exactly one cent


def test_credit_balance_extends_limit_to_equality(api):
    """PRD §3.8: "Confirmation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 402) when the forward-looking exposure plus the candidate order's
    `total_cents` exceeds the customer's `credit_limit_cents` plus the
    spendable `credit_balance_cents`; equality is admitted."
    PRD §3.8: "Whatever remains unallocated is the payment's
    `overpayment_cents`, credited to the customer's `credit_balance_cents`".

    Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_admitted
    """
    depot = make_depot(10, "Depot BP1b")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="BP1 Wallet", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=50000,
    )
    payment = make_payment(cust["id"], 1450, method="ACH")
    assert payment["overpayment_cents"] == 1450
    assert get_customer(cust["id"])["credit_balance_cents"] == 1450

    order = quoted_order(
        cust["id"], depot["id"], BIG_LINES,
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    assert order["total_cents"] == 51450
    confirmed = confirm(order["id"], cust["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        "51450 <= 50000 limit + 1450 wallet: equality admitted"
    )


# --------------------- difficulty: standing gate on confirm -------------------

def _setup_overdue_standing_hold(cust, depot, clerk_headers=CLERK_1):
    """PICKED_UP 2-pallet order -> invoice 45000 ISSUED (due 2026-05-31) ->
    clock 2026-06-01 -> ops checkpoint -> OVERDUE + standing HOLD."""
    order1 = picked_up_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    assert order1["fulfillment_status"] == "PICKED_UP"
    invoice = issue_invoice(
        generate_invoice(cust["id"], "2026-05-01", "2026-06-01", clerk_headers)["id"],
        clerk_headers,
    )
    assert invoice["total_cents"] == 45000
    set_logical_clock("2026-06-01T09:00:00Z")
    ops = run_ops(depot["id"])
    assert invoice["id"] in ops["overdue_invoice_ids"], (
        "aging sweep must move the unpaid invoice to OVERDUE"
    )
    assert get_customer(cust["id"])["standing"] == "HOLD"
    return order1, invoice


def test_confirm_blocked_while_standing_hold_then_unblocked_by_payment(api):
    """PRD §3.8: "Separately, any `OVERDUE` invoice puts `standing` on `HOLD`,
    which blocks confirmation earlier in the gauntlet with `ERR_CREDIT_HOLD`
    (HTTP 402) (§3.5)."
    PRD §3.8: "the invoice lands on `PAID` when its balance reaches zero".

    Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_customer_standing
    """
    depot = make_depot(10, "Depot CE1")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="CE1 Bar", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    _order1, _invoice = _setup_overdue_standing_hold(cust, depot)

    order2 = quoted_order(
        cust["id"], depot["id"], [order_line("CUBE", "BAG", 1)],
        channel="WILL_CALL", event_date="2026-06-05",
        window_start="10:00", window_end="12:00",
    )
    resp = api.confirm_order(order2["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD)

    make_payment(cust["id"], 45000, method="ACH")
    assert get_customer(cust["id"])["standing"] == "GOOD"

    confirmed = confirm(order2["id"], cust["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        "payment moved the invoice OVERDUE -> PAID, lifting the hold"
    )


def test_confirm_unblocked_by_voiding_last_overdue_invoice(api):
    """PRD §3.8: "voiding the last `OVERDUE` invoice restores `GOOD`".
    PRD §3.8: "Separately, any `OVERDUE` invoice puts `standing` on `HOLD`,
    which blocks confirmation earlier in the gauntlet with `ERR_CREDIT_HOLD`
    (HTTP 402) (§3.5)."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_customer_standing
    """
    depot = make_depot(10, "Depot CE1b")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="CE1b Bar", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    order1, invoice = _setup_overdue_standing_hold(cust, depot)

    order2 = quoted_order(
        cust["id"], depot["id"], [order_line("CUBE", "BAG", 1)],
        channel="WILL_CALL", event_date="2026-06-05",
        window_start="10:00", window_end="12:00",
    )
    resp = api.confirm_order(order2["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD)

    # A different clerk voids the overdue invoice (segregation of duties).
    voided = validate_success(api.void_invoice(invoice["id"], CLERK_2))
    assert voided["status"] == "VOID"
    assert get_customer(cust["id"])["standing"] == "GOOD"

    order1_after = get_success_data(api.get_order(order1["id"], ADMIN))
    assert order1_after["billing_status"] == "UNBILLED"
    assert order1_after["invoice_id"] is None

    confirmed = confirm(order2["id"], cust["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED"


# --------------------- difficulty: state beats fiscal on confirm ---------------

def test_confirm_draft_order_reports_state_not_credit(api):
    """PRD §2.6: "Every request is evaluated against a fixed ladder of checks,
    and the first failing rung decides the response — later checks are never
    consulted once an earlier one has failed."
    PRD §3.5: "After the generic ladder of §2.6, the business gates evaluate in
    this pinned order, and the ordering matters because an early failure masks
    later ones."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
    """
    depot = make_depot(10, "Depot PP1")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="PP1 Prepaid", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="PREPAID", credit_limit_cents=0,
    )
    order = make_order(
        cust["id"], depot["id"], [order_line("CUBE", "BAG", 1)],
        channel="WILL_CALL", event_date="2026-05-05",
        window_start="10:00", window_end="12:00",
    )
    # The confirm would also fail the credit check (0 + 350 > 0 + 0), but the
    # DRAFT order is not QUOTED, and the state rung fires first.
    resp = api.confirm_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_quoted_order_over_limit_reports_credit(api):
    """PRD §3.8: "Confirmation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 402) when the forward-looking exposure plus the candidate order's
    `total_cents` exceeds the customer's `credit_limit_cents` plus the
    spendable `credit_balance_cents`; equality is admitted."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
    """
    depot = make_depot(10, "Depot PP1b")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="PP1b Prepaid", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="PREPAID", credit_limit_cents=0,
    )
    order = quoted_order(
        cust["id"], depot["id"], [order_line("CUBE", "BAG", 1)],
        channel="WILL_CALL", event_date="2026-05-05",
        window_start="10:00", window_end="12:00",
    )
    assert order["total_cents"] == 350
    # Isolated fiscal failure: state is QUOTED, so the credit gate is reached.
    resp = api.confirm_order(order["id"], agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
