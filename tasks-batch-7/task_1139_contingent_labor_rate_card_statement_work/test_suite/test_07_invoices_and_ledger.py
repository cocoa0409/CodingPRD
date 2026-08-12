"""Invoice consolidation (per-line rounding, tiered fee, savings), the spend
ledger, void compensation, segregation of duties, and computed reads."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_invoice,
    assert_invoice_line,
    assert_ledger_sums_to_spend,
    assert_spend_ledger_entry,
    create_active_rate_card,
    create_approved_timesheet,
    create_assignment_payload,
    create_engagement_in_open,
    create_invoice_payload,
    create_manual_invoice,
    create_milestone_payload,
    create_submitted_timesheet,
    create_worker_payload,
    find_open_invoice_id,
    get_engagement,
    get_invoice,
    get_milestone,
    get_success_data,
    get_supplier,
    make_finance_analyst_headers,
    make_supplier_coordinator_headers,
    onboard_supplier,
    pick_offer_for_supplier,
    set_logical_clock,
    setup_sow_engagement,
    setup_staffed_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
FIN = TEST_USERS["finance_analyst_headers"]
FIN_1 = make_finance_analyst_headers("fin-1")
FIN_2 = make_finance_analyst_headers("fin-2")


def _staff_supplier_with_approved_timesheet(api, supplier, *, bill_rate_cents=9000,
                                            hours=10.0, budget_cents=1_000_000):
    """Staff the given supplier on a fresh REQUISITION engagement and approve
    one timesheet. Returns (engagement, assignment, timesheet)."""
    rate_card = create_active_rate_card()
    engagement = create_engagement_in_open(budget_cents=budget_cents)
    offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
    offer = pick_offer_for_supplier(offers, supplier["id"])
    get_success_data(
        api.respond_to_offer(
            offer["id"], {"action": "ACCEPT"},
            make_supplier_coordinator_headers(supplier["id"]),
        )
    )
    worker = get_success_data(
        api.create_worker(
            create_worker_payload(supplier["id"], full_name="Worker One",
                                  email="w1@example.com"),
            make_supplier_coordinator_headers(supplier["id"]),
        )
    )
    assignment = get_success_data(
        api.create_assignment(
            create_assignment_payload(
                worker["id"], engagement["id"], offer["id"], rate_card["id"],
                bill_rate_cents=bill_rate_cents, pay_rate_cents=8000),
            ADMIN,
        )
    )
    get_success_data(api.activate_assignment(assignment["id"], ADMIN))
    timesheet = create_approved_timesheet(
        assignment["id"], worker["id"], submitted_hours=hours
    )
    return engagement, assignment, timesheet, worker


class TestInvoiceFinalizeZeroVsOneLine:
    def test_finalize_empty_invoice_rejected(self, api):
        """PRD: "An invoice with zero lines cannot be finalized —
        `line_count` must be at least 1, else `ERR_INVOICE_EMPTY` (422)."

        Design: Difficulty/boundary_precision_check/invoice_finalize_zero_lines_vs_one_line
        """
        set_logical_clock("2026-05-01T00:00:00Z")
        supplier = onboard_supplier(tier="APPROVED", name="Iota Staffing",
                                    supplier_code="SUP-I1")
        invoice = create_manual_invoice(
            supplier["id"], period_start="2026-05-01", period_end="2026-05-31"
        )
        assert invoice["status"] == "OPEN"
        assert invoice["line_count"] == 0
        resp = api.finalize_invoice(invoice["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_EMPTY)
        after = get_invoice(invoice["id"])
        assert after["status"] == "OPEN", "the rejected finalize leaves the invoice OPEN"
        assert after["line_count"] == 0

    def test_finalize_one_line_invoice_zero_savings(self, api):
        """PRD: "The `consolidation_savings_cents` quantifies the batching
        benefit against a per-invoice fee baseline of 5,000 cents: it is one
        less than `line_count`, multiplied by 5,000, whenever `line_count` is
        at least 1, and zero otherwise"
        PRD: "The `processing_fee_cents` is the subtotal multiplied by that
        rate, rounded half up to whole cents, and `total_cents` is the
        subtotal plus the fee."

        Design: Difficulty/boundary_precision_check/invoice_finalize_zero_lines_vs_one_line
        """
        set_logical_clock("2026-05-01T00:00:00Z")
        supplier = onboard_supplier(tier="APPROVED", name="Iota Staffing",
                                    supplier_code="SUP-I1")
        invoice = create_manual_invoice(
            supplier["id"], period_start="2026-05-01", period_end="2026-05-31"
        )
        _engagement, _assignment, timesheet, _worker = (
            _staff_supplier_with_approved_timesheet(
                api, supplier, bill_rate_cents=9000, hours=10.0
            )
        )
        assert timesheet["final_amount_cents"] == 90_000
        assert get_invoice(invoice["id"])["line_count"] == 1, (
            "the approved timesheet's line attaches to the existing OPEN invoice"
        )

        finalized = validate_success(api.finalize_invoice(invoice["id"], FIN))
        assert_invoice(finalized)
        assert finalized["status"] == "FINALIZED"
        assert finalized["line_count"] == 1
        assert finalized["subtotal_cents"] == 90_000
        assert finalized["processing_fee_cents"] == 1350, (
            "round_half_up(90000 x 0.015)"
        )
        assert finalized["total_cents"] == 91_350
        assert finalized["consolidation_savings_cents"] == 0, (
            "one-line boundary: (1-1) x 5000, no savings"
        )


class TestInvoicePerLineRounding:
    def _setup_two_approved_timesheets(self, api):
        ctx = setup_staffed_assignment(
            supplier_tier="APPROVED", supplier_name="Beta Staffing",
            supplier_code="SUP-B1", bill_rate_cents=9001, pay_rate_cents=8000,
        )
        t1 = create_approved_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-04", period_end="2026-05-10",
            submitted_hours=2.5,
        )
        t2 = create_approved_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-11", period_end="2026-05-17",
            submitted_hours=4.5,
        )
        return ctx, t1, t2

    def test_per_line_round_half_up_at_approval(self, api):
        """PRD: "The line's `amount_cents` is already a whole-cent integer at
        attach time, because timesheet finals are rounded per timesheet at
        approval and milestone amounts are integers by definition."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        _ctx, t1, t2 = self._setup_two_approved_timesheets(api)
        assert t1["final_amount_cents"] == 22_503, (
            "round_half_up(2.5 x 9001 = 22502.5) per line at approval"
        )
        assert t2["final_amount_cents"] == 40_505, (
            "round_half_up(4.5 x 9001 = 40504.5) per line at approval"
        )

    def test_invoice_subtotal_sums_rounded_lines(self, api):
        """PRD: "an invoice's `subtotal_cents` is the plain integer sum of
        its attached lines' `amount_cents`, and `line_count` is their count —
        rounding happens exclusively per line upstream and never again at
        invoice level."
        PRD: "The counterfactual of summing raw fractional amounts and
        rounding once at the end is forbidden because it diverges: fractional
        lines of 22502.5 and 40504.5 would sum-and-round to 63007, while the
        pinned per-line amounts 22503 and 40505 sum to 63008."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ctx, _t1, _t2 = self._setup_two_approved_timesheets(api)
        invoice_id = find_open_invoice_id(ctx["supplier"]["id"])
        finalized = validate_success(api.finalize_invoice(invoice_id, FIN))
        assert finalized["line_count"] == 2
        assert finalized["subtotal_cents"] == 63_008, (
            "per-line-round-then-sum; the forbidden sum-then-round order yields 63007"
        )
        assert finalized["processing_fee_cents"] == 945, (
            "round_half_up(63008 x 0.015 = 945.12)"
        )
        assert finalized["total_cents"] == 63_953
        assert finalized["consolidation_savings_cents"] == 5000, "(2-1) x 5000"


class TestInvoiceFeeTieredOnPrefeeSubtotal:
    def _setup_two_accepted_milestones(self, api):
        sow = setup_sow_engagement(
            supplier_name="Gamma Solutions", supplier_code="SUP-G1",
            budget_cents=50_000_000,
        )
        m1 = get_success_data(
            api.create_milestone(
                sow["engagement"]["id"],
                create_milestone_payload(name="M1", amount_cents=5_000_000,
                                         due_date="2026-06-30"),
                HM,
            )
        )
        m2 = get_success_data(
            api.create_milestone(
                sow["engagement"]["id"],
                create_milestone_payload(name="M2", amount_cents=4_999_999,
                                         due_date="2026-07-31"),
                HM,
            )
        )
        coordinator = make_supplier_coordinator_headers(sow["supplier"]["id"])
        for milestone in (m1, m2):
            get_success_data(api.deliver_milestone(milestone["id"], {}, coordinator))
            get_success_data(api.accept_milestone(milestone["id"], HM))
        return sow

    def test_fee_tier_keyed_on_prefee_subtotal(self, api):
        """PRD: "The processing fee is tiered on the pre-fee subtotal — never
        on the post-fee total: when `subtotal_cents` is below 10,000,000
        cents the fee rate is 1.5%; when the subtotal is at or above
        10,000,000 cents the rate is 1.0%."

        Design: Difficulty/combinatorial_formula/invoice_fee_tiered_on_prefee_subtotal
        """
        sow = self._setup_two_accepted_milestones(api)
        invoice_id = find_open_invoice_id(sow["supplier"]["id"])
        finalized = validate_success(api.finalize_invoice(invoice_id, FIN))
        assert finalized["subtotal_cents"] == 9_999_999, "5000000 + 4999999"
        assert finalized["processing_fee_cents"] == 150_000, (
            "tier keyed on the pre-fee subtotal (< 10000000 -> 1.5%): "
            "round_half_up(9999999 x 0.015 = 149999.985)"
        )

    def test_total_crosses_threshold_but_fee_stays_at_low_tier(self, api):
        """PRD: "Keying the tier on the post-fee total would diverge — a
        subtotal of 9,999,999 cents yields a fee of 150,000 cents and a total
        of 10,149,999 cents that crosses the threshold, yet the 1.5% rate
        still applies because the tier was fixed on the pre-fee subtotal."

        Design: Difficulty/combinatorial_formula/invoice_fee_tiered_on_prefee_subtotal
        """
        sow = self._setup_two_accepted_milestones(api)
        invoice_id = find_open_invoice_id(sow["supplier"]["id"])
        finalized = validate_success(api.finalize_invoice(invoice_id, FIN))
        assert finalized["total_cents"] == 10_149_999, (
            "post-fee total crosses 10000000 yet the 1.5% rate still applies"
        )
        assert finalized["consolidation_savings_cents"] == 5000
        assert finalized["line_count"] == 2


def test_second_open_invoice_returns_409(api):
    """PRD: "Invoicing is organized around one invariant: a supplier has at
    most one `OPEN` invoice at any time."
    PRD: "when the supplier already has an `OPEN` invoice the manual creation
    is rejected with `ERR_INVOICE_ALREADY_OPEN` (409)."

    Design: Corner/errors/second_open_invoice_returns_409
    """
    supplier = onboard_supplier(tier="APPROVED", name="Inv Co", supplier_code="SUP-IV")
    create_manual_invoice(supplier["id"], period_start="2026-05-01",
                          period_end="2026-05-31")
    resp = api.create_invoice(
        create_invoice_payload(supplier["id"], period_start="2026-06-01",
                               period_end="2026-06-30"),
        FIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_ALREADY_OPEN)
    # even for a different period


class TestInvoiceSegregationOfDuties:
    def _setup_finalized_invoice(self, api):
        ctx = setup_staffed_assignment(supplier_name="SoD Co", supplier_code="SUP-SD",
                                       bill_rate_cents=9000)
        create_approved_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"], submitted_hours=10.0
        )
        invoice_id = find_open_invoice_id(ctx["supplier"]["id"])
        finalized = get_success_data(api.finalize_invoice(invoice_id, FIN_1))
        assert finalized["finalized_by_user_id"] == "fin-1"
        return ctx, invoice_id

    def test_mark_paid_by_finalizer_rejected_sod(self, api):
        """PRD: "marking a `FINALIZED` invoice paid requires the caller's
        `X-User-ID` to differ from the invoice's `finalized_by_user_id`; the
        same person attempting both steps is rejected with
        `ERR_SOD_VIOLATION` (403)."

        Design: Corner/rbac/invoice_finalize_pay_same_user_rejected
        """
        _ctx, invoice_id = self._setup_finalized_invoice(api)
        resp = api.mark_invoice_paid(invoice_id, FIN_1)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        after = get_invoice(invoice_id)
        assert after["status"] == "FINALIZED", "the SoD rejection leaves it FINALIZED"
        assert after["paid_by_user_id"] is None

    def test_mark_paid_by_different_analyst_succeeds(self, api):
        """PRD: "A successful payment stamps `paid_by_user_id` and moves
        every attached milestone `INVOICED` → `PAID`."
        PRD: "marking a `FINALIZED` invoice paid requires the caller's
        `X-User-ID` to differ from the invoice's `finalized_by_user_id`"

        Design: Corner/rbac/invoice_finalize_pay_same_user_rejected
        """
        _ctx, invoice_id = self._setup_finalized_invoice(api)
        paid = validate_success(api.mark_invoice_paid(invoice_id, FIN_2))
        assert paid["status"] == "PAID"
        assert paid["paid_by_user_id"] == "fin-2"
        assert paid["paid_by_user_id"] != paid["finalized_by_user_id"]


class TestInvoiceVoidMigration:
    def _setup_finalized_sow_invoice(self, api):
        sow = setup_sow_engagement(
            supplier_name="Void Co", supplier_code="SUP-VO", budget_cents=5_000_000,
        )
        milestone = get_success_data(
            api.create_milestone(
                sow["engagement"]["id"],
                create_milestone_payload(name="M", amount_cents=1_000_000,
                                         due_date="2026-06-30"),
                HM,
            )
        )
        coordinator = make_supplier_coordinator_headers(sow["supplier"]["id"])
        get_success_data(api.deliver_milestone(milestone["id"], {}, coordinator))
        accepted = get_success_data(api.accept_milestone(milestone["id"], HM))
        assert accepted["payment_status"] == "UNINVOICED"
        invoice_id = find_open_invoice_id(sow["supplier"]["id"])
        get_success_data(api.finalize_invoice(invoice_id, FIN_1))
        assert get_milestone(milestone["id"])["payment_status"] == "INVOICED"
        return sow, milestone, invoice_id

    def test_invoice_void_migrates_lines_to_fresh_open_invoice(self, api):
        """PRD: "Voiding unwinds a `FINALIZED` invoice: the request's
        `reason` is recorded into `void_reason`, every attached line is
        detached and re-attached to a fresh `OPEN` invoice for the supplier
        (auto-created when none exists)"

        Design: Corner/cross_cutting/invoice_void_returns_lines_to_fresh_open_invoice
        """
        sow, milestone, invoice_id = self._setup_finalized_sow_invoice(api)
        voided = validate_success(
            api.void_invoice(invoice_id, {"reason": "wrong billing period"}, FIN)
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "wrong billing period"
        assert voided["id"] == invoice_id, "the VOIDED invoice keeps its identity"

        lines, meta = validate_paginated(
            api.list_invoice_lines(FIN, params={"milestone_id": milestone["id"]})
        )
        assert meta["total_count"] == 1
        assert lines[0]["amount_cents"] == 1_000_000, "the migrated line is intact"
        assert lines[0]["invoice_id"] != invoice_id
        open_invoice_id = find_open_invoice_id(sow["supplier"]["id"])
        assert lines[0]["invoice_id"] == open_invoice_id, (
            "exactly one fresh OPEN invoice holds the migrated line"
        )

    def test_invoice_void_reverts_milestone_payment_status(self, api):
        """PRD: "every milestone whose line was attached reverts from
        `INVOICED` back to `UNINVOICED`."
        PRD: "Finalization stamps `finalized_by_user_id` with the caller's
        `X-User-ID` and moves every milestone whose line is attached from
        `UNINVOICED` to `INVOICED` on the payment dimension."

        Design: Corner/cross_cutting/invoice_void_returns_lines_to_fresh_open_invoice
        """
        _sow, milestone, invoice_id = self._setup_finalized_sow_invoice(api)
        validate_success(
            api.void_invoice(invoice_id, {"reason": "wrong billing period"}, FIN)
        )
        milestone_after = get_milestone(milestone["id"])
        assert milestone_after["payment_status"] == "UNINVOICED", (
            "compensation of the finalize side effect"
        )
        assert milestone_after["acceptance_status"] == "ACCEPTED", (
            "voiding does not touch the acceptance dimension"
        )


def test_spend_summary_computed_read(api):
    """PRD: "A consolidated spend summary — available to `ProgramAdmin` and
    `FinanceAnalyst`, optionally narrowed to one supplier via `supplier_id` —
    reports five aggregates across the program: `total_committed_cents`
    (approved spend), `total_invoiced_cents`, `total_paid_cents`,
    `consolidation_savings_cents` realized through batching, and
    `open_violations_count`."

    Design: Corner/endpoints/spend_summary_computed_read
    """
    ctx = setup_staffed_assignment(supplier_name="Summary Co",
                                   supplier_code="SUP-SU", bill_rate_cents=9000)
    timesheet = create_approved_timesheet(
        ctx["assignment"]["id"], ctx["worker"]["id"], submitted_hours=10.0
    )
    assert timesheet["final_amount_cents"] == 90_000
    invoice_id = find_open_invoice_id(ctx["supplier"]["id"])
    get_success_data(api.finalize_invoice(invoice_id, FIN_1))
    get_success_data(api.mark_invoice_paid(invoice_id, FIN_2))

    summary = validate_success(api.get_spend_summary(FIN))
    assert summary["total_committed_cents"] == 90_000, "approved timesheet"
    assert summary["total_invoiced_cents"] == 91_350, (
        "subtotal 90000 + fee round_half_up(90000 x 0.015) = 1350"
    )
    assert summary["total_paid_cents"] == 91_350
    assert summary["consolidation_savings_cents"] == 0, "single-line invoice"
    assert summary["open_violations_count"] == 0


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD: "List assignments; filters `worker_id`, `engagement_id`,
    `supplier_id`, `rate_card_id`, `offer_id`, `status`"
    PRD: "List timesheets; filters `assignment_id`, `status`"
    PRD: "invoice lines are reverse-reachable through filters on
    `invoice_id`, `timesheet_id` and `milestone_id`."

    Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
    """
    ctx = setup_staffed_assignment(supplier_name="FK Co", supplier_code="SUP-FK",
                                   bill_rate_cents=9500)
    timesheet = create_approved_timesheet(
        ctx["assignment"]["id"], ctx["worker"]["id"], submitted_hours=8.0
    )

    assignments, meta_a = validate_paginated(
        api.list_assignments(ADMIN, params={"worker_id": ctx["worker"]["id"]})
    )
    assert meta_a["total_count"] == 1
    assert assignments[0]["id"] == ctx["assignment"]["id"]

    timesheets, meta_t = validate_paginated(
        api.list_timesheets(ADMIN, params={"assignment_id": ctx["assignment"]["id"]})
    )
    assert meta_t["total_count"] == 1
    assert timesheets[0]["id"] == timesheet["id"]

    lines, meta_l = validate_paginated(
        api.list_invoice_lines(FIN, params={"timesheet_id": timesheet["id"]})
    )
    assert meta_l["total_count"] == 1
    assert_invoice_line(lines[0])
    assert lines[0]["amount_cents"] == 76_000, "8.0 x 9500"
    assert lines[0]["timesheet_id"] == timesheet["id"]


def test_ledger_entry_immutable_no_version(api):
    """PRD: "Two resource kinds are deliberately lighter: an invoice line and
    a spend ledger entry carry only `id` and `created_at`."
    PRD: "Both `updated_at` and `version` are absent on those two kinds —
    they are immutable records of an event, never edited in place."
    PRD: "Its `entry_type` is one of `TIMESHEET_APPROVED`, `TIMESHEET_VOIDED`
    or `MILESTONE_ACCEPTED`; its `delta_cents` is the signed amount applied
    to the supplier's spend — positive on approval or acceptance, negative on
    a void — and its `running_balance_cents` records the supplier's spend
    balance immediately after the entry"

    Design: Corner/entities/ledger_entry_immutable_no_version
    """
    ctx = setup_staffed_assignment(supplier_name="Ledger Co",
                                   supplier_code="SUP-LG", bill_rate_cents=9000)
    timesheet = create_approved_timesheet(
        ctx["assignment"]["id"], ctx["worker"]["id"], submitted_hours=10.0
    )
    entries, meta = validate_paginated(
        api.list_spend_ledger_entries(FIN, params={"timesheet_id": timesheet["id"]})
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert_spend_ledger_entry(entry)
    assert entry["entry_type"] == "TIMESHEET_APPROVED"
    assert entry["delta_cents"] == 90_000
    assert entry["running_balance_cents"] == 90_000

    fetched = validate_success(api.get_spend_ledger_entry(entry["id"], FIN))
    assert "version" not in fetched and "updated_at" not in fetched
    assert "id" in fetched and "created_at" in fetched


class TestTimesheetVoidRestoresSpendInvariant:
    def _setup_approved_timesheet(self, api):
        ctx = setup_staffed_assignment(supplier_name="Nu Staffing",
                                       supplier_code="SUP-N1")
        timesheet = create_approved_timesheet(
            ctx["assignment"]["id"], ctx["worker"]["id"],
            period_start="2026-05-04", period_end="2026-05-10",
            submitted_hours=35.0,
        )
        assert timesheet["final_amount_cents"] == 332_500
        assert get_supplier(ctx["supplier"]["id"])["spend_ytd_cents"] == 332_500
        return ctx, timesheet

    def test_void_returns_spend_to_pre_approve_baseline(self, api):
        """PRD: "A void records the request's `reason` into `void_reason` and
        compensates every effect of the approval: a ledger entry of type
        `TIMESHEET_VOIDED` is appended with a negative `delta_cents` equal to
        the voided `final_amount_cents` and `spend_ytd_cents` is recomputed;
        the sourcing invoice line is deleted and the invoice's `line_count`
        and `subtotal_cents` are recomputed; and the engagement's
        `committed_spend_cents` is recomputed."

        Design: Difficulty/compensating_invariant/timesheet_void_restores_spend_invariant
        """
        ctx, timesheet = self._setup_approved_timesheet(api)
        voided = validate_success(
            api.void_timesheet(timesheet["id"], {"reason": "duplicate entry"}, FIN)
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "duplicate entry"
        assert get_supplier(ctx["supplier"]["id"])["spend_ytd_cents"] == 0, (
            "exactly the pre-approve baseline"
        )
        assert get_engagement(ctx["engagement"]["id"])["committed_spend_cents"] == 0
        invoice_id = find_open_invoice_id(ctx["supplier"]["id"])
        invoice = get_invoice(invoice_id)
        assert invoice["subtotal_cents"] == 0
        assert invoice["line_count"] == 0, "line detached"

    def test_void_appends_compensating_ledger_entry_and_detaches_line(self, api):
        """PRD: "A supplier's `spend_ytd_cents` is exactly the sum of
        `delta_cents` across its ledger entries — approved spend net of voids
        — so the ledger is never edited, only appended to, and every reversal
        is itself a new entry."

        Design: Difficulty/compensating_invariant/timesheet_void_restores_spend_invariant
        """
        ctx, timesheet = self._setup_approved_timesheet(api)
        validate_success(
            api.void_timesheet(timesheet["id"], {"reason": "duplicate entry"}, FIN)
        )
        entries, meta = validate_paginated(
            api.list_spend_ledger_entries(FIN, params={"timesheet_id": timesheet["id"]})
        )
        assert meta["total_count"] == 2, "approve then void: exactly two entries"
        by_type = {e["entry_type"]: e for e in entries}
        assert by_type["TIMESHEET_APPROVED"]["delta_cents"] == 332_500
        assert by_type["TIMESHEET_VOIDED"]["delta_cents"] == -332_500
        assert_ledger_sums_to_spend(entries, 0)
        assert sorted(e["running_balance_cents"] for e in entries) == [0, 332_500]
        _, meta_lines = validate_paginated(
            api.list_invoice_lines(FIN, params={"timesheet_id": timesheet["id"]})
        )
        assert meta_lines["total_count"] == 0, "sourcing invoice line deleted"


def test_immediate_consistency_on_approve(api):
    """PRD: "On success the approval stamps `approved_by_user_id` and fires a
    four-link cascade."
    PRD: "Link 2: the engagement's `committed_spend_cents` is recomputed."
    PRD: "Link 1: a spend ledger entry of type `TIMESHEET_APPROVED` is
    appended with a positive `delta_cents` equal to `final_amount_cents`, and
    the supplier's `spend_ytd_cents` is recomputed."

    Design: Corner/consistency/immediate_consistency_on_approve
    """
    ctx = setup_staffed_assignment(supplier_name="Cons Co", supplier_code="SUP-CO")
    timesheet = create_submitted_timesheet(
        ctx["assignment"]["id"], ctx["worker"]["id"], submitted_hours=8.0
    )
    approved = validate_success(api.approve_timesheet(timesheet["id"], {}, HM))
    assert approved["status"] == "APPROVED"
    assert approved["final_amount_cents"] == 76_000, (
        "the approve response itself carries the computed final"
    )
    assert approved["approved_by_user_id"] == HM["X-User-ID"]

    # The very next reads (no waiting, no recompute endpoint) agree.
    assert get_engagement(ctx["engagement"]["id"])["committed_spend_cents"] == 76_000
    assert get_supplier(ctx["supplier"]["id"])["spend_ytd_cents"] == 76_000
    entries, meta = validate_paginated(
        api.list_spend_ledger_entries(FIN, params={"timesheet_id": timesheet["id"]})
    )
    assert meta["total_count"] == 1
    assert entries[0]["delta_cents"] == 76_000
    assert entries[0]["running_balance_cents"] == 76_000
