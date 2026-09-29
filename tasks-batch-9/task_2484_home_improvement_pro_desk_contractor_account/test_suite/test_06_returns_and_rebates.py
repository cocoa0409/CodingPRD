"""Return valuation variants and the rebate ledger's behaviour under a credited return."""

from typing import Any, Dict

from test_helpers import (
    CREDIT_MANAGER,
    PRO_DESK_ASSOCIATE,
    SKU_SHINGLE_BUNDLE,
    api_client,
    approve_return,
    assert_refund_legs_sum,
    create_credit_line,
    credit_return,
    invoice_order,
    list_rebate_accruals,
    read_credit_line,
    read_pro_account,
    read_pro_order,
    request_return,
    set_clock,
    setup_accepted_quote,
    setup_account_at_tier,
    setup_fulfilled_will_call_order,
    setup_store_with_stock,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Scenario builder (inlined: every test starts from an empty database)         #
# --------------------------------------------------------------------------- #


def _fulfilled_quote_bound_order() -> Dict[str, Any]:
    """A GOLD account's 8-unit quote-bound will-call order, picked up on 2026-08-01.

    The quote is negotiated at 1500 per unit against a 1999 list price, and its
    requested 45-day term is capped by the GOLD rung.
    """
    store, stocks = setup_store_with_stock([(SKU_SHINGLE_BUNDLE, 600)])
    account = setup_account_at_tier(store["id"], "GOLD")
    credit_line = create_credit_line(
        account["id"], limit_cents=100_000_000, terms_days=30
    )
    quote, _quote_lines = setup_accepted_quote(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 8)],
        negotiated_unit_price_cents=1_500,
        term_days=45,
    )
    bundle = setup_fulfilled_will_call_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 8)],
        stage_start="2026-08-01T08:00:00Z",
        stage_hours=6,
        job_quote_id=quote["id"],
        payment_method="CREDIT_LINE",
        job_name="MAPLE-ST-REROOF",
    )
    bundle.update(
        {
            "store": store,
            "stock": stocks[SKU_SHINGLE_BUNDLE],
            "account": account,
            "credit_line": credit_line,
            "quote": quote,
        }
    )
    return bundle


# =========================================================================== #
# Return valuation: QUOTED_TERM against CURRENT_LIST                          #
# =========================================================================== #


class TestReturnValuationVariants:
    def test_return_approved_inside_the_quote_term_refunds_the_negotiated_price(self):
        """PRD §3.9: "The mode is `QUOTED_TERM` when the order names a `job_quote_id` and the approval instant is at or before that quote's `term_end`; otherwise it is `CURRENT_LIST`."
        PRD §3.9: "Under `QUOTED_TERM`, each returned line is refunded at the `effective_unit_price_cents` recorded on its order line, which is exactly what the contractor paid, so a return inside a live quote term is a clean reversal of the original sale at the negotiated price."
        PRD §3.9: "The request's `restocking_fee_pct` is the greater of the two, so a quoted-material return sent back on day 3 still carries 15 percent, and a tier-priced return sent back on day 60 carries 10 percent, while a quoted-material return on day 60 carries 15 percent rather than the sum of the two."
        PRD §3.9: "`tax_refund_cents` is 0 when the original order's `tax_exempt_applied` was true, and otherwise that net goods figure multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent — note that the refunded tax is computed on the goods net of the restocking fee, not on the gross."

        Design: Difficulty/dual_variant_calc/return_valuation_quoted_term_vs_current_list_divergence
        """
        scenario = _fulfilled_quote_bound_order()
        order_line_id = scenario["order_lines"][0]["id"]

        set_clock("2026-08-11T00:00:00Z")
        request = request_return(
            scenario["order"]["id"],
            scenario["account"]["id"],
            [(order_line_id, 4)],
            reason_code="OVER_ORDERED",
        )
        approved = validate_success(
            api_client.approve_return_request(request["id"], PRO_DESK_ASSOCIATE),
            expected_status=200,
        )

        assert approved["valuation_mode"] == "QUOTED_TERM"
        assert approved["gross_refund_cents"] == 6000
        assert approved["restocking_fee_pct"] == 0.15
        assert approved["restocking_fee_cents"] == 900
        assert approved["tax_refund_cents"] == 421
        assert approved["refund_total_cents"] == 5521
        assert_refund_legs_sum(approved)

    def test_return_approved_after_term_end_revalues_at_current_list_and_diverges(self):
        """PRD §3.9: "The mode is `QUOTED_TERM` when the order names a `job_quote_id` and the approval instant is at or before that quote's `term_end`; otherwise it is `CURRENT_LIST`."
        PRD §3.9: "Under `CURRENT_LIST`, each returned line is instead revalued from scratch at today's price: the fulfillment store's current `list_unit_price_cents` for that line's `sku`, reduced by the account's currently persisted `tier_discount_pct`, rounded half up to a whole cent."
        PRD §3.9: "The two variants therefore diverge whenever list prices have moved or the account's tier has moved since the order was priced, and the divergence propagates: identical return quantities yield a different gross refund, a different restocking fee and a different tax refund."
        PRD §3.9: "`restocking_fee_cents` is then that percentage applied to `gross_refund_cents` and rounded half up to a whole cent — **one single rounding, on the summed gross, never per line**, which is the deliberate opposite of the per-unit rounding used when order lines were priced."

        Design: Difficulty/dual_variant_calc/return_valuation_quoted_term_vs_current_list_divergence
        """
        scenario = _fulfilled_quote_bound_order()
        order_id = scenario["order"]["id"]
        account_id = scenario["account"]["id"]
        order_line_id = scenario["order_lines"][0]["id"]

        set_clock("2026-08-11T00:00:00Z")
        inside_term = request_return(order_id, account_id, [(order_line_id, 4)])
        inside_term_approved = approve_return(inside_term["id"])
        credit_return(inside_term["id"])

        set_clock("2026-09-15T00:00:00Z")
        after_term = request_return(order_id, account_id, [(order_line_id, 4)])
        after_term_approved = validate_success(
            api_client.approve_return_request(after_term["id"], PRO_DESK_ASSOCIATE),
            expected_status=200,
        )

        assert after_term_approved["valuation_mode"] == "CURRENT_LIST"
        assert after_term_approved["gross_refund_cents"] == 7596
        assert after_term_approved["restocking_fee_cents"] == 1139
        assert after_term_approved["tax_refund_cents"] == 533
        assert after_term_approved["refund_total_cents"] == 6990
        assert_refund_legs_sum(after_term_approved)

        assert inside_term_approved["refund_total_cents"] == 5521
        assert (
            after_term_approved["refund_total_cents"]
            - inside_term_approved["refund_total_cents"]
            == 1469
        )


# =========================================================================== #
# The rebate ledger against net invoiced volume                               #
# =========================================================================== #


class TestRebateConservationAcrossACreditedReturn:
    def test_credited_return_claws_back_the_rebate_at_the_persisted_tier_rate(self):
        """PRD §3.9: "The delta added to `accrued_cents` is the order's `subtotal_cents` — the post-discount goods figure, not the total, so freight, the lift-gate fee and tax earn no rebate — multiplied by the rebate rate of the tier persisted on the account at the triggering instant, rounded half up to a whole cent."
        PRD §3.9: "The clawback delta is the request's `gross_refund_cents` — the pre-fee, pre-tax figure — multiplied by the rebate rate of the tier persisted at the triggering instant, rounded half up to a whole cent, and added to `clawed_back_cents` on the account's **newest** accrual whose `payout_status` is `ACCRUING` or `PAYABLE`."
        PRD §3.9: "After every booking, `payable_cents` is set to `accrued_cents` less `clawed_back_cents`, floored at zero, and the account's `rebate_accrued_cents` is recomputed as the sum of `payable_cents` across the account's accruals whose `payout_status` is `ACCRUING` or `PAYABLE`."

        Design: Difficulty/compensating_invariant/return_credit_conserves_rebate_against_net_volume
        """
        scenario = _fulfilled_quote_bound_order()
        order_id = scenario["order"]["id"]
        account_id = scenario["account"]["id"]
        invoice_order(order_id)

        accruals = list_rebate_accruals(account_id, payout_status="ACCRUING")
        assert len(accruals) == 1
        accrual_id = accruals[0]["id"]
        assert accruals[0]["accrued_cents"] == 120

        set_clock("2026-08-11T00:00:00Z")
        request = request_return(
            order_id, account_id, [(scenario["order_lines"][0]["id"], 4)]
        )
        approved = approve_return(request["id"])
        assert approved["gross_refund_cents"] == 6000
        credit_return(request["id"])

        accrual = validate_success(
            api_client.get_rebate_accrual(accrual_id, CREDIT_MANAGER),
            expected_status=200,
        )
        assert accrual["accrued_cents"] == 120
        assert accrual["clawed_back_cents"] == 60
        assert accrual["payable_cents"] == 60

    def test_credited_return_nets_order_volume_account_tier_and_credit_exposure(self):
        """PRD §3.9: "Hop one recomputes the order's `credited_refund_cents`, `credited_gross_refund_cents` and `net_volume_cents`."
        PRD §3.9: "Hop two recomputes the credit line's `exposure_cents` and `available_cents` from those order-level changes — this is the compensating leg of the exposure invariant, and it is what gives the contractor headroom back for returned material."
        PRD §3.2: "`trailing_volume_cents` is then the account's `baseline_volume_cents` plus the sum of `net_volume_cents` across the account's in-window orders, where an order's `net_volume_cents` is its `subtotal_cents` less its `credited_gross_refund_cents` — returns net out at their gross refund value, before any restocking fee."
        PRD §3.9: "The credit stamps `credited_at` with the current clock, adds each returned `qty_units` to its order line's `returned_units`, increments the request's `version`, and then fires the deepest cascade in the system, all four hops of which must be applied."

        Design: Difficulty/compensating_invariant/return_credit_conserves_rebate_against_net_volume
        """
        scenario = _fulfilled_quote_bound_order()
        order_id = scenario["order"]["id"]
        account_id = scenario["account"]["id"]
        order_line_id = scenario["order_lines"][0]["id"]

        invoiced = invoice_order(order_id)
        assert invoiced["subtotal_cents"] == 12000
        assert invoiced["total_cents"] == 12990

        set_clock("2026-08-11T00:00:00Z")
        request = request_return(order_id, account_id, [(order_line_id, 4)])
        approved = approve_return(request["id"])
        assert approved["refund_total_cents"] == 5521
        credited = credit_return(request["id"])
        assert credited["status"] == "CREDITED"

        order = read_pro_order(order_id, account_id)
        assert order["credited_gross_refund_cents"] == 6000
        assert order["credited_refund_cents"] == 5521
        assert order["net_volume_cents"] == 6000

        account = read_pro_account(account_id)
        assert account["trailing_volume_cents"] == 6006000
        assert account["tier_code"] == "GOLD"

        credit_line = read_credit_line(scenario["credit_line"]["id"])
        assert credit_line["exposure_cents"] == 7469

        order_line = validate_success(
            api_client.get_order_line(order_line_id, CREDIT_MANAGER),
            expected_status=200,
        )
        assert order_line["returned_units"] == 4

    def test_clawed_back_accrual_pays_out_only_its_remaining_payable(self):
        """PRD §3.9: "A `CreditManager` **closes** an accrual, which stamps `closed_at` with the current clock, increments the accrual's `version`, and branches on the money: `payout_status` goes from `ACCRUING` to `PAYABLE` when `payable_cents` is strictly positive, and from `ACCRUING` to `VOIDED` when `payable_cents` is exactly zero, which happens when clawbacks have consumed the whole accrual."
        PRD §3.9: "Pay-out then moves the accrual from `PAYABLE` to `PAID`, carrying a `payout_reference` recorded as such, setting `paid_amount_cents` to the accrual's `payable_cents`, recomputing the account's `rebate_accrued_cents` — a `PAID` accrual also leaves the base — and incrementing the accrual's `version`."

        Design: Difficulty/compensating_invariant/return_credit_conserves_rebate_against_net_volume
        """
        scenario = _fulfilled_quote_bound_order()
        order_id = scenario["order"]["id"]
        account_id = scenario["account"]["id"]
        invoice_order(order_id)

        accrual_id = list_rebate_accruals(account_id, payout_status="ACCRUING")[0]["id"]

        set_clock("2026-08-11T00:00:00Z")
        request = request_return(
            order_id, account_id, [(scenario["order_lines"][0]["id"], 4)]
        )
        approve_return(request["id"])
        credit_return(request["id"])

        closed = validate_success(
            api_client.close_rebate_accrual(accrual_id, CREDIT_MANAGER),
            expected_status=200,
        )
        assert closed["payout_status"] == "PAYABLE"
        assert closed["payable_cents"] == 60

        paid = validate_success(
            api_client.pay_out_rebate_accrual(
                accrual_id, "ACH-2026-08-0001", CREDIT_MANAGER
            ),
            expected_status=200,
        )
        assert paid["payout_status"] == "PAID"
        assert paid["paid_amount_cents"] == 60

        account = read_pro_account(account_id)
        assert account["rebate_accrued_cents"] == 0
