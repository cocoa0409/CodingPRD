"""Invoice payment: spend-ledger posting, aggregate cascades, overrun cap, OCC order."""

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_invoice,
    assert_spend_line,
    create_budget,
    create_invoice,
    get_success_data,
    pay_invoice,
    setup_budget_with_consumed,
    setup_matter_graph,
    validate_success,
    validate_error,
    validate_paginated,
    ANALYST,
    MANAGER,
)


class TestPaymentCascade:
    def test_pay_cascades_through_spendline_to_budget_posture(self, api):
        """PRD §3.5: "On success the system writes a spend line whose
        `amount_cents` equals the invoice amount, whose `posting_date` is the
        posting period's `start_date`, and whose `source_status` is `POSTED`."
        PRD §3.5: "The matter's `actual_spend_cents` grows by the invoice amount
        and its `accrual_outstanding_cents` is recomputed; the period's
        `total_actual_spend_cents` grows likewise and its `total_accrual_cents` is
        recomputed; every matching budget recomputes `consumed_cents` and
        re-derives its `posture`"

        Design: Difficulty/transitive_cascade/invoice_pay_cascades_through_spendline_to_budget_posture
        """
        graph = setup_matter_graph(
            dept_overrides={"budget_warning_pct": 0.80, "budget_critical_pct": 0.95}
        )
        fp_id = graph["fiscal_period"]["id"]
        budget = create_budget(
            fp_id, graph["practice_area"]["id"], 1000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        assert budget["posture"] == "OK"
        assert budget["consumed_cents"] == 0

        inv = create_invoice(
            graph["matter"]["id"], graph["firm"]["id"], fp_id, 950000
        )
        approve_invoice(inv["id"])
        paid = pay_invoice(inv["id"])
        assert paid["payment_status"] == "PAID"  # depth 1: invoice mutation

        matter_after = get_success_data(api_client.get_matter(graph["matter"]["id"], ANALYST))
        assert matter_after["actual_spend_cents"] == 950000  # depth 2: spend-line insert

        period_after = get_success_data(api_client.get_fiscal_period(fp_id, ANALYST))
        assert period_after["total_actual_spend_cents"] == 950000

        budget_after = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        assert budget_after["consumed_cents"] == 950000  # depth 3: budget recompute
        # ratio 0.95 >= budget_critical_pct 0.95 — inclusive boundary
        assert budget_after["posture"] == "CRITICAL"

    def test_pay_writes_posted_spend_line_row(self, api):
        """PRD §3.5: "On success the system writes a spend line whose
        `amount_cents` equals the invoice amount, whose `posting_date` is the
        posting period's `start_date`, and whose `source_status` is `POSTED`."
        PRD §2.4: "Spend lines are the single exception. As immutable entries in
        an append-only ledger, a spend line carries only `id` and `created_at`;
        both `updated_at` and `version` are absent, because a posted ledger row is
        never modified."

        Design: Difficulty/transitive_cascade/invoice_pay_cascades_through_spendline_to_budget_posture
        """
        graph = setup_budget_with_consumed(consumed_cents=950000, allocated_cents=1000000)
        inv = graph["invoice"]
        lines, meta = validate_paginated(
            api_client.list_spend_lines(ANALYST, params={"matter_id": graph["matter"]["id"]})
        )
        assert meta["total_count"] == 1
        line = lines[0]
        assert_spend_line(line)
        assert line["amount_cents"] == 950000
        assert line["posting_date"] == graph["fiscal_period"]["start_date"]
        assert line["source_status"] == "POSTED"
        assert line["invoice_id"] == inv["id"]
        assert line["firm_id"] == graph["firm"]["id"]
        assert line["fiscal_period_id"] == graph["fiscal_period"]["id"]


class TestPayConservation:
    def test_sequential_pays_keep_budget_and_period_in_lockstep(self, api):
        """PRD §2.8: "A matter's `actual_spend_cents` sums posted ledger amounts
        for that matter; a period's `total_actual_spend_cents` sums posted lines
        whose `posting_date` falls within the period's inclusive date range; a
        budget's `consumed_cents` sums posted lines matching its grain."

        Design: Difficulty/compensating_invariant/invoice_pay_conserves_budget_consumed_sum_equality
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        budget = create_budget(
            fp_id, graph["practice_area"]["id"], 10000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        inv1 = create_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 2000000)
        approve_invoice(inv1["id"])
        inv2 = create_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 3000000)
        approve_invoice(inv2["id"])

        pay_invoice(inv1["id"])
        b_mid = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        fp_mid = get_success_data(api_client.get_fiscal_period(fp_id, ANALYST))
        assert b_mid["consumed_cents"] == 2000000
        assert fp_mid["total_actual_spend_cents"] == 2000000

        pay_invoice(inv2["id"])
        b_final = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        fp_final = get_success_data(api_client.get_fiscal_period(fp_id, ANALYST))
        assert b_final["consumed_cents"] == 5000000
        assert fp_final["total_actual_spend_cents"] == 5000000

    def test_matter_budget_period_spend_stay_equal_after_each_pay(self, api):
        """PRD §2.8: "A matter's `actual_spend_cents` sums posted ledger amounts
        for that matter; a period's `total_actual_spend_cents` sums posted lines
        whose `posting_date` falls within the period's inclusive date range; a
        budget's `consumed_cents` sums posted lines matching its grain."

        Design: Difficulty/compensating_invariant/invoice_pay_conserves_budget_consumed_sum_equality
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        budget = create_budget(
            fp_id, graph["practice_area"]["id"], 10000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        expected = 0
        for amount in (1500000, 2500000):
            inv = create_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, amount)
            approve_invoice(inv["id"])
            pay_invoice(inv["id"])
            expected += amount
            m = get_success_data(api_client.get_matter(graph["matter"]["id"], ANALYST))
            b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
            fp = get_success_data(api_client.get_fiscal_period(fp_id, ANALYST))
            assert m["actual_spend_cents"] == expected
            assert b["consumed_cents"] == expected
            assert fp["total_actual_spend_cents"] == expected


class TestPaymentValidationOrder:
    def test_state_check_beats_fiscal_overrun_on_terminal_invoice(self, api):
        """PRD §2.12: "Every request is checked against a fixed pipeline, and the
        order is part of the contract:"
        PRD §2.12: "4. State eligibility — for the action endpoints (activate,
        hold, resume, close, reopen, archive, soft-close, hard-close, approve,
        pay, reject, release, publish), a target resource that is not in a state
        from which the requested transition is defined yields `ERR_INVALID_STATE`
        (HTTP 409)." — state (step 4) precedes business rules (step 5).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_conflict_on_invoice_pay
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        # 1200000 would push consumption past 110% of this allocation (1100000).
        create_budget(
            fp_id, graph["practice_area"]["id"], 1000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        inv = create_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 1200000)
        validate_success(api_client.reject_invoice(inv["id"], ANALYST), 200)

        res = api_client.pay_invoice(inv["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_overrun_rejected_when_state_preconditions_clean(self, api):
        """PRD §3.5: "Before anything posts, the fiscal cap runs: if paying would
        push any matching budget's `consumed_cents` past one hundred and ten
        percent of its `allocated_cents` — the fixed ten-percent overrun allowance
        of §2.7 — payment is refused with `ERR_BUDGET_OVERRUN_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_conflict_on_invoice_pay
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        create_budget(
            fp_id, graph["practice_area"]["id"], 1000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        inv = create_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 1200000)
        approve_invoice(inv["id"])  # APPROVED, period OPEN — only the cap can fail
        res = api_client.pay_invoice(inv["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_BUDGET_OVERRUN_EXCEEDED)


def test_overrun_cap_inclusive_at_exactly_110_percent(api):
    """PRD §3.5: "Before anything posts, the fiscal cap runs: if paying would push
    any matching budget's `consumed_cents` past one hundred and ten percent of its
    `allocated_cents` — the fixed ten-percent overrun allowance of §2.7 — payment
    is refused with `ERR_BUDGET_OVERRUN_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/budget_overrun_exceeded_at_110_percent_cap
    """
    graph = setup_matter_graph()
    fp_id = graph["fiscal_period"]["id"]
    create_budget(
        fp_id, graph["practice_area"]["id"], 1000000,
        matter_type_id=graph["matter_type"]["id"],
    )
    # Exactly 110% of allocation — "past" the cap is not reached, payment allowed.
    inv1 = create_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 1100000)
    approve_invoice(inv1["id"])
    paid = pay_invoice(inv1["id"])
    assert paid["payment_status"] == "PAID"

    # One more cent pushes consumption to 1100001 > 1100000 — refused.
    inv2 = create_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 1)
    approve_invoice(inv2["id"])
    res = api_client.pay_invoice(inv2["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_BUDGET_OVERRUN_EXCEEDED)


def test_derived_fields_reconcile_after_payment(api):
    """PRD §2.8: "Aggregates are derived from the ledger, never independently
    stored truths. A matter's `actual_spend_cents` sums posted ledger amounts for
    that matter; a period's `total_actual_spend_cents` sums posted lines whose
    `posting_date` falls within the period's inclusive date range; a budget's
    `consumed_cents` sums posted lines matching its grain."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_after_payment
    """
    graph = setup_budget_with_consumed(consumed_cents=4000000, allocated_cents=10000000)
    m = get_success_data(api_client.get_matter(graph["matter"]["id"], ANALYST))
    fp = get_success_data(api_client.get_fiscal_period(graph["fiscal_period"]["id"], ANALYST))
    b = get_success_data(api_client.get_budget(graph["budget"]["id"], ANALYST))
    assert m["actual_spend_cents"] == 4000000
    assert fp["total_actual_spend_cents"] == 4000000
    assert b["consumed_cents"] == 4000000


def test_payment_immediately_visible_on_matter_read(api):
    """PRD §1: "Writes are gated by the state of the fiscal calendar, invoice
    payment cascades update matter, period, and budget aggregates immediately,
    budget posture is a derived signal driven by department-set thresholds, and a
    fixed validation order determines which error a premature or malformed request
    receives."

    Design: Corner/consistency_model/immediate_visibility_after_payment
    """
    graph = setup_matter_graph()
    inv = create_invoice(
        graph["matter"]["id"], graph["firm"]["id"], graph["fiscal_period"]["id"], 700000
    )
    approve_invoice(inv["id"])
    pay_invoice(inv["id"])
    m = get_success_data(api_client.get_matter(graph["matter"]["id"], ANALYST))
    assert m["actual_spend_cents"] == 700000
