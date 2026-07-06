"""Engagement parallel state dimensions, exception cycle, billing cascade, phase
ordering/weights, validation-priority conflicts, and scope-accept consistency/OCC.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success, validate_error
from test_helpers import (
    api_client, ApiErrorId,
    make_engagement_manager_headers,
    make_bookkeeper_headers,
    make_reviewer_headers,
    make_tax_preparer_headers,
)
from test_helpers import fixtures as fx

EM = make_engagement_manager_headers("em-1")
BK = make_bookkeeper_headers("bk-1")
RV = make_reviewer_headers("reviewer-1")
RV2 = make_reviewer_headers("reviewer-2")
TP = make_tax_preparer_headers("tp-1")


def test_quote_advances_billing_dimension_only(api):
    """PRD 3.1: "The engagement carries two independent state dimensions that progress
    in parallel." PRD 3.7: "Once scope is locked, the `EngagementManager` requests a
    quote, which computes the engagement's fixed price and moves `billing_status` from
    `UNBILLED` to `QUOTED`."

    Design: Difficulty/non_linear_state_machine/engagement_parallel_workflow_billing_dimensions
    """
    eng = fx.setup_reconstruction_engagement()
    data = validate_success(api.quote(eng["id"], EM))
    assert data["billing_status"] == "QUOTED"
    assert data["workflow_status"] == "RECONSTRUCTION"


def test_workflow_status_unchanged_by_quote(api):
    """PRD 3.1: "The lifecycle dimension, `workflow_status`, runs `DRAFT` → `SCOPING` →
    `RECONSTRUCTION` → `RECONCILIATION` → `TAX_HANDOFF` → `COMPLETED` ... The billing
    dimension, `billing_status`, runs `UNBILLED` → `QUOTED` → `PHASED` → `SETTLED`. The
    two tracks advance through separate operations described below."

    Design: Difficulty/non_linear_state_machine/engagement_parallel_workflow_billing_dimensions
    """
    eng = fx.setup_reconstruction_engagement()
    assert eng["workflow_status"] == "RECONSTRUCTION"
    get_success_data(api.quote(eng["id"], EM))
    after = validate_success(api.get_engagement(eng["id"], EM))
    assert after["workflow_status"] == "RECONSTRUCTION"
    assert after["billing_status"] == "QUOTED"


def test_exception_cycle_open_waiting_open(api):
    """PRD 3.6: "A `Bookkeeper` may request documents on a `MISSING_DOC` exception,
    moving it from `OPEN` to `WAITING_DOCS` ... When the documents arrive, the
    `Bookkeeper` records receipt, moving the exception back from `WAITING_DOCS` to
    `OPEN`."

    Design: Difficulty/non_linear_state_machine/exception_cycle_open_waiting_open
    """
    eng, acct, exc = fx.setup_missing_doc_exception_open()
    get_success_data(api.request_docs(eng["id"], exc["id"], BK))
    data = validate_success(api.docs_received(eng["id"], exc["id"], BK))
    assert data["status"] == "OPEN"


def test_exception_request_docs_moves_to_waiting(api):
    """PRD 3.6: "A `Bookkeeper` may request documents on a `MISSING_DOC` exception,
    moving it from `OPEN` to `WAITING_DOCS` — this transition is allowed only for the
    `MISSING_DOC` kind"

    Design: Difficulty/non_linear_state_machine/exception_cycle_open_waiting_open
    """
    eng, acct, exc = fx.setup_missing_doc_exception_open()
    data = validate_success(api.request_docs(eng["id"], exc["id"], BK))
    assert data["status"] == "WAITING_DOCS"


def test_pay_invoice_cascades_phase_billing_settled(api):
    """PRD 3.7: "The manager records payment on an invoice, which sets the invoice's
    `status` to `PAID` and advances its phase from `INVOICED` to `PAID`. When the last
    phase becomes `PAID` — that is, once every phase on the engagement is `PAID` — the
    engagement's `billing_status` bubbles up automatically from `PHASED` to `SETTLED`."

    Design: Difficulty/transitive_cascade/pay_invoice_cascades_phase_billing_settled
    """
    eng, phase, invoice = fx.setup_single_phase_invoiced()
    inv_after = validate_success(api.pay_invoice(eng["id"], invoice["id"], EM))
    assert inv_after["status"] == "PAID"
    phases = validate_success(api.list_phases(eng["id"], EM))
    assert phases[0]["status"] == "PAID"
    eng_after = validate_success(api.get_engagement(eng["id"], EM))
    assert eng_after["billing_status"] == "SETTLED"


def test_pay_invoice_advances_phase_to_paid(api):
    """PRD 3.7: "The manager records payment on an invoice, which sets the invoice's
    `status` to `PAID` and advances its phase from `INVOICED` to `PAID`."

    Design: Difficulty/transitive_cascade/pay_invoice_cascades_phase_billing_settled
    """
    eng, phase, invoice = fx.setup_single_phase_invoiced()
    validate_success(api.pay_invoice(eng["id"], invoice["id"], EM))
    phases = validate_success(api.list_phases(eng["id"], EM))
    assert phases[0]["status"] == "PAID"


def test_tax_build_blocking_exception_beats_recon_balance(api):
    """PRD 3.8: "Two preconditions gate the build, and they are evaluated with the
    blocking-exception check ahead of the balance check: first, the engagement must
    have no open blocking exceptions — `open_blocking_exception_count` must be zero, or
    the build is rejected with `ERR_BLOCKING_EXCEPTIONS_OPEN`; then, the engagement's
    `recon_status` must be `IN_BALANCE`, or the build is rejected with
    `ERR_RECON_NOT_IN_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/tax_build_blocking_exception_beats_recon_balance
    """
    # RECONCILIATION engagement with a non-bank account never reconciled (recon_status
    # PENDING via no reconciled bank, but here account is non-bank so recon_status is
    # IN_BALANCE vacuously); to force not-IN_BALANCE we open a BLOCKING UNRECONCILED_DIFF
    # path. Simpler: open one OPEN BLOCKING exception; the blocking check must fire first.
    eng, acct, entry = fx.setup_reconciliation_with_categorized_account()
    fx.add_exception(eng["id"], acct["id"], "UNCATEGORIZED", severity="BLOCKING")
    validate_error(api.build_tax_package(eng["id"], TP),
                   ApiErrorId.ERR_BLOCKING_EXCEPTIONS_OPEN.value)


def test_reverse_entry_settled_beats_account_reconciled(api):
    """PRD 3.3: "A posted entry may be reversed ... provided it has not been
    cash-settled — a reversal of an entry whose `cash_settled` is true is rejected with
    `ERR_ENTRY_SETTLED` — and provided its account is not already `RECONCILED`, which is
    rejected with `ERR_ACCOUNT_RECONCILED`."

    Design: Difficulty/priority_pair_validation_conflict/reverse_entry_settled_beats_account_reconciled
    """
    # Bank account reconciled via a finalized statement; its entry is cash_settled and
    # the account is RECONCILED. cash_settled is checked before account-reconciled.
    eng, bank, entry, stmt = fx.setup_bank_account_reconciled(book_amount=340000)
    validate_error(api.reverse_entry(eng["id"], entry["id"], BK),
                   ApiErrorId.ERR_ENTRY_SETTLED.value)


def test_tax_build_blocking_exception_fires_before_balance_check(api):
    """PRD 3.8: "Two preconditions gate the build, and they are evaluated with the
    blocking-exception check ahead of the balance check: first, the engagement must
    have no open blocking exceptions — `open_blocking_exception_count` must be zero, or
    the build is rejected with `ERR_BLOCKING_EXCEPTIONS_OPEN`"

    Design: Difficulty/priority_pair_validation_conflict/tax_build_blocking_exception_beats_recon_balance
    """
    # Bank account never reconciled -> recon_status PENDING (not IN_BALANCE) AND a
    # BLOCKING exception open. Per PRD the blocking check is reported first.
    eng = fx.setup_reconstruction_engagement()
    bank = fx.add_account(eng["id"], account_code="1010", name="Checking",
                          account_type="ASSET", is_bank_account=True)
    fx.add_posted_entry(eng["id"], bank["id"], side="DEBIT", amount_cents=1000)
    get_success_data(api.categorize_account(eng["id"], bank["id"], BK))
    get_success_data(api.advance_to_reconciliation(eng["id"], EM))
    fx.add_exception(eng["id"], bank["id"], "UNCATEGORIZED", severity="BLOCKING")
    validate_error(api.build_tax_package(eng["id"], TP),
                   ApiErrorId.ERR_BLOCKING_EXCEPTIONS_OPEN.value)


def test_reverse_settled_entry_on_reconciled_account_reports_settled(api):
    """PRD 3.3: "provided it has not been cash-settled — a reversal of an entry whose
    `cash_settled` is true is rejected with `ERR_ENTRY_SETTLED` — and provided its
    account is not already `RECONCILED`, which is rejected with
    `ERR_ACCOUNT_RECONCILED`."

    Design: Difficulty/priority_pair_validation_conflict/reverse_entry_settled_beats_account_reconciled
    """
    eng, bank, entry, stmt = fx.setup_bank_account_reconciled(book_amount=200000)
    # The entry is both cash_settled and on a RECONCILED account; settled is reported.
    validate_error(api.reverse_entry(eng["id"], entry["id"], BK),
                   ApiErrorId.ERR_ENTRY_SETTLED.value)


def test_phase_weights_must_sum_to_10000(api):
    """PRD 3.7: "Generation requires that the phases' `weight_bp` values sum to exactly
    10000 basis points (otherwise `ERR_PHASE_WEIGHTS_INVALID`)."

    Design: Corner/validations/phase_weights_not_summing_10000_rejected
    """
    eng, phases = fx.setup_quoted_with_phases([5000, 4000])
    validate_error(api.generate_phases(eng["id"], EM),
                   ApiErrorId.ERR_PHASE_WEIGHTS_INVALID.value)


def test_quote_before_scope_locked_rejected(api):
    """PRD 3.7: "Quoting requires that `scope_locked` be true; quoting before scope is
    locked is rejected with `ERR_SCOPE_NOT_LOCKED`."

    Design: Corner/validations/quote_before_scope_locked_rejected
    """
    eng = fx.create_client_and_engagement()
    validate_error(api.quote(eng["id"], EM), ApiErrorId.ERR_SCOPE_NOT_LOCKED.value)


def test_phase_invoice_out_of_order_rejected(api):
    """PRD 3.7: "The `EngagementManager` invoices a `BILLABLE` phase, moving it to
    `INVOICED`, but only after every lower-`phase_index` phase on the engagement is
    already `INVOICED` or `PAID` (otherwise `ERR_PHASE_ORDER`)."

    Design: Corner/validations/phase_invoice_out_of_order_rejected
    """
    eng, phases = fx.setup_phased_engagement([6000, 4000])
    by_idx = {p["phase_index"]: p for p in phases}
    validate_error(api.invoice_phase(eng["id"], by_idx[2]["id"], EM),
                   ApiErrorId.ERR_PHASE_ORDER.value)


def test_start_scoping_from_scoping_invalid_state(api):
    """PRD 3.2: "An `EngagementManager` moves an engagement from `DRAFT` into `SCOPING`
    to begin estimating the size of the job." PRD 2.6: "State-machine validity for the
    requested transition (`ERR_INVALID_STATE`) is sixth."

    Design: Corner/state_machines/start_scoping_from_scoping_invalid_state
    """
    eng = fx.create_client_and_engagement()
    get_success_data(api.start_scoping(eng["id"], EM))
    validate_error(api.start_scoping(eng["id"], EM), ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_from_cancelled_terminal_rejected(api):
    """PRD 3.9: "`CANCELLED` and `COMPLETED` are the two terminal lifecycle outcomes."
    PRD 2.6: "State-machine validity for the requested transition (`ERR_INVALID_STATE`)
    is sixth."

    Design: Corner/state_machines/cancel_completed_terminal_locked
    """
    eng = fx.create_client_and_engagement()
    get_success_data(api.cancel_engagement(eng["id"], EM))
    validate_error(api.cancel_engagement(eng["id"], EM), ApiErrorId.ERR_INVALID_STATE.value)


def test_categorize_without_posted_entries_rejected(api):
    """PRD 3.3: "Categorization is permitted only while the engagement is in
    `RECONSTRUCTION` (otherwise `ERR_INVALID_STATE`) and only when the account has at
    least one `POSTED` entry (otherwise `ERR_NO_POSTED_ENTRIES`)"

    Design: Corner/state_machines/categorize_without_posted_entries_rejected
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="1000", name="Cash", account_type="ASSET")
    # Create a DRAFT entry but never post it.
    get_success_data(api.create_entry(
        eng["id"], {"account_id": acct["id"], "txn_date": "2025-02-01",
                    "side": "DEBIT", "amount_cents": 1000}, BK))
    validate_error(api.categorize_account(eng["id"], acct["id"], BK),
                   ApiErrorId.ERR_NO_POSTED_ENTRIES.value)


def test_advance_to_reconciliation_with_draft_entry_rejected(api):
    """PRD 3.4: "no ledger entry on the engagement may remain in `DRAFT` — every entry
    must be `POSTED` (or `REVERSED`) first ... an unposted entry blocks the advance with
    `ERR_UNPOSTED_ENTRIES`."

    Design: Corner/state_machines/advance_reconciliation_with_draft_entries_rejected
    """
    eng = fx.setup_reconstruction_engagement()
    a1, _ = fx.add_categorized_account(eng["id"], account_code="1000", name="Cash",
                                       account_type="ASSET")
    # Leave a stray DRAFT entry on the same account.
    get_success_data(api.create_entry(
        eng["id"], {"account_id": a1["id"], "txn_date": "2025-03-01",
                    "side": "CREDIT", "amount_cents": 500}, BK))
    validate_error(api.advance_to_reconciliation(eng["id"], EM),
                   ApiErrorId.ERR_UNPOSTED_ENTRIES.value)


def test_waive_unreconciled_diff_rejected(api):
    """PRD 3.6: "A `Reviewer` may instead waive an `OPEN` exception, moving it to
    `WAIVED`; waiving is forbidden for an `UNRECONCILED_DIFF` exception, which must be
    genuinely resolved rather than dismissed (rejected with `ERR_CANNOT_WAIVE_DIFF`)."

    Design: Corner/state_machines/waive_unreconciled_diff_rejected
    """
    eng = fx.setup_reconstruction_engagement()
    bank = fx.add_account(eng["id"], account_code="1010", name="Checking",
                          account_type="ASSET", is_bank_account=True)
    exc = fx.add_exception(eng["id"], bank["id"], "UNRECONCILED_DIFF",
                           severity="BLOCKING", as_headers=RV)
    validate_error(api.waive_exception(eng["id"], exc["id"], RV),
                   ApiErrorId.ERR_CANNOT_WAIVE_DIFF.value)


def test_stale_engagement_version_on_scope_accept(api):
    """PRD 2.10: "If a competing scope estimate was accepted in the meantime — which
    legitimately supersedes the earlier baseline and increments the engagement's
    `version` — then the client's observed version is now stale, and the request is
    rejected with `ERR_STALE_ENGAGEMENT_VERSION` and HTTP status 412."

    Design: Corner/errors/stale_engagement_version_on_scope_accept
    """
    eng = fx.create_client_and_engagement()
    eng = get_success_data(api.start_scoping(eng["id"], EM))
    v0 = eng["version"]
    se1 = get_success_data(api.create_scope_estimate(eng["id"], {"monthly_txn_rate": 220}, EM))
    se2 = get_success_data(api.create_scope_estimate(eng["id"], {"monthly_txn_rate": 300}, EM))
    get_success_data(api.accept_scope_estimate(
        eng["id"], se1["id"], {"expected_engagement_version": v0}, EM))
    validate_error(api.accept_scope_estimate(
        eng["id"], se2["id"], {"expected_engagement_version": v0}, EM),
        ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value)


def test_occ_correct_version_scope_accept_succeeds(api):
    """PRD 2.10: "The accept request must carry an `expected_engagement_version` field
    whose value is the `version` of the target `CleanupEngagement` that the client last
    observed. The server compares this against the engagement's current `version`." PRD
    3.2: "the engagement's `version` is incremented by one; and the engagement's
    `workflow_status` advances from `SCOPING` to `RECONSTRUCTION`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_scope_accept_succeeds
    """
    eng = fx.create_client_and_engagement()
    eng = get_success_data(api.start_scoping(eng["id"], EM))
    v0 = eng["version"]
    se = get_success_data(api.create_scope_estimate(eng["id"], {"monthly_txn_rate": 220}, EM))
    data = validate_success(api.accept_scope_estimate(
        eng["id"], se["id"], {"expected_engagement_version": v0}, EM))
    assert data["status"] == "ACCEPTED"
    eng_after = validate_success(api.get_engagement(eng["id"], EM))
    assert eng_after["workflow_status"] == "RECONSTRUCTION"
    assert eng_after["version"] == v0 + 1


def test_scope_accept_immediate_visibility(api):
    """PRD 3.2: "the engagement's `scope_locked` flag is set to true; its
    `estimated_txn_volume` is set to the accepted estimate's `txn_volume_estimate`"

    Design: Corner/consistency_model/scope_accept_immediate_visibility
    """
    eng = fx.create_client_and_engagement()
    eng = get_success_data(api.start_scoping(eng["id"], EM))
    se = get_success_data(api.create_scope_estimate(eng["id"], {"monthly_txn_rate": 220}, EM))
    get_success_data(api.accept_scope_estimate(
        eng["id"], se["id"], {"expected_engagement_version": eng["version"]}, EM))
    data = validate_success(api.get_engagement(eng["id"], EM))
    assert data["estimated_txn_volume"] == 1518
    assert data["scope_locked"] is True


def test_derived_reconciled_count_recompute_on_mark(api):
    """PRD 2.7: "The `reconciled_account_count` is the number of the engagement's
    accounts currently in the `RECONCILED` state." PRD 3.5: "On sign-off the
    engagement's `reconciled_account_count` increases, and the engagement's
    `readiness_score` and `recon_status` are recomputed."

    Design: Corner/cross_cutting_complexity_layers/derived_reconciled_count_recompute_on_mark
    """
    eng, acct, entry = fx.setup_reconciliation_with_categorized_account()
    get_success_data(api.mark_reconciled(eng["id"], acct["id"], RV))
    data = validate_success(api.get_engagement(eng["id"], EM))
    assert data["reconciled_account_count"] == 1
    assert data["readiness_score"] == 100
    assert data["recon_status"] == "IN_BALANCE"
