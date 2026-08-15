"""Invoices and withholding: branch divergence, fee-only withholding order,
validation ordering pairs, claim reconciliation, the reject compensation,
tax-document expiry, and finance segregation of duties."""
from test_helpers import (
    ApiErrorId,
    accept_for_publication,
    add_rate_agreement,
    approve_invoice,
    assert_invoice_money_invariants,
    bootstrap_desk,
    clear_all_reports,
    create_assignment,
    create_contributor,
    create_verified_tax_document,
    get_assignment,
    get_invoice,
    get_success_data,
    kill_assignment,
    list_reports,
    make_contributor_headers,
    make_finance_headers,
    record_result,
    set_clock,
    setup_accepted_assignment,
    setup_accepted_with_reimbursable_expense,
    setup_assignment_in_state,
    setup_contributor_with_agreement,
    setup_verified_invoice,
    submit_invoice,
    validate_error,
    validate_success,
    verify_invoice,
    walk_assignment,
)
from test_helpers import api_client as _api
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]


class TestWithholdingBranchDivergence:

    def test_domestic_backup_withholding_branch(self, api):
        """PRD section 3.8: "For a `DOMESTIC_US` contributor, if
        `backup_withholding_flag` is true or no such valid document exists,
        the rate is the desk's `backup_withholding_rate_bps` (default 2400,
        i.e. 24%); otherwise the rate is zero."
        PRD section 3.8: "The withheld amount is the fee multiplied by the
        rate in basis points and divided by 10000, floor-divided."

        Design: Difficulty/dual_variant_calc/withholding_branch_divergence_on_invoice
        """
        ctx = setup_verified_invoice(
            legal_name="Dom Backup", email="dom@x.com",
            backup_withholding_flag=True, with_verified_tax_doc=False,
            pricing_mode="FLAT", flat_fee_cents=105000)
        invoice = ctx["invoice"]
        assert invoice["fee_claim_cents"] == 105000
        assert invoice["withholding_cents"] == 25200, (
            "floor(105000 * 2400 / 10000)")
        assert invoice["gross_cents"] == 105000
        assert invoice["net_payable_cents"] == 79800
        assert_invoice_money_invariants(invoice)

    def test_foreign_treaty_withholding_branch(self, api):
        """PRD section 3.8: "For a `FOREIGN` contributor with no valid
        document, the rate is the desk's `foreign_statutory_rate_bps`
        (default 3000, i.e. 30%); with a valid `W8BEN`, the rate is looked up
        in the desk's `treaty_rates_bps` table keyed by `treaty_country`
        (defaults: `GB` 0, `DE` 0, `JP` 1000, `IN` 1500, `BR` 1500), and a
        country absent from the table falls back to the statutory rate."
        PRD section 3.8: "The withheld amount is the fee multiplied by the
        rate in basis points and divided by 10000, floor-divided."

        Design: Difficulty/dual_variant_calc/withholding_branch_divergence_on_invoice
        """
        ctx = setup_verified_invoice(
            legal_name="Foreign JP", email="jp@x.com",
            tax_residency="FOREIGN", treaty_country="JP",
            pricing_mode="FLAT", flat_fee_cents=105000)
        invoice = ctx["invoice"]
        assert invoice["fee_claim_cents"] == 105000
        # Treaty JP (1000 bps) on the identical fee diverges from the
        # domestic-backup branch (25200) purely by tax branch selection.
        assert invoice["withholding_cents"] == 10500, (
            "floor(105000 * 1000 / 10000); != 25200 domestic-backup outcome")
        assert invoice["net_payable_cents"] == 94500
        assert_invoice_money_invariants(invoice)


class TestFeeOnlyWithholdingOrder:

    def _setup_jp_invoice_with_expense(self, api):
        ctx, claim = setup_accepted_with_reimbursable_expense(
            legal_name="JP Writer", email="jpw@x.com",
            tax_residency="FOREIGN", pricing_mode="FLAT",
            flat_fee_cents=105000, category="TRAVEL", requested_cents=3200,
            claimed_cents=3200, receipt_attached=True)
        assert claim["reimbursable_cents"] == 3200
        create_verified_tax_document(ctx["contributor"]["id"],
                                     doc_kind="W8BEN", treaty_country="JP",
                                     tin_last4="9999")
        invoice = submit_invoice(ctx["assignment"]["id"],
                                 ctx["contributor"]["id"],
                                 105000, 3200)
        return ctx, invoice

    def test_withholding_computed_from_fee_portion_only(self, api):
        """PRD section 3.8: "`withholding_cents` comes from the
        `withholding_computation` rule, which applies to the fee portion only
        — expenses are never withheld."
        PRD section 3.8: "The evaluation order is pinned to resolve the
        circular-looking dependency: gross is computed first from fee plus
        expenses, withholding second from the fee alone (never from gross —
        that is the classic bug this pins against), net third as gross minus
        withholding."

        Design: Difficulty/combinatorial_formula/waterfall_fee_only_withholding_mode_c
        """
        _ctx, invoice = self._setup_jp_invoice_with_expense(api)
        verified = verify_invoice(invoice["id"], "VERIFY")
        assert verified["gross_cents"] == 108200, "105000 fee + 3200 expense"
        assert verified["withholding_cents"] == 10500, (
            "10% of fee 105000, not 10% of gross 108200")
        assert verified["net_payable_cents"] == 97700
        assert_invoice_money_invariants(verified)

    def test_net_allocation_and_terms_after_verify(self, api):
        """PRD section 3.8: "`gross_cents` is the integer sum of
        `fee_claim_cents` and `expense_claim_cents`, no rounding." and
        "`net_payable_cents` is `gross_cents` minus `withholding_cents`, per
        the `net_payable_allocation` rule."
        PRD section 3.8: "The new invoice starts at `SUBMITTED`, with
        `payment_terms_days` copied from the desk's `net_terms_days` (default
        30) and `late_fee_cents` at 0." and "`due_date_utc` is set to now
        plus `payment_terms_days`."

        Design: Difficulty/combinatorial_formula/waterfall_fee_only_withholding_mode_c
        """
        _ctx, invoice = self._setup_jp_invoice_with_expense(api)
        assert invoice["status"] == "SUBMITTED"
        assert invoice["payment_terms_days"] == 30
        assert invoice["late_fee_cents"] == 0

        verified = verify_invoice(invoice["id"], "VERIFY")
        assert verified["withholding_cents"] != 10820, (
            "withholding on gross (the pinned-against bug) would be 10820")
        assert verified["net_payable_cents"] == (
            verified["gross_cents"] - verified["withholding_cents"])
        # Verified at the startup clock 2026-08-01T00:00:00Z + 30 days.
        assert verified["due_date_utc"].startswith("2026-08-31T00:00:00")


class TestStateVsGateOrderingOnInvoiceCreate:

    def test_invoice_create_on_in_progress_assignment(self, api):
        """PRD section 3.8: "The assignment must be in
        `ACCEPTED_FOR_PUBLICATION` or `KILLED`, and the verification gate
        must be open: either `verification_cleared` is true, or the
        assignment is `KILLED` with no report in `PENDING` or `FLAGGED`;
        otherwise the submission is rejected with
        `ERR_VERIFICATION_NOT_CLEARED`."
        PRD section 3.11: "Authentication comes first (missing or malformed
        headers yield `ERR_UNAUTHENTICATED`), then role authorization
        (`ERR_FORBIDDEN_ROLE`), then path existence left-to-right
        (`ERR_NOT_FOUND`), then state-machine legality including
        terminal-state lockdown (`ERR_INVALID_STATE`)."
        PRD section 3.11: "Business-safety gates follow: the verification
        gate (`ERR_VERIFICATION_NOT_CLEARED`) on invoice submission and
        invoice verification, then the three segregation-of-duties pairs
        (`ERR_SEGREGATION_OF_DUTIES`) on invoice approval, batch release,
        and report adjudication."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_invoice_create
        """
        _contributor, _agr, assignment = setup_assignment_in_state(
            "IN_PROGRESS", legal_name="Dual Dana", email="dana@x.com")
        contributor_id = assignment["contributor_id"]
        resp = api.create_invoice(
            assignment["id"],
            {"fee_claim_cents": 50000, "expense_claim_cents": 0},
            make_contributor_headers(contributor_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        invoices = get_success_data(
            api.list_assignment_invoices(assignment["id"], EDITOR))
        assert invoices == [], "no invoice persisted for the rejected call"

    def test_invoice_create_on_draft_assignment(self, api):
        """PRD section 3.8: "The assignment must be in
        `ACCEPTED_FOR_PUBLICATION` or `KILLED`, and the verification gate
        must be open: either `verification_cleared` is true, or the
        assignment is `KILLED` with no report in `PENDING` or `FLAGGED`;
        otherwise the submission is rejected with
        `ERR_VERIFICATION_NOT_CLEARED`."
        PRD section 3.11: "Authentication comes first (missing or malformed
        headers yield `ERR_UNAUTHENTICATED`), then role authorization
        (`ERR_FORBIDDEN_ROLE`), then path existence left-to-right
        (`ERR_NOT_FOUND`), then state-machine legality including
        terminal-state lockdown (`ERR_INVALID_STATE`)."
        PRD section 3.11: "Business-safety gates follow: the verification
        gate (`ERR_VERIFICATION_NOT_CLEARED`) on invoice submission and
        invoice verification, then the three segregation-of-duties pairs
        (`ERR_SEGREGATION_OF_DUTIES`) on invoice approval, batch release,
        and report adjudication."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_invoice_create
        """
        contributor, _agr = setup_contributor_with_agreement(
            legal_name="Draft Dora", email="dora@x.com")
        assignment = create_assignment(contributor["id"], title="DS")
        resp = api.create_invoice(
            assignment["id"],
            {"fee_claim_cents": 50000, "expense_claim_cents": 0},
            make_contributor_headers(contributor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert (get_assignment(assignment["id"])["payment_status"]
                == "UNINVOICED")


class TestTaxDocKindMatching:

    def test_w8ben_without_treaty_country_rejected(self, api):
        """PRD section 3.8: "The kind must match the contributor's
        `tax_residency`: `W9` pairs with `DOMESTIC_US`, `W8BEN` with
        `FOREIGN`; a mismatch, or a `W8BEN` without a `treaty_country`, is
        rejected with `ERR_TAX_DOC_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_invoice_approve
        """
        bootstrap_desk()
        contributor = create_contributor(legal_name="Gap Greg",
                                         email="greg@x.com",
                                         tax_residency="FOREIGN")
        resp = api.create_tax_document(
            contributor["id"], {"doc_kind": "W8BEN", "tin_last4": "7777"},
            make_contributor_headers(contributor["id"]))
        validate_error(resp, ApiErrorId.ERR_TAX_DOC_MISMATCH, 422)
        docs = get_success_data(
            api.list_tax_documents(contributor["id"], ADMIN))
        assert docs == [], "no TaxDocument persisted"

    def test_w9_for_foreign_contributor_rejected(self, api):
        """PRD section 3.8: "The kind must match the contributor's
        `tax_residency`: `W9` pairs with `DOMESTIC_US`, `W8BEN` with
        `FOREIGN`; a mismatch, or a `W8BEN` without a `treaty_country`, is
        rejected with `ERR_TAX_DOC_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_invoice_approve
        """
        bootstrap_desk()
        contributor = create_contributor(legal_name="Kind Kim",
                                         email="kim@x.com",
                                         tax_residency="FOREIGN")
        resp = api.create_tax_document(
            contributor["id"], {"doc_kind": "W9", "tin_last4": "7777"},
            make_contributor_headers(contributor["id"]))
        validate_error(resp, ApiErrorId.ERR_TAX_DOC_MISMATCH, 422)


class TestInvoiceRejectCompensation:

    def test_reject_restores_uninvoiced_and_keeps_fee(self, api):
        """PRD section 3.8: "A `decision` of `REJECT` instead moves the
        invoice to `REJECTED` and compensates the payment dimension back from
        `INVOICED` to `UNINVOICED`, so the contributor may submit a fresh
        invoice."

        Design: Difficulty/compensating_invariant/invoice_reject_payment_status_invariant
        """
        contributor, _agr, accepted = setup_accepted_assignment(
            legal_name="Reject Rena", email="rena@x.com",
            pricing_mode="FLAT", flat_fee_cents=50000)
        assert accepted["final_fee_cents"] == 50000
        invoice = submit_invoice(accepted["id"], contributor["id"], 50000, 0)
        assert (get_assignment(accepted["id"])["payment_status"]
                == "INVOICED")

        rejected = verify_invoice(invoice["id"], "REJECT")
        assert rejected["status"] == "REJECTED"
        assignment_after = get_assignment(accepted["id"])
        assert assignment_after["payment_status"] == "UNINVOICED", (
            "round trip restores the pre-submission payment posture")
        assert assignment_after["final_fee_cents"] == 50000

    def test_fresh_invoice_accepted_after_reject(self, api):
        """PRD section 3.8: "A `decision` of `REJECT` instead moves the
        invoice to `REJECTED` and compensates the payment dimension back from
        `INVOICED` to `UNINVOICED`, so the contributor may submit a fresh
        invoice."
        PRD section 3.8: "The submission sets `submitted_by_contributor_id`
        from `X-User-ID` and moves `payment_status` from `UNINVOICED` to
        `INVOICED`."

        Design: Difficulty/compensating_invariant/invoice_reject_payment_status_invariant
        """
        contributor, _agr, accepted = setup_accepted_assignment(
            legal_name="Reject Rena", email="rena@x.com",
            pricing_mode="FLAT", flat_fee_cents=50000)
        first = submit_invoice(accepted["id"], contributor["id"], 50000, 0)
        verify_invoice(first["id"], "REJECT")

        resp = api.create_invoice(
            accepted["id"],
            {"fee_claim_cents": 50000, "expense_claim_cents": 0},
            make_contributor_headers(contributor["id"]))
        fresh = validate_success(resp, 201)
        assert fresh["status"] == "SUBMITTED"
        assert fresh["id"] != first["id"]
        assert (get_assignment(accepted["id"])["payment_status"]
                == "INVOICED")


def test_flagged_report_blocks_invoice_submission(api):
    """PRD section 3.5: "Clearing recomputes the assignment's
    `verification_cleared` (true exactly when every report of the assignment
    is `CLEARED` or `DISMISSED`); flagging closes the payment gate, blocking
    invoice submission while any report is `PENDING` or `FLAGGED` with
    `ERR_VERIFICATION_NOT_CLEARED`."
    PRD section 3.8: "The assignment must be in `ACCEPTED_FOR_PUBLICATION` or
    `KILLED`, and the verification gate must be open: either
    `verification_cleared` is true, or the assignment is `KILLED` with no
    report in `PENDING` or `FLAGGED`; otherwise the submission is rejected
    with `ERR_VERIFICATION_NOT_CLEARED`."

    Design: Corner/validations/verification_gate_blocks_invoice_submission
    """
    _contributor, _agr, assignment = setup_assignment_in_state(
        "UNDER_VERIFICATION", legal_name="Gate Gina", email="gina@x.com",
        pricing_mode="FLAT", flat_fee_cents=50000)
    contributor_id = assignment["contributor_id"]
    plag = list_reports(assignment["id"])[0]
    record_result(plag["id"], 4000, 0, user_id="ve-1")
    killed = kill_assignment(assignment["id"])
    assert killed["editorial_status"] == "KILLED"
    assert killed["final_fee_cents"] == 25000, "POST_DELIVERY 50% of 50000"

    resp = api.create_invoice(
        assignment["id"],
        {"fee_claim_cents": 25000, "expense_claim_cents": 0},
        make_contributor_headers(contributor_id))
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_NOT_CLEARED, 409)
    assert (get_assignment(assignment["id"])["payment_status"]
            == "UNINVOICED")


def test_invoice_approve_requires_verified_tax_document(api):
    """PRD section 3.8: "Approval — a second `FinanceUser` distinct from the
    verifier, enforced as `ERR_SEGREGATION_OF_DUTIES` — requires the
    contributor to hold at least one `VERIFIED`, unexpired tax document at
    approval time; its absence is rejected with `ERR_TAX_DOC_MISSING`."
    PRD section 3.8: "For a `DOMESTIC_US` contributor, if
    `backup_withholding_flag` is true or no such valid document exists, the
    rate is the desk's `backup_withholding_rate_bps` (default 2400, i.e.
    24%); otherwise the rate is zero."

    Design: Corner/validations/invoice_approve_requires_tax_doc
    """
    ctx = setup_verified_invoice(legal_name="NoDoc Ned", email="ned@x.com",
                                 with_verified_tax_doc=False,
                                 pricing_mode="FLAT", flat_fee_cents=50000)
    invoice = ctx["invoice"]
    assert invoice["status"] == "VERIFIED"
    assert invoice["withholding_cents"] == 12000, (
        "24% backup withholding applied at verify despite missing doc")

    resp = api.approve_invoice(invoice["id"], make_finance_headers("fin-2"))
    validate_error(resp, ApiErrorId.ERR_TAX_DOC_MISSING, 422)
    assert get_invoice(invoice["id"])["status"] == "VERIFIED"


def test_invoice_verifier_cannot_approve_same_invoice(api):
    """PRD section 2.8: "The `FinanceUser` who verifies an invoice may not
    approve it."
    PRD section 3.8: "Approval moves the invoice to `APPROVED` and cascades
    the assignment's `payment_status` from `INVOICED` to `PAYABLE`."

    Design: Corner/validations/sod_invoice_verify_then_approve_same_user
    """
    ctx = setup_verified_invoice(legal_name="Sod Sue", email="sue@x.com",
                                 pricing_mode="FLAT", flat_fee_cents=50000)
    invoice = ctx["invoice"]

    resp = api.approve_invoice(invoice["id"], make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    assert get_invoice(invoice["id"])["status"] == "VERIFIED"

    approved = validate_success(
        api.approve_invoice(invoice["id"], make_finance_headers("fin-2")))
    assert approved["status"] == "APPROVED"
    assert (get_assignment(ctx["assignment"]["id"])["payment_status"]
            == "PAYABLE")


def test_fee_claim_mismatch_rejected_at_verify(api):
    """PRD section 3.8: "The claim-reconciliation rule compares
    `fee_claim_cents` to the assignment's `final_fee_cents` — plus
    `buyout_uplift_cents` when rights are `ALL` — and `expense_claim_cents`
    to the sum of `reimbursable_cents` across the assignment's `REIMBURSABLE`
    expense claims; any disagreement is rejected with `ERR_CLAIM_MISMATCH`."

    Design: Corner/validations/claim_mismatch_fee_amount
    """
    contributor, _agr, accepted = setup_accepted_assignment(
        legal_name="Mismatch Mike", email="mike@x.com", pricing_mode="FLAT",
        flat_fee_cents=50000)
    assert accepted["final_fee_cents"] == 50000
    invoice = submit_invoice(accepted["id"], contributor["id"], 49000, 0)

    resp = api.verify_invoice(invoice["id"], {"decision": "VERIFY"},
                              make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_CLAIM_MISMATCH, 422)
    assert get_invoice(invoice["id"])["status"] == "SUBMITTED"


def test_expired_tax_document_forces_statutory_withholding(api):
    """PRD section 2.5: "Advancing the clock triggers a sweep: every
    `TaxDocument` whose `status` is `VERIFIED` and whose `expires_at` is
    earlier than the new now transitions to `EXPIRED`, and subsequent
    withholding computations for that contributor resolve to the punitive
    branch."
    PRD section 3.8: "For a `FOREIGN` contributor with no valid document, the
    rate is the desk's `foreign_statutory_rate_bps` (default 3000, i.e.
    30%); with a valid `W8BEN`, the rate is looked up in the desk's
    `treaty_rates_bps` table keyed by `treaty_country` (defaults: `GB` 0,
    `DE` 0, `JP` 1000, `IN` 1500, `BR` 1500), and a country absent from the
    table falls back to the statutory rate."

    Design: Corner/state_machines/tax_document_expiry_sweep
    """
    bootstrap_desk()
    contributor = create_contributor(legal_name="Expiry Eli",
                                     email="eli@x.com", tax_residency="FOREIGN")
    add_rate_agreement(contributor, pricing_mode="FLAT",
                       flat_fee_cents=100000)
    doc = create_verified_tax_document(contributor["id"], doc_kind="W8BEN",
                                       treaty_country="JP", tin_last4="6666")
    assignment = create_assignment(contributor["id"], title="ES")
    walk_assignment(assignment["id"], contributor["id"],
                    "UNDER_VERIFICATION")
    clear_all_reports(assignment["id"])
    accept_for_publication(assignment["id"], 100)
    invoice = submit_invoice(assignment["id"], contributor["id"], 100000, 0)

    # submitted at 2026-08-01 + 1095 days expires 2029-07-27; jump past it.
    set_clock("2029-08-01T00:00:00Z")
    doc_after = get_success_data(api.get_tax_document(doc["id"], ADMIN))
    assert doc_after["status"] == "EXPIRED", "clock sweep flips VERIFIED"

    verified = verify_invoice(invoice["id"], "VERIFY")
    assert verified["withholding_cents"] == 30000, (
        "treaty document expired, so the punitive 30% statutory rate "
        "applies instead of JP 10%")
    assert_invoice_money_invariants(verified)
