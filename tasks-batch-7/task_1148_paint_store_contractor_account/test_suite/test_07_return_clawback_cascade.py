"""Return cascade: refund recompute, payment-state flip, loyalty clawback,
and job-spent reconciliation (PRD §3.7), plus the compensating invariants of
the loyalty ledger and rebate chronological sweep."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_rebate_statement_payload,
    get_first_order_line,
    place_and_pay_order,
    set_logical_clock,
    setup_account_job_product,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


def _setup_paid_four_unit_order(api, company="Claw Co", jurisdiction_code="UT-OPEN",
                                jurisdiction_name="Utah Open", sku="P-RET"):
    """STANDARD account; paid order 4 units at 20000 list (subtotal 80000,
    tax 6600, total 86600); EARN posted 800 points at pay."""
    account, _, job, product = setup_account_job_product(
        company_name=company, credit_limit_cents=100_000_000,
        jurisdiction_code=jurisdiction_code, jurisdiction_name=jurisdiction_name,
        job_name="Barn", sku=sku, product_name="Pail", list_price_cents=20_000)
    order = place_and_pay_order(
        account["id"], job["id"],
        [{"product_id": product["id"], "quantity": 4}], headers=ASSOCIATE)
    line = get_first_order_line(order["id"])
    return account, job, order, line


def _loyalty_entries(api, account_id):
    resp = api.list_loyalty_transactions(
        ASSOCIATE, params={"contractor_account_id": account_id})
    data = validate_success(resp, expected_status=200)
    assert isinstance(data, list)
    return data


def test_return_flips_payment_and_recomputes_refund(api):
    """PRD §3.7: "The refund event then drives the order's payment dimension:
    while cumulative `refunded_cents` stays below `total_cents`, a `PAID`
    order becomes `PARTIALLY_REFUNDED`; when `refunded_cents` reaches
    `total_cents` exactly, the order becomes `REFUNDED` — whether it arrived
    there from `PAID` or from `PARTIALLY_REFUNDED`." PRD §3.7: "The line's
    `returned_quantity`, zero at order creation, grows by the returned amount,
    and the order's `refunded_cents` is recomputed as the sum of
    `total_credit_cents` over all its return records."

    Returning 1 of 4 units at unit price 20000 credits 20000 merchandise plus
    1650 tax: refunded_cents 21650 and payment PARTIALLY_REFUNDED.

    Design: Difficulty/transitive_cascade/return_refund_loyalty_clawback_chain
    """
    account, job, order, line = _setup_paid_four_unit_order(api)
    resp = api.return_order_line(line["id"], {"quantity": 1}, ASSOCIATE)
    record = validate_success(resp, expected_status=201)
    assert record["quantity"] == 1
    line_after = validate_success(api.get_order_line(line["id"], ASSOCIATE))
    assert line_after["returned_quantity"] == 1, (
        f"the line's returned_quantity grows by the returned amount, "
        f"got {line_after['returned_quantity']}")
    order_after = validate_success(api.get_order(order["id"], ASSOCIATE))
    assert order_after["refunded_cents"] == 21_650, (
        f"20000 merchandise + 1650 tax = 21650, got {order_after['refunded_cents']}")
    assert order_after["payment_status"] == "PARTIALLY_REFUNDED", (
        f"21650 < 86600 total keeps the order PARTIALLY_REFUNDED, "
        f"got {order_after['payment_status']}")


def test_return_posts_clawback_and_recomputes_balances(api):
    """PRD §3.7: "Clawback mirrors it at return time: a `CLAWBACK` entry posts
    a negative `points_delta` whose magnitude is the return record's
    `refund_merchandise_cents` divided by 100, truncated down, times the same
    snapshot multiplier." PRD §3.7: "Either path fires the same downstream
    cascade: a loyalty clawback entry is posted (below), the account's
    `loyalty_points_balance` and `ytd_net_volume_cents` are recomputed, the
    job's `spent_cents` is recomputed, any referenced spec lines have their
    `ordered_qty` and `delivered_qty` (and their sheets' pull-through
    percentages) recomputed, and the order, the order line, the contractor
    account, and the job account each take a `version` increment."

    The 800-point EARN minus a 200-point CLAWBACK leaves 600; the job's spend
    drops from 86600 to 64950.

    Design: Difficulty/transitive_cascade/return_refund_loyalty_clawback_chain
    """
    account, job, order, line = _setup_paid_four_unit_order(api)
    validate_success(api.return_order_line(line["id"], {"quantity": 1}, ASSOCIATE),
                     expected_status=201)
    account_after = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert account_after["loyalty_points_balance"] == 600, (
        f"800 earned - floor(20000/100)*1 clawed back = 600, "
        f"got {account_after['loyalty_points_balance']}")
    clawbacks = [t for t in _loyalty_entries(api, account["id"])
                 if t["type"] == "CLAWBACK"]
    assert len(clawbacks) == 1, "exactly one CLAWBACK entry must be posted"
    assert clawbacks[0]["points_delta"] == -200, (
        f"clawback magnitude is floor(20000/100)*1 = 200, "
        f"got {clawbacks[0]['points_delta']}")
    job_after = validate_success(api.get_job_account(job["id"], ASSOCIATE))
    assert job_after["spent_cents"] == 64_950, (
        f"job spend recomputes to 86600 - 21650 = 64950, "
        f"got {job_after['spent_cents']}")


def test_full_return_restores_prepayment_loyalty_balance(api):
    """PRD §3.7: "Because earn and clawback share the merchandise basis and
    the multiplier, a single-line order that is paid and then fully returned
    claws back exactly what it earned, restoring the account's pre-payment
    balance; in general, though, `loyalty_points_balance` — always the sum of
    `points_delta` over the account's ledger — may go negative, and a negative
    balance blocks redemption."

    Design: Difficulty/compensating_invariant/loyalty_earn_clawback_full_reversal
    """
    account, job, order, line = _setup_paid_four_unit_order(
        api, company="Loy Co", jurisdiction_code="ID-OPEN",
        jurisdiction_name="Idaho Open", sku="P-LOY")
    validate_success(api.return_order_line(line["id"], {"quantity": 4}, ASSOCIATE),
                     expected_status=201)
    account_after = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert account_after["loyalty_points_balance"] == 0, (
        f"EARN +800 then CLAWBACK -800 cancel exactly, "
        f"got {account_after['loyalty_points_balance']}")
    entries = _loyalty_entries(api, account["id"])
    ledger_sum = sum(t["points_delta"] for t in entries)
    assert ledger_sum == 0, (
        f"the balance is always the ledger sum; sum must be 0, got {ledger_sum}")
    assert ledger_sum == account_after["loyalty_points_balance"], (
        "ledger sum and reported balance must agree")


def test_full_return_marks_order_refunded_at_total(api):
    """PRD §3.7: "The refund event then drives the order's payment dimension:
    while cumulative `refunded_cents` stays below `total_cents`, a `PAID`
    order becomes `PARTIALLY_REFUNDED`; when `refunded_cents` reaches
    `total_cents` exactly, the order becomes `REFUNDED` — whether it arrived
    there from `PAID` or from `PARTIALLY_REFUNDED`."

    Returning all 4 units drives refunded_cents to the full 86600 total, and
    the order lands in terminal REFUNDED.

    Design: Difficulty/compensating_invariant/loyalty_earn_clawback_full_reversal
    """
    account, job, order, line = _setup_paid_four_unit_order(
        api, company="Loy Co", jurisdiction_code="ID-OPEN",
        jurisdiction_name="Idaho Open", sku="P-LOY")
    validate_success(api.return_order_line(line["id"], {"quantity": 4}, ASSOCIATE),
                     expected_status=201)
    order_after = validate_success(api.get_order(order["id"], ASSOCIATE))
    assert order_after["payment_status"] == "REFUNDED", (
        f"refunded == total must land the order in REFUNDED, "
        f"got {order_after['payment_status']}")
    assert order_after["refunded_cents"] == 86_600 == order_after["total_cents"]


def _setup_rewound_statement(api):
    """One 6,000,000-subtotal order paid Apr 10, fully returned Apr 20, both
    inside period [2026-04-01, 2026-07-01); statement generated after close."""
    set_logical_clock("2026-04-10T00:00:00Z")
    account, _, job, product = setup_account_job_product(
        company_name="Rew Co", credit_limit_cents=100_000_000,
        jurisdiction_code="MT-OPEN", jurisdiction_name="Montana Open",
        job_name="Mill", sku="P-REW", product_name="Drum",
        list_price_cents=6_000_000)
    order = place_and_pay_order(
        account["id"], job["id"],
        [{"product_id": product["id"], "quantity": 1}], headers=ASSOCIATE)
    line = get_first_order_line(order["id"])
    set_logical_clock("2026-04-20T00:00:00Z")
    validate_success(api.return_order_line(line["id"], {"quantity": 1}, ASSOCIATE),
                     expected_status=201)
    set_logical_clock("2026-07-01T00:00:00Z")
    resp = api.create_rebate_statement(
        create_rebate_statement_payload(account["id"],
                                        "2026-04-01T00:00:00Z",
                                        "2026-07-01T00:00:00Z"),
        ADMIN)
    stmt = validate_success(resp, expected_status=201)
    return account, stmt


def test_rebate_full_rewind_restores_zero_final(api):
    """PRD §3.9: "The marginal straddle is symmetric — a payment followed by a
    full in-period refund restores both accumulators exactly — so for
    identical order data the final differs from the provisional only through
    the provisional's forward-looking projection and proration whenever volume
    crosses a band boundary mid-period." PRD §3.9: "Each refund of amount *f*
    peels the bands top-down, unwinding the highest-rate band first ... the
    rebate loses the chunk times the rate, and the volume loses the chunk."

    The +6,000,000 payment accrues 120,000 at 2%; the full in-period refund
    peels exactly 120,000 back off, leaving final_amount_cents 0.

    Design: Difficulty/compensating_invariant/rebate_full_rewind_restores_zero
    """
    account, stmt = _setup_rewound_statement(api)
    resp = api.finalize_rebate_statement(stmt["id"], ADMIN)
    finalized = validate_success(resp, expected_status=200)
    assert finalized["final_amount_cents"] == 0, (
        f"payment then full in-period refund restores R to zero, "
        f"got {finalized['final_amount_cents']}")
    assert finalized["period_net_cents"] == 0, (
        f"merchandise basis nets to zero, got {finalized['period_net_cents']}")
    assert finalized["payable_cents"] == 0, (
        f"payable is floored at zero, got {finalized['payable_cents']}")


def test_rebate_full_rewind_zero_provisional(api):
    """PRD §3.9: "The net volume so far is the merchandise basis over the
    account's paid-set orders (`payment_status` `PAID`, `PARTIALLY_REFUNDED`,
    or `REFUNDED`) whose `paid_at` falls inside the elapsed portion of the
    period, minus the refund merchandise on those orders' return records."

    Generated after the payment was fully refunded, the statement's net-so-far
    is zero and the provisional estimate is 0.

    Design: Difficulty/compensating_invariant/rebate_full_rewind_restores_zero
    """
    account, stmt = _setup_rewound_statement(api)
    assert stmt["provisional_amount_cents"] == 0, (
        f"net_so_far is 0 at generation, so the provisional is 0, "
        f"got {stmt['provisional_amount_cents']}")
