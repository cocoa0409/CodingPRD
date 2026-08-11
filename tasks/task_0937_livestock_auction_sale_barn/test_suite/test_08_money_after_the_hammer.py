"""Payments, dead-on-arrival credits, settlement release and adjustment."""

from test_helpers import (
    ApiErrorId,
    SETTLEMENT_CLERK,
    apply_payment,
    assert_money,
    assert_settlement_balances,
    list_charge_lines,
    read_buyer_invoice,
    read_buyer_registration,
    read_consignment,
    read_purchase,
    read_settlement,
    release_settlement,
    require_charge_line,
    setup_closed_day_with_settlement,
    validate_error,
    validate_success,
)


def test_payment_above_the_invoice_balance_is_refused_then_exact_payment_pays_it(api):
    """PRD §3.11: "Payments are applied by a `SettlementClerk` against a named
    `buyer_invoice_id` with an `amount`, and the amount may not exceed that invoice's
    `balance_due`; exceeding it is refused with `ERR_AMOUNT_EXCEEDS_BALANCE`."
    PRD §3.11: "A payment exactly equal to the outstanding balance takes an invoice
    from either `ISSUED` or `PARTIALLY_PAID` to `PAID`, drives `balance_due` to zero,
    transitions every purchase on that invoice to `PAID` — dropping them out of the
    buyer's exposure — and makes any settlement sitting at `HELD` with `hold_reason`
    `AWAITING_FUNDS` eligible for release once all of its covering invoices are paid."
    PRD §3.7: "`exposure` is the sum of those two figures less `payments_applied`,
    rounded half up to two decimal places, and `available_credit` is `effective_limit`
    less `exposure`, likewise rounded."

    Design: Corner/validations/corner_payment_above_invoice_balance_is_rejected
    """
    scn = setup_closed_day_with_settlement()
    assert_money(scn.invoice["total_due"], 12422.73, "the issued invoice:")

    response = api.apply_payment(
        scn.registration["id"],
        {"buyer_invoice_id": scn.invoice["id"], "amount": 20000.00},
        SETTLEMENT_CLERK,
    )
    validate_error(response, ApiErrorId.ERR_AMOUNT_EXCEEDS_BALANCE.value)
    assert_money(
        read_buyer_invoice(scn.invoice["id"])["amount_paid"],
        0.00,
        "a refused payment moves nothing:",
    )

    validate_success(
        api.apply_payment(
            scn.registration["id"],
            {"buyer_invoice_id": scn.invoice["id"], "amount": 12422.73},
            SETTLEMENT_CLERK,
        )
    )

    invoice = read_buyer_invoice(scn.invoice["id"])
    assert invoice["status"] == "PAID"
    assert_money(invoice["balance_due"], 0.00, "the balance is cleared:")
    assert read_purchase(scn.purchase["id"])["status"] == "PAID"

    registration = read_buyer_registration(scn.registration["id"])
    assert_money(registration["payments_applied"], 12422.73, "payments applied:")
    assert_money(
        registration["exposure"],
        -12422.73,
        "a paid purchase leaves the exposure while the payment stays:",
    )


def test_dead_on_arrival_credit_memo_cascades_through_purchase_invoice_and_lines(api):
    """PRD §3.11: "When a purchase is named, the head declared dead on arrival may not
    exceed the purchase's `head_count`; the purchase transitions `INVOICED → ADJUSTED`,
    its `doa_head` rises, its `doa_credit_amount` is computed, and a negative
    `DOA_CREDIT` charge line is appended on the buyer side."
    PRD §3.11: "The dead-on-arrival credit is a per-head value multiplied by the
    purchase's cumulative `doa_head`, rounded half up to two decimal places; the per-head
    value is the purchase's `extended_amount` divided by its `head_count` and rounded
    half up to two decimal places on a `PER_CWT` purchase, and simply the purchase's
    `unit_price` on a `PER_HEAD` purchase."
    PRD §3.10: "From there, `total_due` is `subtotal` plus `buyer_fee` less
    `credit_memo_total`, rounded half up to two decimal places, and `balance_due` is
    `total_due` less `amount_paid`, likewise rounded."
    PRD §2.11: "`DOA_CREDIT` is `BUYER`-side `BARN_REVENUE` and is the only line whose
    `amount` is negative; every other line is positive."

    Design: Corner/cross_cutting_complexity_layers/corner_doa_credit_memo_cascades_into_purchase_invoice_and_charge_lines
    """
    scn = setup_closed_day_with_settlement()

    # The supplied amount is exactly the computed dead-on-arrival credit
    # (12391.75 / 10 = 1239.18 per head, twice over), so the memo total is the same
    # figure whichever of the two the implementation records.
    validate_success(
        api.issue_credit_memo(
            scn.invoice["id"],
            {"amount": 2478.36, "purchase_id": scn.purchase["id"], "doa_head": 2},
            SETTLEMENT_CLERK,
        )
    )

    purchase = read_purchase(scn.purchase["id"])
    assert purchase["doa_head"] == 2
    assert_money(purchase["doa_credit_amount"], 2478.36, "1239.18 per head on two head:")
    assert purchase["status"] == "ADJUSTED"

    invoice = read_buyer_invoice(scn.invoice["id"])
    assert_money(invoice["credit_memo_total"], 2478.36, "credit memo total:")
    assert_money(invoice["subtotal"], 12391.75, "the subtotal is untouched by the memo:")
    assert_money(invoice["buyer_fee"], 30.98, "the bond fee is untouched by the memo:")
    assert_money(invoice["total_due"], 9944.37, "subtotal plus fee less the memo:")
    assert_money(invoice["balance_due"], 9944.37, "nothing has been paid yet:")

    lines = list_charge_lines(buyer_invoice_id=scn.invoice["id"])
    doa_line = require_charge_line(lines, "DOA_CREDIT")
    assert doa_line["side"] == "BUYER"
    assert_money(doa_line["amount"], -2478.36, "the only negative line:")

    apply_payment(scn.registration["id"], scn.invoice["id"], 1000.00)

    invoice = read_buyer_invoice(scn.invoice["id"])
    assert_money(invoice["balance_due"], 8944.37, "the balance after a partial payment:")
    assert invoice["status"] == "PARTIALLY_PAID"
    assert read_purchase(scn.purchase["id"])["status"] == "INVOICED", (
        "a partial payment returns an adjusted purchase to the billed state"
    )


def test_a_released_settlement_refuses_a_second_release_but_admits_an_adjustment(api):
    """PRD §2.6: "**G5 — the settlement is released.** A `Settlement` whose `status` is
    `RELEASED` accepts no further mutation, and an attempt is refused with
    `ERR_SETTLEMENT_RELEASED` (HTTP 409). The single exemption is `POST
    /sale-barn/settlements/{id}/adjust`, which posts a credit-memo style adjustment; a
    released settlement is never reversed, only adjusted."
    PRD §3.11: "Every release transitions the parent consignment `RECONCILED →
    SETTLED` and activates gate G5, after which the settlement accepts no mutation other
    than adjustment."
    PRD §3.11: "The settlement transitions `RELEASED → ADJUSTED`, `adjustment_total`
    rises by the adjustment amount, `net_amount` is recomputed and `balance_ok`
    re-derived."
    PRD §2.9 rung 6: "Numeric body fields satisfy their sign and range constraints —
    head counts at least 1, money amounts at least 0, `pencil_shrink_pct` at most 0.06,
    payment and adjustment amounts strictly greater than 0."
    PRD §3.10: "`net_amount` is `gross_amount`, less `commission_amount`, less
    `yardage_amount`, less `feed_amount`, less `statutory_amount`, less
    `brand_fee_amount`, less `indemnity_fee_amount`, less `advances_amount`, less
    `offset_applied`, plus `adjustment_total`, rounded half up to two decimal places."

    Design: Corner/validations/corner_second_release_of_a_released_settlement_is_rejected
    """
    scn = setup_closed_day_with_settlement()
    released = release_settlement(scn.settlement["id"])
    assert released["status"] == "RELEASED"
    assert_money(released["net_amount"], 11944.41, "net proceeds handed to the consignor:")

    response = api.release_settlement(scn.settlement["id"], SETTLEMENT_CLERK)
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_RELEASED.value)

    assert read_settlement(scn.settlement["id"])["status"] == "RELEASED"
    assert read_consignment(scn.consignment["id"])["status"] == "SETTLED"

    adjusted = validate_success(
        api.adjust_settlement(
            scn.settlement["id"],
            {"adjustment_amount": 100.00, "reason": "Scale correction after release"},
            SETTLEMENT_CLERK,
        )
    )
    assert adjusted["status"] == "ADJUSTED"
    assert_money(adjusted["adjustment_total"], 100.00, "the adjustment total:")
    assert_money(adjusted["net_amount"], 12044.41, "net recomputed with the adjustment:")
    assert adjusted["balance_ok"] is True
    assert_settlement_balances(read_settlement(scn.settlement["id"]))
