"""Invoicing: the seven pinned numbers, retainage tiers, issuance, voiding and payment."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_invoice, assert_contract, assert_expense, assert_invoice_money_identity,
    assert_contract_wip_identity,
    state_payload, create_invoice_payload,
    setup_executed_project,
    activate_phase, activate_and_complete_phase, activate_and_advance_phase, set_phase_percent,
    create_approved_expense, draft_invoice, issue_invoice, draft_and_issue_invoice,
    record_payment, get_contract_version, read_contract, read_phase, read_expense,
    PRINCIPAL,
)

# SD 2_000_000 / DD 4_000_000 / CD 2_000_000 / CA 2_000_000 against a base fee of 10_000_000.
DD_HEAVY_WEIGHTS = (2000, 4000, 2000, 2000)


def _setup_for_retainage_boundary(project_number="RET-001", dd_percent=75):
    """SD COMPLETED (2_000_000 earned) and DD ACTIVE at `dd_percent`, with no expenses."""
    bundle = setup_executed_project(
        project_number=project_number, name="Retainage Row",
        weights=DD_HEAVY_WEIGHTS, with_architect=False,
    )
    activate_and_complete_phase(bundle, "SD")
    activate_and_advance_phase(bundle, "DD", dd_percent)
    return bundle


def _setup_with_expense_and_draft_invoice(project_number):
    """SD COMPLETED, DD at 60 percent, one APPROVED reimbursable expense, one DRAFT invoice."""
    bundle = setup_executed_project(project_number=project_number, name="Parallel Plaza")
    activate_and_complete_phase(bundle, "SD")
    activate_and_advance_phase(bundle, "DD", 60)
    expense = create_approved_expense(
        bundle, category="PRINTING", amount_cents=100_000, reimbursable=True, markup_bp=1000
    )
    bundle["expense"] = expense
    invoice = draft_invoice(bundle)
    bundle["invoice"] = invoice
    bundle["invoice_id"] = invoice["id"]
    return bundle


class TestRetainageTierIsKeyedOnTheCumulativeFee:

    def test_a_ratio_landing_exactly_on_5000_bp_selects_the_ten_percent_tier(self, api):
        """PRD §3.9: "**Fifth**, select the retainage tier from that cumulative figure, using
        integer arithmetic only. Multiply the cumulative amount by 10000, divide by the contract's
        `total_fee_cents`, and take the **floor** of the quotient — no rounding — to obtain a ratio
        in basis points. If that ratio is at most 5000 basis points (the contract is at most half
        billed), `retainage_bp` is 1000, a ten percent hold-back."
        PRD §3.9: "**Fourth**, compute the cumulative fee the contract will have billed *after* this
        invoice: the contract's `billed_fee_to_date_cents` plus this invoice's `fee_billed_cents`."

        Design: Difficulty/combinatorial_formula/invoice_retainage_tier_keyed_on_cumulative_fee_after_this_invoice
        """
        bundle = _setup_for_retainage_boundary("RET-001", dd_percent=75)

        assert read_phase(bundle, "SD")["earned_cents"] == 2_000_000
        assert read_phase(bundle, "DD")["earned_cents"] == 3_000_000  # 4_000_000 * 75 / 100

        invoice = draft_invoice(bundle)
        assert_invoice(invoice)

        assert invoice["fee_billed_cents"] == 5_000_000
        assert invoice["reimbursable_cents"] == 0
        assert invoice["gross_cents"] == 5_000_000
        # floor(5_000_000 * 10000 / 10_000_000) == 5000, which is "at most 5000".
        assert invoice["retainage_bp"] == 1000

    def test_retainage_is_taken_on_the_gross_and_net_due_follows(self, api):
        """PRD §3.9: "**Sixth**, `retainage_cents` is `gross_cents` multiplied by `retainage_bp`,
        divided by 10000, rounded half up. Note that retainage is taken on the **gross** — fee plus
        reimbursables together — and not on the fee alone."
        PRD §3.9: "**Seventh**, `net_due_cents` is `gross_cents` minus `retainage_cents`. That is
        what the client actually owes."

        Design: Difficulty/combinatorial_formula/invoice_retainage_tier_keyed_on_cumulative_fee_after_this_invoice
        """
        bundle = _setup_for_retainage_boundary("RET-002", dd_percent=75)

        invoice = draft_invoice(bundle)
        assert_invoice(invoice)

        assert invoice["gross_cents"] == 5_000_000
        assert invoice["retainage_bp"] == 1000
        assert invoice["retainage_cents"] == 500_000  # 5_000_000 * 1000 / 10000
        assert invoice["net_due_cents"] == 4_500_000
        assert_invoice_money_identity(invoice)

    def test_a_ratio_just_above_5000_bp_drops_to_the_five_percent_tier(self, api):
        """PRD §3.9: "If the ratio is above 5000 but at most 9000, `retainage_bp` drops to 500, a
        five percent hold-back."
        PRD §3.9: "**Sixth**, `retainage_cents` is `gross_cents` multiplied by `retainage_bp`,
        divided by 10000, rounded half up. Note that retainage is taken on the **gross** — fee plus
        reimbursables together — and not on the fee alone."

        Design: Corner/calculations/retainage_tier_drops_to_500bp_once_ratio_exceeds_5000bp
        """
        bundle = _setup_for_retainage_boundary("TIR-001", dd_percent=76)

        assert read_phase(bundle, "DD")["earned_cents"] == 3_040_000  # 4_000_000 * 76 / 100

        invoice = draft_invoice(bundle)
        assert_invoice(invoice)

        assert invoice["fee_billed_cents"] == 5_040_000
        assert invoice["gross_cents"] == 5_040_000
        # floor(5_040_000 * 10000 / 10_000_000) == 5040, which is above 5000.
        assert invoice["retainage_bp"] == 500
        assert invoice["retainage_cents"] == 252_000
        assert invoice["net_due_cents"] == 4_788_000


class TestInvoiceParallelDimensions:

    def test_issuing_an_invoice_leaves_the_payment_dimension_untouched(self, api):
        """PRD §3.9: "It is born in status `DRAFT` and payment status `UNPAID`, with
        `amount_paid_cents` at 0 and `issued_at` null."
        PRD §3.9: "The invoice's `payment_status` is a genuinely independent second dimension: it
        evolves on its own, and neither dimension ever moves the other."

        Design: Difficulty/non_linear_state_machine/invoice_status_and_payment_status_are_independent_dimensions
        """
        bundle = _setup_with_expense_and_draft_invoice("PAR-001")
        draft = bundle["invoice"]
        assert draft["status"] == "DRAFT"
        assert draft["payment_status"] == "UNPAID"
        assert draft["amount_paid_cents"] == 0
        assert draft["issued_at"] is None

        issued = issue_invoice(bundle["invoice_id"], bundle)
        assert_invoice(issued)

        assert issued["status"] == "ISSUED"
        assert issued["payment_status"] == "UNPAID", (
            "the issuance dimension must not move the settlement dimension"
        )
        assert issued["gross_cents"] == 3_310_000   # 3_200_000 fee + 110_000 reimbursables
        assert issued["net_due_cents"] == 2_979_000  # gross - 10% of gross

    def test_payments_advance_the_settlement_dimension_while_the_status_stays_issued(self, api):
        """PRD §3.9: "When the new total is still short of `net_due_cents`, `payment_status` becomes
        `PARTIALLY_PAID` (from `UNPAID`) or stays `PARTIALLY_PAID` (when it was already there)."
        PRD §3.9: "When the new `amount_paid_cents` lands exactly on `net_due_cents`,
        `payment_status` becomes `PAID`, which is terminal — whether it arrives in one payment from
        `UNPAID` or as the last of several from `PARTIALLY_PAID`."
        PRD §3.9: "Recording payment never changes the issuance dimension: a fully paid invoice
        remains `ISSUED`."

        Design: Difficulty/non_linear_state_machine/invoice_status_and_payment_status_are_independent_dimensions
        """
        bundle = _setup_with_expense_and_draft_invoice("PAR-002")
        issued = issue_invoice(bundle["invoice_id"], bundle)
        assert issued["net_due_cents"] == 2_979_000

        partial = record_payment(bundle["invoice_id"], 1_000_000)
        assert_invoice(partial)
        assert partial["payment_status"] == "PARTIALLY_PAID"
        assert partial["status"] == "ISSUED"
        assert partial["amount_paid_cents"] == 1_000_000

        settled = record_payment(bundle["invoice_id"], 1_979_000)
        assert_invoice(settled)
        assert settled["amount_paid_cents"] == 2_979_000
        assert settled["payment_status"] == "PAID"
        assert settled["status"] == "ISSUED"


class TestInvoiceVoidConservesTheFeeLedger:

    def test_issue_moves_wip_into_billed_and_sweeps_the_expense(self, api):
        """PRD §3.9: "On success, `issued_at` is stamped from the logical clock and two cascades
        run: every expense on the project that is `APPROVED`, `reimbursable`, and not yet attached to
        an invoice moves to `BILLED` with its `invoice_id` set to this invoice; and the contract's
        `billed_fee_to_date_cents` rises by this invoice's `fee_billed_cents`, after which
        `wip_balance_cents` is recomputed and `Contract.version` increments."
        PRD §2.6: "The contract's `wip_balance_cents`, in particular, is never stored as an
        independent quantity — it is always the contract's `earned_to_date_cents` minus its
        `billed_fee_to_date_cents`, recomputed at every point either operand changes."

        Design: Difficulty/compensating_invariant/invoice_void_restores_wip_and_conserves_earned_fee_identity
        """
        bundle = _setup_with_expense_and_draft_invoice("INV-001")

        before = read_contract(bundle)
        assert before["earned_to_date_cents"] == 3_200_000
        assert before["billed_fee_to_date_cents"] == 0
        assert before["wip_balance_cents"] == 3_200_000

        issue_invoice(bundle["invoice_id"], bundle)

        after = read_contract(bundle)
        assert_contract(after)
        assert after["earned_to_date_cents"] == 3_200_000
        assert after["billed_fee_to_date_cents"] == 3_200_000
        assert after["wip_balance_cents"] == 0
        assert_contract_wip_identity(after)

        expense = read_expense(bundle, bundle["expense"]["id"])
        assert_expense(expense)
        assert expense["status"] == "BILLED"
        assert expense["invoice_id"] == bundle["invoice_id"]

    def test_void_returns_the_wip_and_the_expense_without_un_earning_the_fee(self, api):
        """PRD §3.9: "Voiding an `ISSUED` invoice runs the full compensating cascade:
        `billed_fee_to_date_cents` falls back by this invoice's `fee_billed_cents`,
        `wip_balance_cents` is recomputed, and `Contract.version` increments. The contract's
        `earned_to_date_cents` is emphatically **not** touched — voiding a bill does not un-earn the
        work."
        PRD §3.9: "Every expense whose `invoice_id` points at the voided invoice reverts from
        `BILLED` to `APPROVED` with its `invoice_id` cleared to null, returning to the unbilled pool
        for the next invoice."

        Design: Difficulty/compensating_invariant/invoice_void_restores_wip_and_conserves_earned_fee_identity
        """
        bundle = _setup_with_expense_and_draft_invoice("INV-002")
        issue_invoice(bundle["invoice_id"], bundle)

        voided = validate_success(
            api.set_invoice_state(bundle["invoice_id"], state_payload("VOID"), PRINCIPAL)
        )
        assert_invoice(voided)
        assert voided["status"] == "VOID"
        assert voided["fee_billed_cents"] == 3_200_000, "the frozen figures are not erased"

        contract = read_contract(bundle)
        assert contract["earned_to_date_cents"] == 3_200_000
        assert contract["billed_fee_to_date_cents"] == 0
        assert contract["wip_balance_cents"] == 3_200_000
        assert_contract_wip_identity(contract)

        expense = read_expense(bundle, bundle["expense"]["id"])
        assert expense["status"] == "APPROVED"
        assert expense["invoice_id"] is None


class TestIssuanceDependsOnTheProject:

    def test_issuing_on_a_suspended_project_is_rejected(self, api):
        """PRD §3.2: "What it does do is close the billing window — issuing an invoice on a project
        that is not `ACTIVE` is rejected with `ERR_PROJECT_NOT_ACTIVE`."
        PRD §3.9: "**Issuing.** A `ProjectManager` or `PrincipalArchitect` drives a `DRAFT` invoice
        to `ISSUED`, which is permitted only while the contract's project is `ACTIVE`
        (`ERR_PROJECT_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/invoice_issue_blocked_while_project_is_suspended
        """
        bundle = setup_executed_project(project_number="SUS-001", name="Suspended Spire",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")
        invoice = draft_invoice(bundle)
        assert invoice["fee_billed_cents"] == 2_000_000
        assert invoice["gross_cents"] == 2_000_000

        validate_success(
            api.set_project_state(bundle["project_id"], state_payload("SUSPENDED"), PRINCIPAL)
        )

        response = api.set_invoice_state(
            invoice["id"], state_payload("ISSUED"), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_NOT_ACTIVE.value)

    def test_the_blocked_issuance_leaves_the_billing_ledger_completely_untouched(self, api):
        """PRD §3.9: "Draft invoices contribute nothing to any ledger; neither do voided ones. Only
        issued invoices count."
        PRD §3.2: "Suspension is deliberately shallow: it does **not** cascade to the phases, whose
        statuses are left exactly as they were."

        Design: Difficulty/cross_entity_state_dependency/invoice_issue_blocked_while_project_is_suspended
        """
        bundle = setup_executed_project(project_number="SUS-003", name="Suspended Stack",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")
        invoice = draft_invoice(bundle)

        validate_success(
            api.set_project_state(bundle["project_id"], state_payload("SUSPENDED"), PRINCIPAL)
        )
        validate_error(
            api.set_invoice_state(invoice["id"], state_payload("ISSUED"), bundle["pm_headers"]),
            ApiErrorId.ERR_PROJECT_NOT_ACTIVE.value,
        )

        rows, _ = validate_paginated(
            api.list_contract_invoices(bundle["contract_id"], bundle["pm_headers"])
        )
        still = next(row for row in rows if row["id"] == invoice["id"])
        assert still["status"] == "DRAFT"
        assert still["issued_at"] is None

        contract = read_contract(bundle)
        assert contract["billed_fee_to_date_cents"] == 0
        assert contract["wip_balance_cents"] == 2_000_000
        # The shallow suspension left the phase alone.
        assert read_phase(bundle, "SD")["status"] == "COMPLETED"


class TestInvoiceFeeArithmetic:

    def test_a_second_invoice_bills_only_the_unbilled_delta(self, api):
        """PRD §3.9: "Either way, subtract the contract's `billed_fee_to_date_cents` from the figure
        to get `fee_billed_cents` — this invoice bills only what previous issued invoices did not."
        PRD §3.9: "Draft invoices contribute nothing to any ledger; neither do voided ones. Only
        issued invoices count."

        Design: Corner/calculations/invoice_fee_billed_only_counts_the_unbilled_delta_on_a_second_invoice
        """
        bundle = setup_executed_project(project_number="DLT-001", name="Delta Depot",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")

        first = draft_and_issue_invoice(bundle, period_end="2026-06-30T00:00:00Z")
        assert first["fee_billed_cents"] == 2_000_000
        assert first["net_due_cents"] == 1_800_000
        assert read_contract(bundle)["billed_fee_to_date_cents"] == 2_000_000

        activate_and_advance_phase(bundle, "DD", 50)  # DD earns 1_000_000

        second = draft_invoice(bundle, period_end="2026-07-31T00:00:00Z")
        assert_invoice(second)
        assert second["fee_billed_cents"] == 1_000_000, (
            "3_000_000 earned minus 2_000_000 already billed"
        )
        assert second["gross_cents"] == 1_000_000
        assert second["retainage_bp"] == 1000
        assert second["net_due_cents"] == 900_000

        contract = read_contract(bundle)
        assert contract["earned_to_date_cents"] == 3_000_000
        assert contract["wip_balance_cents"] == 1_000_000

    def test_invoice_totals_are_reconciled_against_current_state_at_issue(self, api):
        """PRD §3.9: "All seven numbers are recomputed from scratch against the state of the world
        at this moment — phases may have progressed and expenses may have been approved since the
        draft was cut — and only then are they frozen."
        PRD §3.9: "**Third**, `gross_cents` is `fee_billed_cents` plus `reimbursable_cents`."

        Design: Corner/cross_cutting_complexity_layers/invoice_totals_are_reconciled_against_current_state_at_issue
        """
        bundle = setup_executed_project(project_number="RCN-001", name="Reconcile Ranch",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")

        draft = draft_invoice(bundle)
        assert draft["fee_billed_cents"] == 2_000_000
        assert draft["gross_cents"] == 2_000_000

        # The world moves on before the bill goes out.
        activate_and_advance_phase(bundle, "DD", 50)

        issued = issue_invoice(draft["id"], bundle)
        assert_invoice(issued)
        assert issued["fee_billed_cents"] == 3_000_000, "re-derived at issuance, not frozen at draft"
        assert issued["gross_cents"] == 3_000_000
        assert issued["retainage_bp"] == 1000
        assert issued["retainage_cents"] == 300_000
        assert issued["net_due_cents"] == 2_700_000

        contract = read_contract(bundle)
        assert contract["billed_fee_to_date_cents"] == 3_000_000
        assert contract["earned_to_date_cents"] == 3_000_000
        assert contract["wip_balance_cents"] == 0


class TestInvoiceMoneyGates:

    def test_drafting_with_no_phase_at_the_billing_threshold_is_rejected(self, api):
        """PRD §3.9: "**First, the fee portion.** On a `PERCENT_OF_CONSTRUCTION` contract, gather
        the project's phases that are marked `is_billing_milestone` **and** whose `percent_complete`
        has reached **at least 50** — exactly 50 qualifies; 49 does not. Sum their `earned_cents`.
        If no phase qualifies, the invoice is rejected outright with
        `ERR_BILLING_THRESHOLD_NOT_MET`."

        Design: Corner/validations/invoice_draft_with_no_phase_over_billing_threshold_is_rejected
        """
        bundle = setup_executed_project(
            project_number="THR-001", name="Threshold Theatre",
            weights=(2500, 2500, 2500, 2500), with_architect=False,
        )
        activate_and_advance_phase(bundle, "SD", 40)  # below the 50-percent threshold

        version = get_contract_version(bundle)
        response = api.create_invoice(
            create_invoice_payload(bundle["contract_id"], version), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_BILLING_THRESHOLD_NOT_MET.value)

        rows, _ = validate_paginated(
            api.list_contract_invoices(bundle["contract_id"], bundle["pm_headers"])
        )
        assert len(rows) == 0

        # The earned value exists; it is simply not yet billable.
        assert read_phase(bundle, "SD")["earned_cents"] == 1_000_000
        assert read_contract(bundle)["earned_to_date_cents"] == 1_000_000

    def test_drafting_a_zero_gross_invoice_on_an_hourly_contract_is_rejected(self, api):
        """PRD §3.9: "**Third**, `gross_cents` is `fee_billed_cents` plus `reimbursable_cents`. An
        invoice whose `gross_cents` computes to 0 is rejected with `ERR_ZERO_INVOICE_AMOUNT` — a
        rejection applied both at drafting and again at issuance."
        PRD §3.9: "On an `HOURLY` contract, no threshold applies and the figure is simply the
        contract's `earned_to_date_cents`, already capped at the not-to-exceed ceiling."

        Design: Corner/validations/invoice_draft_with_zero_gross_on_hourly_contract_is_rejected
        """
        bundle = setup_executed_project(
            project_number="ZRO-001", name="Zero Zone",
            weights=(2500, 2500, 2500, 2500), hourly_not_to_exceed_cents=200_000,
            with_architect=False,
        )

        version = get_contract_version(bundle)
        response = api.create_invoice(
            create_invoice_payload(bundle["contract_id"], version), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_ZERO_INVOICE_AMOUNT.value)

        contract = read_contract(bundle)
        assert contract["earned_to_date_cents"] == 0
        assert contract["wip_balance_cents"] == 0

        rows, _ = validate_paginated(
            api.list_contract_invoices(bundle["contract_id"], bundle["pm_headers"])
        )
        assert len(rows) == 0

    def test_overpayment_is_refused_and_a_paid_invoice_may_not_be_voided(self, api):
        """PRD §3.9: "If the resulting total would exceed `net_due_cents`, the payment is rejected
        with `ERR_OVERPAYMENT`; the client may not overpay, not even by a cent."
        PRD §3.9: "An issued invoice may only be voided while its `payment_status` is still
        `UNPAID`; once money has arrived, the void is rejected with `ERR_INVOICE_ALREADY_PAID`."

        Design: Corner/validations/payment_exceeding_net_due_is_rejected_and_full_payment_blocks_void
        """
        bundle = setup_executed_project(
            project_number="PAY-001", name="Payment Park",
            weights=DD_HEAVY_WEIGHTS, with_architect=False,
        )
        activate_and_complete_phase(bundle, "SD")
        invoice = draft_and_issue_invoice(bundle)
        assert invoice["net_due_cents"] == 1_800_000  # gross 2_000_000 less 10 percent

        over = api.record_payment(invoice["id"], {"amount_cents": 1_800_001}, PRINCIPAL)
        validate_error(over, ApiErrorId.ERR_OVERPAYMENT.value)

        rows, _ = validate_paginated(
            api.list_contract_invoices(bundle["contract_id"], bundle["pm_headers"])
        )
        unpaid = next(row for row in rows if row["id"] == invoice["id"])
        assert unpaid["amount_paid_cents"] == 0

        paid = validate_success(
            api.record_payment(invoice["id"], {"amount_cents": 1_800_000}, PRINCIPAL)
        )
        assert paid["payment_status"] == "PAID"
        assert paid["status"] == "ISSUED"

        void = api.set_invoice_state(invoice["id"], state_payload("VOID"), PRINCIPAL)
        validate_error(void, ApiErrorId.ERR_INVOICE_ALREADY_PAID.value)

        rows, _ = validate_paginated(
            api.list_contract_invoices(bundle["contract_id"], bundle["pm_headers"])
        )
        still = next(row for row in rows if row["id"] == invoice["id"])
        assert still["status"] == "ISSUED"

        contract = read_contract(bundle)
        assert contract["billed_fee_to_date_cents"] == 2_000_000
        assert contract["wip_balance_cents"] == 0


class TestInvoiceDraftConcurrency:

    def test_a_second_draft_carrying_a_stale_contract_version_is_rejected(self, api):
        """PRD §2.5: "Drafting an invoice requires a non-optional `expected_contract_version` field
        in the request body, carrying the `version` of the target `Contract` as the client last
        observed it."
        PRD §2.5: "If `expected_contract_version` does not equal the contract's current `version`,
        the request is rejected with `ERR_STALE_CONTRACT_VERSION` and HTTP status 412."

        Design: Corner/cross_cutting_complexity_layers/second_invoice_draft_with_stale_contract_version_returns_412
        """
        bundle = setup_executed_project(project_number="OCC-001", name="OCC Outpost",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")

        observed_version = get_contract_version(bundle)
        first = validate_success(
            api.create_invoice(
                create_invoice_payload(bundle["contract_id"], observed_version,
                                       period_end="2026-06-30T00:00:00Z"),
                bundle["pm_headers"],
            ),
            201,
        )
        assert first["fee_billed_cents"] == 2_000_000

        # Drafting bumped Contract.version, so the version we still hold is stale.
        stale = api.create_invoice(
            create_invoice_payload(bundle["contract_id"], observed_version,
                                   period_end="2026-07-31T00:00:00Z"),
            bundle["pm_headers"],
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)

        rows, _ = validate_paginated(
            api.list_contract_invoices(bundle["contract_id"], bundle["pm_headers"])
        )
        assert len(rows) == 1, "the stale draft must not have been written"

        fresh_version = get_contract_version(bundle)
        validate_success(
            api.create_invoice(
                create_invoice_payload(bundle["contract_id"], fresh_version,
                                       period_end="2026-07-31T00:00:00Z"),
                bundle["pm_headers"],
            ),
            201,
        )
        rows, _ = validate_paginated(
            api.list_contract_invoices(bundle["contract_id"], bundle["pm_headers"])
        )
        assert len(rows) == 2
