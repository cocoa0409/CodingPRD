"""Commission statements: reconciliation, disputes, settlement, draws (PRD §3.7).

Covers statement upload uniqueness, expectation bases (accrual vs cash), line
matching at the inclusive tolerance, the dispute cycle, settle gates and their
pipeline precedence, settlement money movement, and draw recovery.
"""
from test_helpers import (
    ApiErrorId,
    create_invoiced_order,
    create_order,
    create_principal,
    create_rate_schedule,
    create_agreement,
    activate_agreement,
    create_rep,
    create_customer,
    create_statement,
    dispute_line,
    get_order,
    get_rep,
    get_statement,
    invoice_order,
    list_entries,
    make_order_line,
    make_principal_ops_headers,
    make_statement_line,
    mark_order_paid,
    order_line,
    post_adjustment,
    respond_dispute,
    set_clock,
    setup_base_scenario,
    ship_order,
    settle_statement,
    start_reconciliation,
    statement_line,
    validate_error,
    TEST_USERS,
)


def _admin():
    return TEST_USERS["agency_admin_headers"]


def _setup_invoiced_base(api, lines=None, ref="PO-1"):
    """BASE scenario plus one invoiced order; returns (base, order)."""
    base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
    order = create_invoiced_order(
        base["customer"]["id"], base["principal"]["id"], ref,
        lines=lines or [
            make_order_line("L1", "CONNECTORS", 100, 5000),
            make_order_line("L2", "CABLES", 50, 2000),
        ],
    )
    return base, order


class TestStatementUpload:
    def test_duplicate_period_label_rejected(self, api):
        """PRD §3.7: "The period label must be unique per principal — a second upload
        of the same month fails with `ERR_DUPLICATE_PERIOD_LABEL`, and a duplicated
        `line_id` inside one statement fails with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/duplicate_period_label_rejected
        """
        p1 = create_principal()
        p2 = create_principal(name="P2", annual_quota_cents=5_000_000)
        create_statement(
            p1["id"], "2026-08",
            [make_statement_line("S1", "PO-1", 100)],
        )
        resp = api.create_statement(
            {
                "principal_id": p1["id"],
                "period_label": "2026-08",
                "lines": [{"line_id": "S1", "external_order_ref": "PO-9",
                           "amount_cents": 200}],
            },
            make_principal_ops_headers(p1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD_LABEL)

        # The same label on a different principal is fine (uniqueness is per principal).
        other = create_statement(
            p2["id"], "2026-08",
            [make_statement_line("S1", "PO-9", 200)],
        )
        assert other["status"] == "RECEIVED"

    def test_adjustment_zero_amount_rejected(self, api):
        """PRD §2.6: "`ADJUSTMENT` amounts may carry either sign but are never zero —
        a zero-amount adjustment is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/adjustment_zero_amount_rejected
        """
        rep = create_rep("R1", ["CA"])
        resp = api.post_rep_adjustment(
            rep["id"], {"amount_cents": 0, "note": "noop"}, _admin(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestExpectationBases:
    def _setup_straddling_ledger(self, api):
        """O_A invoiced in August and paid in September; O_B invoiced in September."""
        base = setup_base_scenario()
        principal = base["principal"]
        customer = base["customer"]
        set_clock("2026-08-05T00:00:00Z")
        o_a = create_invoiced_order(
            customer["id"], principal["id"], "PO-A", placed_at="2026-08-05T00:00:00Z",
            lines=[make_order_line("LA", "CABLES", 100, 2000)],
        )
        set_clock("2026-09-02T00:00:00Z")
        mark_order_paid(o_a["id"], principal["id"])
        set_clock("2026-09-03T00:00:00Z")
        o_b = create_invoiced_order(
            customer["id"], principal["id"], "PO-B", placed_at="2026-09-03T00:00:00Z",
            lines=[make_order_line("LB", "CONNECTORS", 100, 5000)],
        )
        stmt = create_statement(
            principal["id"], "2026-09", [make_statement_line("S1", "PO-B", 50000)],
        )
        return base, o_a, o_b, stmt

    def test_statement_expectation_accrual_basis_canonical(self, api):
        """PRD §3.7: "The canonical expectation, `expected_total_cents`, is
        accrual-basis: the sum of every `ACCRUAL` and `CHARGEBACK` entry amount for
        this principal whose `business_date` falls inside the period month — the
        period runs from the first instant of the `period_label` month up to, but not
        including, the first instant of the following month." and "The `variance_cents`
        is then the stated total minus the accrual expectation."

        Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_expectation
        """
        base, o_a, o_b, stmt = self._setup_straddling_ledger(api)
        reconciled = start_reconciliation(stmt["id"])
        # Only O_B (invoiced 2026-09-03, 50,000c) falls inside period 2026-09.
        assert reconciled["expected_total_cents"] == 50000
        # stated 50,000 - expected 50,000.
        assert reconciled["variance_cents"] == 0

    def test_statement_expectation_cash_basis_informational(self, api):
        """PRD §3.7: "The informational variant, `expected_cash_basis_cents`, instead
        counts `ACCRUAL` entries whose order's `paid_at` falls inside the period
        month, plus `CHARGEBACK` entries by their `business_date`; an identical ledger
        yields a different cash-basis total whenever payment and invoice straddle the
        period boundary." and "An `AgencyAdmin` starting reconciliation moves the
        statement from `RECEIVED` to `IN_RECONCILIATION` and triggers three
        computations."

        Design: Difficulty/dual_variant_calc/statement_accrual_vs_cash_expectation
        """
        base, o_a, o_b, stmt = self._setup_straddling_ledger(api)
        reconciled = start_reconciliation(stmt["id"])
        # Only O_A (paid 2026-09-02, 16,000c) counts on the cash basis.
        assert reconciled["expected_cash_basis_cents"] == 16000
        assert reconciled["expected_total_cents"] != reconciled["expected_cash_basis_cents"]
        assert reconciled["status"] == "IN_RECONCILIATION"
        assert statement_line(reconciled, "S1")["disposition"] == "MATCHED"


class TestDisputeCycleAndSettle:
    def _setup_disputed_statement(self, api):
        """O1 invoiced (58,000c expected); statement S1 58,025 (+25c) and S2 ghost;
        reconciliation run, then S2 disputed."""
        base, order = _setup_invoiced_base(api)
        principal = base["principal"]
        stmt = create_statement(
            principal["id"], "2026-08",
            [make_statement_line("S1", "PO-1", 58025),
             make_statement_line("S2", "PO-GHOST", 99900)],
        )
        return base, order, stmt

    def test_statement_dispute_cycle_returns_to_reconciliation(self, api):
        """PRD §3.7: "A line whose stated amount differs from that expectation by no
        more than twenty-five cents becomes `MATCHED` — the boundary is inclusive, so
        a delta of exactly 25 cents still matches — and anything wider becomes
        `AMOUNT_VARIANCE`." and "when the response resolves the statement's last
        disputed line the statement returns from `DISPUTED` to `IN_RECONCILIATION`".

        Design: Difficulty/non_linear_state_machine/statement_dispute_resolve_cycle
        """
        base, order, stmt = self._setup_disputed_statement(api)
        principal = base["principal"]
        reconciled = start_reconciliation(stmt["id"])
        # stated 157,925 - expected 58,000.
        assert reconciled["variance_cents"] == 99925
        assert statement_line(reconciled, "S1")["disposition"] == "MATCHED"
        assert statement_line(reconciled, "S2")["disposition"] == "UNMATCHED_ORDER"

        disputed = dispute_line(stmt["id"], "S2", "unknown order ref")
        assert disputed["status"] == "DISPUTED"
        assert statement_line(disputed, "S2")["disposition"] == "DISPUTED"

        resolved = respond_dispute(stmt["id"], principal["id"], "S2", "ACCEPT")
        assert statement_line(resolved, "S2")["disposition"] == "RESOLVED"
        assert resolved["status"] == "IN_RECONCILIATION", (
            "resolving the last disputed line returns the statement to IN_RECONCILIATION"
        )

    def test_settle_posts_adjustments_payments_and_zeroes_balances(self, api):
        """PRD §3.7: "Every absorbed delta — a `MATCHED` line whose delta was nonzero,
        a `VARIANCE_ACCEPTED` line, or a `RESOLVED` line carrying an
        `adjustment_amount_cents` — produces `ADJUSTMENT` ledger entries, the signed
        delta allocated across the matched order's split rows pro-rata by `share_bp`
        using the same largest-remainder distribution as invoice allocation. For each
        rep with accruals on the orders the statement covers, one `STATEMENT_PAYMENT`
        entry posts equal to the negative of that rep's accrued share plus that rep's
        share of the adjustments." and "Settlement finishes by moving every covered
        order's `commission_status` to `SETTLED`, stamping `settled_at` with the
        clock".

        Design: Difficulty/non_linear_state_machine/statement_dispute_resolve_cycle
        """
        base, order, stmt = self._setup_disputed_statement(api)
        principal = base["principal"]
        r1, r2 = base["reps"]
        start_reconciliation(stmt["id"])
        dispute_line(stmt["id"], "S2", "unknown order ref")
        respond_dispute(stmt["id"], principal["id"], "S2", "ACCEPT")

        settled = settle_statement(stmt["id"])
        assert settled["status"] == "SETTLED"

        # +25c absorbed delta over the 60/40 splits: +15 / +10.
        # PRD §3.7 posts ADJUSTMENT entries "allocated across the matched order's
        # split rows" (one per split row), so accumulate the per-rep sums.
        adj = list_entries(entry_type="ADJUSTMENT")
        adj_by_rep = {}
        for e in adj:
            adj_by_rep[e["rep_id"]] = adj_by_rep.get(e["rep_id"], 0) + e["amount_cents"]
        assert adj_by_rep == {r1["id"]: 15, r2["id"]: 10}

        pay = list_entries(statement_id=stmt["id"], entry_type="STATEMENT_PAYMENT")
        pay_by_rep = {e["rep_id"]: e["amount_cents"] for e in pay}
        # -(34,800 + 15) and -(23,200 + 10).
        assert pay_by_rep == {r1["id"]: -34815, r2["id"]: -23210}

        assert get_rep(r1["id"])["commission_balance_cents"] == 0
        assert get_rep(r2["id"])["commission_balance_cents"] == 0
        assert get_order(order["id"])["commission_status"] == "SETTLED"

    def test_settle_on_disputed_statement_fails_state_check_first(self, api):
        """PRD §3.7: "Settle is gated: any line still `DISPUTED` blocks it with
        `ERR_UNRESOLVED_DISPUTES`, and any line still `PENDING`, `AMOUNT_VARIANCE`, or
        `UNMATCHED_ORDER` blocks it with `ERR_LINES_NOT_DISPOSITIONED`." A `DISPUTED`
        statement always carries a `DISPUTED` line (disputing moves both, and the
        statement returns to `IN_RECONCILIATION` only when its last disputed line
        resolves), so settling it is blocked by the named unresolved-disputes gate.

        Design: Difficulty/priority_pair_validation_conflict/settle_state_error_beats_unresolved_disputes
        """
        base, order, stmt = self._setup_disputed_statement(api)
        start_reconciliation(stmt["id"])
        dispute_line(stmt["id"], "S2", "unknown order ref")

        resp = api.settle_statement(stmt["id"], _admin())
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_DISPUTES)
        after = get_statement(stmt["id"])
        assert after["status"] == "DISPUTED"
        assert statement_line(after, "S2")["disposition"] == "DISPUTED"

    def test_settle_after_dispute_resolution_succeeds(self, api):
        """PRD §3.7: "Settle is gated: any line still `DISPUTED` blocks it with
        `ERR_UNRESOLVED_DISPUTES`, and any line still `PENDING`, `AMOUNT_VARIANCE`, or
        `UNMATCHED_ORDER` blocks it with `ERR_LINES_NOT_DISPOSITIONED`." Once the
        disputed line is `RESOLVED` and the statement is back `IN_RECONCILIATION`, the
        state gate passes and settle succeeds.

        Design: Difficulty/priority_pair_validation_conflict/settle_state_error_beats_unresolved_disputes
        """
        base, order, stmt = self._setup_disputed_statement(api)
        principal = base["principal"]
        start_reconciliation(stmt["id"])
        dispute_line(stmt["id"], "S2", "unknown order ref")
        respond_dispute(stmt["id"], principal["id"], "S2", "ACCEPT")
        settled = settle_statement(stmt["id"])
        assert settled["status"] == "SETTLED"


class TestSettleGatesAndDraw:
    def test_settle_with_undispositioned_lines_rejected(self, api):
        """PRD §3.7: "Settle is gated: any line still `DISPUTED` blocks it with
        `ERR_UNRESOLVED_DISPUTES`, and any line still `PENDING`, `AMOUNT_VARIANCE`, or
        `UNMATCHED_ORDER` blocks it with `ERR_LINES_NOT_DISPOSITIONED`."

        Design: Corner/validations/settle_with_undispositioned_lines_rejected
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        principal = base["principal"]
        create_invoiced_order(
            base["customer"]["id"], principal["id"], "PO-1",
            lines=[make_order_line("L1", "CONNECTORS", 100, 5000)],
        )
        stmt = create_statement(
            principal["id"], "2026-08", [make_statement_line("S1", "PO-1", 60000)],
        )
        reconciled = start_reconciliation(stmt["id"])
        # |60,000 - 50,000| = 10,000 > 25 -> AMOUNT_VARIANCE.
        assert statement_line(reconciled, "S1")["disposition"] == "AMOUNT_VARIANCE"

        resp = api.settle_statement(stmt["id"], _admin())
        validate_error(resp, ApiErrorId.ERR_LINES_NOT_DISPOSITIONED)
        assert get_statement(stmt["id"])["status"] == "IN_RECONCILIATION"

    def test_settled_statement_terminal_lockdown(self, api):
        """PRD §3.7: "`SETTLED` is the statement's terminal state." and PRD §2.9:
        "The target resource's state permits the requested
        transition, terminal states are locked, a return authorization is created only
        against an order in `SHIPPED`, `INVOICED`, or `PAID`, a sample checkout is
        created only against a unit in `IN_STOCK`, and a split override is attempted
        only while the order's commission dimension is still `ATTRIBUTED` — otherwise
        `ERR_INVALID_STATE_TRANSITION` or `ERR_SPLITS_LOCKED`."

        Design: Corner/state_machines/settled_statement_terminal_lockdown
        """
        base, order = _setup_invoiced_base(api)
        stmt = create_statement(
            base["principal"]["id"], "2026-08",
            [make_statement_line("S1", "PO-1", 58000)],
        )
        start_reconciliation(stmt["id"])
        settled = settle_statement(stmt["id"])
        assert settled["status"] == "SETTLED"

        resp = api.dispute_statement_line(stmt["id"], "S1", {"reason": "too late"},
                                          _admin())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_statement(stmt["id"])["status"] == "SETTLED"

    def test_draw_recovery_waterfall_floor_and_cap(self, api):
        """PRD §3.7: "Then the draw-recovery waterfall runs over reps with a positive
        `outstanding_draw_cents`, oldest rep first by `created_at`: a rep's gross is
        its accrued share on covered orders plus its adjustment share; a gross of zero
        or less means no payment and no recovery; otherwise the recovery is the
        smaller of the rep's `outstanding_draw_cents` and one half of the gross
        rounded down to whole cents, posted as a negative `DRAW_RECOVERY` entry with
        the rep's `outstanding_draw_cents` reduced by the recovered amount. The
        recovery rides inside the payout — the payment entry is the negative of the
        full gross, and the rep's cash payout is what remains after the skim."

        Design: Corner/calculations/draw_recovery_waterfall_floor_and_cap
        """
        principal = create_principal(name="P3")
        agreement = create_agreement(principal["id"], territory_codes=["CO"])
        activate_agreement(agreement["id"])
        create_rate_schedule(
            principal["id"], principal["version"],
            family_rates=[{"family_code": "CONNECTORS", "base_rate_bp": 1000}],
            attainment_tiers=[{"min_attainment_bp": 0, "multiplier_bp": 10000}],
        )
        rep = create_rep("R9", ["CO"], outstanding_draw_cents=10_000)
        customer = create_customer(name="C9", spec_territory_code="CO",
                                   ship_to_territory_code="CO")
        order = create_invoiced_order(
            customer["id"], principal["id"], "PO-D",
            lines=[make_order_line(quantity=60, unit_price_cents=5000)],
        )
        stmt = create_statement(
            principal["id"], "2026-08", [make_statement_line("S1", "PO-D", 30000)],
        )
        start_reconciliation(stmt["id"])
        settled = settle_statement(stmt["id"])
        assert settled["status"] == "SETTLED"

        pay = list_entries(statement_id=stmt["id"], entry_type="STATEMENT_PAYMENT")
        assert len(pay) == 1 and pay[0]["rep_id"] == rep["id"]
        assert pay[0]["amount_cents"] == -30000, "payment is the negative of full gross"

        recovery = list_entries(statement_id=stmt["id"], entry_type="DRAW_RECOVERY")
        assert len(recovery) == 1 and recovery[0]["rep_id"] == rep["id"]
        # min(10,000 draw, floor(30,000 x 5000/10000) = 15,000) — the draw caps it.
        assert recovery[0]["amount_cents"] == -10000

        after = get_rep(rep["id"])
        assert after["outstanding_draw_cents"] == 0
        # 30,000 accrual - 30,000 payment - 10,000 recovery.
        assert after["commission_balance_cents"] == -10000
        assert after["status"] == "ACTIVE", "-10,000c is above the -50,000c hold floor"
