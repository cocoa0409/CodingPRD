"""Core returns: provisional vs final penalty, boundaries, deposit waterfall."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_core_return_waterfall_invariant,
    setup_issued_quote, setup_delivered_order,
    make_quote_line, set_clock, TEST_USERS,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

EXCHANGE_PART = {
    "part_number": "PN-EXCH", "description": "Rotable valve", "rotable": True,
    "list_price_cents": 250_000, "core_value_cents": 500_000,
    "warranty_months": 24,
}
EXCHANGE_LINE = {"unit_price_cents": 250_000}


def _exchange_ctx(name):
    return setup_delivered_order(
        sale_type="EXCHANGE", customer_name=name,
        part_overrides=dict(EXCHANGE_PART),
        aog_overrides={"airport_code": "LAX"},
        line_overrides=dict(EXCHANGE_LINE),
    )


class TestCorePenaltyProvisionalVsFinal:
    def test_quote_discloses_provisional_worst_case(self, api):
        """PRD §3.4: "One more figure rides on every quote: `max_penalty_cents`,
        a provisional worst-case disclosure equal to the sum of each `EXCHANGE`
        line's core value multiplied by its quantity — the exposure the
        customer would face if every core were forfeited. This forward-looking
        number deliberately ignores the calendar".

        Design: Difficulty/dual_variant_calc/core_penalty_provisional_vs_final
        """
        ctx = setup_issued_quote(
            customer_name="Skyline Air",
            part_overrides=dict(EXCHANGE_PART),
            unit_overrides={"condition": "OVERHAULED",
                            "trace_doc_level": "DUAL_RELEASE"},
            aog_overrides={"aircraft_tail": "N100SL", "airport_code": "LAX",
                           "condition_acceptable": ["OVERHAULED", "NEW"]},
            line_overrides={"sale_type": "EXCHANGE",
                            "unit_price_cents": 250_000,
                            "condition_required": "OVERHAULED"},
            with_unit=True, source_search=True,
        )
        assert ctx["quote"]["max_penalty_cents"] == 500_000

    def test_final_penalty_at_receipt_differs_from_provisional(self, api):
        """PRD §3.6: "The accrual charges one-half of one percent of the core
        deposit for each of the first seven overdue days, plus one percent of
        the deposit for each additional day from day eight through day
        twenty-one. The final `penalty_cents` is the smaller of the full core
        deposit and the sum of a fixed 25,000-cent late fee — charged whenever
        the core is at least one day overdue — with the accrual rounded half-up
        to whole cents before the fee is added." And §3.5: "One CoreReturn
        springs up per `EXCHANGE` line with its due instant exactly 21 days
        after delivery."

        Delivered 2026-05-01 (due 2026-05-22), received 2026-06-01: 10 days
        overdue -> 25000 + (0.005*500000*7) + (0.01*500000*3) = 57500, which
        differs from the 500000 provisional disclosure on the same core data.

        Design: Difficulty/dual_variant_calc/core_penalty_provisional_vs_final
        """
        ctx = _exchange_ctx("Skyline Air")
        provisional = ctx["quote"]["max_penalty_cents"]
        core = ctx["core_return"]
        assert core["due_at"].startswith("2026-05-22T00:00:00")

        set_clock("2026-06-01T00:00:00Z")
        received = validate_success(api.receive_core_return(
            core["id"], {"core_serial_number": "SN-CORE-1"}, WAREHOUSE,
        ))
        assert received["days_overdue"] == 10
        assert received["penalty_cents"] == 57_500
        assert provisional == 500_000
        assert received["penalty_cents"] != provisional


class TestCoreReceivedExactlyAtDue:
    def test_received_exactly_at_due_is_on_time(self, api):
        """PRD §3.6: "`days_overdue` is zero when the core arrives on or before
        its due instant, otherwise the lateness in whole days rounded up." The
        25,000-cent late fee is "charged whenever the core is at least one day
        overdue", so arrival exactly at the due instant draws no fee.

        Design: Difficulty/boundary_precision_check/core_received_exactly_at_due_zero_penalty
        """
        ctx = _exchange_ctx("ExactAir")
        set_clock("2026-05-22T00:00:00Z")
        received = validate_success(api.receive_core_return(
            ctx["core_return"]["id"], {"core_serial_number": "SN-CORE-X"},
            WAREHOUSE,
        ))
        assert received["days_overdue"] == 0
        assert received["penalty_cents"] == 0
        assert received["status"] == "RECEIVED"

    def test_received_one_day_late_draws_late_fee(self, api):
        """PRD §3.6: "otherwise the lateness in whole days rounded up" and the
        penalty sums "a fixed 25,000-cent late fee — charged whenever the core
        is at least one day overdue" with "one-half of one percent of the core
        deposit for each of the first seven overdue days".

        One day late on a 500000 deposit: 25000 + round(0.005*500000*1) =
        27500.

        Design: Difficulty/boundary_precision_check/core_received_exactly_at_due_zero_penalty
        """
        ctx = _exchange_ctx("ExactAir")
        set_clock("2026-05-23T00:00:00Z")
        received = validate_success(api.receive_core_return(
            ctx["core_return"]["id"], {"core_serial_number": "SN-CORE-Y"},
            WAREHOUSE,
        ))
        assert received["days_overdue"] == 1
        assert received["penalty_cents"] == 27_500


class TestCoreDepositWaterfallConservation:
    def _received_with_waiver(self, api):
        ctx = _exchange_ctx("ConserveAir")
        set_clock("2026-06-01T00:00:00Z")
        validate_success(api.receive_core_return(
            ctx["core_return"]["id"], {"core_serial_number": "SN-CVC"},
            WAREHOUSE,
        ))
        validate_success(api.waive_core_penalty(
            ctx["core_return"]["id"], {"amount_cents": 10_000}, FINANCE,
        ))
        return ctx

    def test_waterfall_split_and_invariant(self, api):
        """PRD §3.6: "On `ACCEPTED_WITH_PENALTY`, `penalty_retained_cents` is
        the accrued penalty minus whatever has been waived, `refunded_cents`
        is the remainder of the deposit, `forfeited_cents` is zero" and "One
        invariant holds at settlement: the deposit equals refund plus penalty
        retained plus forfeiture."

        Penalty 57500 with 10000 waived -> retained 47500, refund 452500,
        forfeiture 0; 452500 + 47500 + 0 == 500000.

        Design: Difficulty/compensating_invariant/core_deposit_waterfall_conservation
        """
        ctx = self._received_with_waiver(api)
        settled = validate_success(api.inspect_core_return(
            ctx["core_return"]["id"], {"verdict": "ACCEPTED_WITH_PENALTY"},
            WAREHOUSE,
        ))
        assert settled["status"] == "SETTLED"
        assert settled["penalty_retained_cents"] == 47_500
        assert settled["refunded_cents"] == 452_500
        assert settled["forfeited_cents"] == 0
        assert_core_return_waterfall_invariant(settled)

    def test_balance_reconciles_against_ledger(self, api):
        """PRD §2.5: "A customer's `outstanding_balance_cents` ... always
        equals the sum of `amount_cents` over the debit entry types ... minus
        the sum over the credit entry types" and §3.6: "Whenever the refund is
        positive, a `CORE_REFUND_CREDIT` posts against the customer and the
        balance recomputes"; waiving "posts a `WAIVER_CREDIT` with balance
        recompute".

        Debits 269770 + 4800 + 500000 = 774570; credits 10000 + 452500 =
        462500; balance 312070.

        Design: Difficulty/compensating_invariant/core_deposit_waterfall_conservation
        """
        ctx = self._received_with_waiver(api)
        validate_success(api.inspect_core_return(
            ctx["core_return"]["id"], {"verdict": "ACCEPTED_WITH_PENALTY"},
            WAREHOUSE,
        ))
        cust = validate_success(api.get_customer(ctx["customer"]["id"], FINANCE))
        assert cust["outstanding_balance_cents"] == 312_070

        ledger, meta = validate_paginated(
            api.list_ledger_entries(ctx["customer"]["id"], FINANCE)
        )
        seen = {(e["entry_type"], e["amount_cents"]) for e in ledger}
        assert ("WAIVER_CREDIT", 10_000) in seen
        assert ("CORE_REFUND_CREDIT", 452_500) in seen


def test_waiver_capped_at_remaining_penalty(api):
    """PRD §3.6: "A `FinanceController` may soften a penalty while the return
    is `OVERDUE` or `RECEIVED` by waiving an `amount_cents` no greater than the
    penalty minus what has already been waived — an over-large waiver is
    refused with `ERR_WAIVER_EXCEEDS_PENALTY`. Waiving accumulates into
    `penalty_waived_cents` and posts a `WAIVER_CREDIT` with balance recompute".

    Design: Corner/errors/waiver_capped_at_remaining_penalty
    """
    ctx = _exchange_ctx("WaiveAir")
    set_clock("2026-06-01T00:00:00Z")
    received = validate_success(api.receive_core_return(
        ctx["core_return"]["id"], {"core_serial_number": "SN-WVC"}, WAREHOUSE,
    ))
    assert received["penalty_cents"] == 57_500

    over = api.waive_core_penalty(
        ctx["core_return"]["id"], {"amount_cents": 57_501}, FINANCE,
    )
    validate_error(over, "ERR_WAIVER_EXCEEDS_PENALTY", expected_status=402)

    exact = validate_success(api.waive_core_penalty(
        ctx["core_return"]["id"], {"amount_cents": 57_500}, FINANCE,
    ))
    assert exact["penalty_waived_cents"] == 57_500

    ledger, meta = validate_paginated(
        api.list_ledger_entries(ctx["customer"]["id"], FINANCE)
    )
    assert any(
        e["entry_type"] == "WAIVER_CREDIT" and e["amount_cents"] == 57_500
        for e in ledger
    )
