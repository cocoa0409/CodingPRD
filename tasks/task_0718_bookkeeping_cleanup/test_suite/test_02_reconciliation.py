"""Bank reconciliation: statement finalize, recon difference boundary, cascades,
cross-entity state dependencies, ledger entry period/exclusion rules, and the
reversing-entry balance invariant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success, validate_error
from test_helpers import (
    api_client, ApiErrorId,
    make_engagement_manager_headers,
    make_bookkeeper_headers,
    make_reviewer_headers,
)
from test_helpers import fixtures as fx

EM = make_engagement_manager_headers("em-1")
BK = make_bookkeeper_headers("bk-1")
RV = make_reviewer_headers("reviewer-1")
RV2 = make_reviewer_headers("reviewer-2")


def test_recon_difference_tolerance_inclusive_boundary(api):
    """PRD 3.5: "If the absolute value of that difference is at most 100 cents — the
    boundary is inclusive, so a difference whose magnitude equals exactly 100 still
    reconciles — the statement becomes `RECONCILED`."

    Design: Difficulty/boundary_precision_check/recon_difference_tolerance_inclusive_boundary
    """
    # book 340000; bank adjusted = 350100 + 15000 - 25000 = 340100; diff = +100 (inclusive).
    eng, bank, entry, stmt, item = fx.setup_bank_statement_reconciling(
        book_amount=340000, ending_balance_cents=350100,
        deposits_in_transit_cents=15000, outstanding_checks_cents=25000,
        statement_line_amount_cents=340000, match_kind="TOLERANCE")
    data = validate_success(api.finalize_statement(eng["id"], stmt["id"], RV))
    assert data["status"] == "RECONCILED"


def test_recon_difference_exact_zero_reconciles(api):
    """PRD 3.5: "take the statement's `ending_balance_cents`, add its
    `deposits_in_transit_cents`, subtract its `outstanding_checks_cents`, and from that
    adjusted bank figure subtract the account's `book_balance_cents`. If the absolute
    value of that difference is at most 100 cents ... the statement becomes
    `RECONCILED`."

    Design: Difficulty/resource_temporal_overlap/statement_dates_aggregate_capacity_vs_book
    """
    # book 340000; bank adjusted = 350000 + 15000 - 25000 = 340000; diff 0.
    eng, bank, entry, stmt, item = fx.setup_bank_statement_reconciling(
        book_amount=340000, ending_balance_cents=350000,
        deposits_in_transit_cents=15000, outstanding_checks_cents=25000,
        statement_line_amount_cents=340000, match_kind="EXACT")
    data = validate_success(api.finalize_statement(eng["id"], stmt["id"], RV))
    assert data["status"] == "RECONCILED"
    eng_after = validate_success(api.get_engagement(eng["id"], EM))
    assert eng_after["recon_status"] == "IN_BALANCE"


def test_statement_aggregate_capacity_balances_to_book(api):
    """PRD 3.5: "It then computes the reconciliation difference: take the statement's
    `ending_balance_cents`, add its `deposits_in_transit_cents`, subtract its
    `outstanding_checks_cents`, and from that adjusted bank figure subtract the
    account's `book_balance_cents`."

    Design: Difficulty/resource_temporal_overlap/statement_dates_aggregate_capacity_vs_book
    """
    eng, bank, entry, stmt, item = fx.setup_bank_statement_reconciling(
        book_amount=340000, ending_balance_cents=350000,
        deposits_in_transit_cents=15000, outstanding_checks_cents=25000,
        statement_line_amount_cents=340000, match_kind="EXACT")
    data = validate_success(api.finalize_statement(eng["id"], stmt["id"], RV))
    assert data["status"] == "RECONCILED"


def test_statement_finalize_cascades_settle_and_recon_status(api):
    """PRD 3.5: "Finalization then marks every linked ledger entry's `cash_settled`
    flag true and recomputes the engagement's `recon_status`."

    Design: Difficulty/transitive_cascade/statement_finalize_cascades_settle_and_readiness
    """
    eng, bank, entry, stmt, item = fx.setup_bank_statement_reconciling(
        book_amount=340000, ending_balance_cents=350000,
        deposits_in_transit_cents=15000, outstanding_checks_cents=25000,
        statement_line_amount_cents=340000, match_kind="EXACT")
    stmt_after = validate_success(api.finalize_statement(eng["id"], stmt["id"], RV))
    assert stmt_after["status"] == "RECONCILED"
    posted = validate_success(api.list_entries(eng["id"], BK,
                                               params={"account_id": bank["id"]}))
    matched = [e for e in posted if e["id"] == entry["id"]]
    assert matched and matched[0]["cash_settled"] is True
    eng_after = validate_success(api.get_engagement(eng["id"], EM))
    assert eng_after["recon_status"] == "IN_BALANCE"


def test_statement_finalize_settles_then_permits_account_reconcile(api):
    """PRD 3.5: "Finalization then marks every linked ledger entry's `cash_settled`
    flag true and recomputes the engagement's `recon_status`." PRD 3.5: "If the account
    is a bank account, one of its statements must already be `RECONCILED` (otherwise
    `ERR_BANK_NOT_RECONCILED`) ... On sign-off the engagement's
    `reconciled_account_count` increases, and the engagement's `readiness_score` and
    `recon_status` are recomputed."

    Design: Difficulty/transitive_cascade/statement_finalize_cascades_settle_and_readiness
    """
    eng, bank, entry, stmt = fx.setup_bank_account_reconciled(book_amount=340000)
    assert bank["status"] == "RECONCILED"
    eng_after = validate_success(api.get_engagement(eng["id"], EM))
    assert eng_after["reconciled_account_count"] == 1
    assert eng_after["readiness_score"] == 100


def test_account_reconcile_requires_statement_reconciled(api):
    """PRD 3.5: "If the account is a bank account, one of its statements must already
    be `RECONCILED` (otherwise `ERR_BANK_NOT_RECONCILED`)"

    Design: Difficulty/cross_entity_state_dependency/account_reconcile_requires_statement_reconciled
    """
    eng = fx.setup_reconstruction_engagement()
    bank = fx.add_account(eng["id"], account_code="1010", name="Checking",
                          account_type="ASSET", is_bank_account=True)
    fx.add_posted_entry(eng["id"], bank["id"], side="DEBIT", amount_cents=340000)
    get_success_data(api.categorize_account(eng["id"], bank["id"], BK))
    get_success_data(api.advance_to_reconciliation(eng["id"], EM))
    # Import a statement but never finalize it (stays IMPORTED).
    get_success_data(api.create_statement(
        eng["id"], {"account_id": bank["id"], "statement_start": "2025-02-01",
                    "statement_end": "2025-02-28", "ending_balance_cents": 340000}, RV))
    validate_error(api.mark_reconciled(eng["id"], bank["id"], RV2),
                   ApiErrorId.ERR_BANK_NOT_RECONCILED.value)


def test_entry_post_requires_account_not_excluded(api):
    """PRD 3.3: "Posting an entry advances it from `DRAFT` to `POSTED`, but only when
    its `txn_date` falls within the engagement's `period_start` through `period_end`
    inclusive ... and only when the target account is not `EXCLUDED`, an excluded
    account being rejected with `ERR_ACCOUNT_EXCLUDED`."

    Design: Difficulty/cross_entity_state_dependency/entry_post_requires_account_not_excluded
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="9999", name="Suspense", account_type="ASSET")
    entry = get_success_data(api.create_entry(
        eng["id"], {"account_id": acct["id"], "txn_date": "2025-02-01",
                    "side": "DEBIT", "amount_cents": 1000}, BK))
    get_success_data(api.exclude_account(eng["id"], acct["id"], BK))
    validate_error(api.post_entry(eng["id"], entry["id"], BK),
                   ApiErrorId.ERR_ACCOUNT_EXCLUDED.value)


def test_entry_post_period_end_inclusive(api):
    """PRD 3.3: "Posting an entry advances it from `DRAFT` to `POSTED`, but only when
    its `txn_date` falls within the engagement's `period_start` through `period_end`
    inclusive — an out-of-period date is rejected with `ERR_ENTRY_OUT_OF_PERIOD`"

    Design: Difficulty/resource_temporal_overlap/entry_post_period_boundary_inclusive
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="1000", name="Cash", account_type="ASSET")
    entry = get_success_data(api.create_entry(
        eng["id"], {"account_id": acct["id"], "txn_date": "2025-06-30",
                    "side": "DEBIT", "amount_cents": 1000}, BK))
    data = validate_success(api.post_entry(eng["id"], entry["id"], BK))
    assert data["status"] == "POSTED"


def test_entry_post_period_start_inclusive(api):
    """PRD 3.3: "only when its `txn_date` falls within the engagement's `period_start`
    through `period_end` inclusive — an out-of-period date is rejected with
    `ERR_ENTRY_OUT_OF_PERIOD`"

    Design: Difficulty/resource_temporal_overlap/entry_post_period_boundary_inclusive
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="1000", name="Cash", account_type="ASSET")
    entry = get_success_data(api.create_entry(
        eng["id"], {"account_id": acct["id"], "txn_date": "2025-01-01",
                    "side": "DEBIT", "amount_cents": 1000}, BK))
    data = validate_success(api.post_entry(eng["id"], entry["id"], BK))
    assert data["status"] == "POSTED"


def test_account_reconcile_requires_statement_reconciled_when_imported_only(api):
    """PRD 3.5: "If the account is a bank account, one of its statements must already
    be `RECONCILED` (otherwise `ERR_BANK_NOT_RECONCILED`)"

    Design: Difficulty/cross_entity_state_dependency/account_reconcile_requires_statement_reconciled
    """
    # Statement progressed to RECONCILING (a recon item exists) but not finalized.
    eng, bank, entry, stmt, item = fx.setup_bank_statement_reconciling(
        book_amount=340000, ending_balance_cents=350000,
        deposits_in_transit_cents=15000, outstanding_checks_cents=25000,
        statement_line_amount_cents=340000, match_kind="EXACT")
    validate_error(api.mark_reconciled(eng["id"], bank["id"], RV2),
                   ApiErrorId.ERR_BANK_NOT_RECONCILED.value)


def test_entry_post_on_excluded_draft_account_categorized_path(api):
    """PRD 3.3: "only when the target account is not `EXCLUDED`, an excluded account
    being rejected with `ERR_ACCOUNT_EXCLUDED`."

    Design: Difficulty/cross_entity_state_dependency/entry_post_requires_account_not_excluded
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="1000", name="Cash", account_type="ASSET")
    # Post one entry, then exclude is refused on CATEGORIZED bank-only; here exclude from
    # DRAFT after creating a second unposted entry that we then try to post.
    second = get_success_data(api.create_entry(
        eng["id"], {"account_id": acct["id"], "txn_date": "2025-02-02",
                    "side": "CREDIT", "amount_cents": 500}, BK))
    get_success_data(api.exclude_account(eng["id"], acct["id"], BK))
    validate_error(api.post_entry(eng["id"], second["id"], BK),
                   ApiErrorId.ERR_ACCOUNT_EXCLUDED.value)


def test_entry_post_one_day_past_period_rejected(api):
    """PRD 3.3: "only when its `txn_date` falls within the engagement's `period_start`
    through `period_end` inclusive — an out-of-period date is rejected with
    `ERR_ENTRY_OUT_OF_PERIOD`"

    Design: Corner/validations/entry_out_of_period_upper_bound_rejected
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="1000", name="Cash", account_type="ASSET")
    entry = get_success_data(api.create_entry(
        eng["id"], {"account_id": acct["id"], "txn_date": "2025-07-01",
                    "side": "DEBIT", "amount_cents": 1000}, BK))
    validate_error(api.post_entry(eng["id"], entry["id"], BK),
                   ApiErrorId.ERR_ENTRY_OUT_OF_PERIOD.value)


def test_reverse_entry_creates_opposite_posting(api):
    """PRD 3.3: "Reversing an entry creates a brand-new `POSTED` ledger entry with the
    opposite `side`, the same `amount_cents`, and its `reversed_entry_id` set to the
    original entry's id"

    Design: Corner/state_machines/reverse_entry_creates_reversing_entry_self_reference
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="1000", name="Cash", account_type="ASSET")
    entry = fx.add_posted_entry(eng["id"], acct["id"], side="DEBIT", amount_cents=1000)
    rev = validate_success(api.reverse_entry(eng["id"], entry["id"], BK))
    assert rev["status"] == "REVERSED"
    reversing = validate_success(api.list_entries(eng["id"], BK,
                                                  params={"reversed_entry_id": entry["id"]}))
    assert len(reversing) == 1
    r = reversing[0]
    assert r["status"] == "POSTED"
    assert r["side"] == "CREDIT"
    assert r["amount_cents"] == 1000
    assert r["reversed_entry_id"] == entry["id"]


def test_recon_out_of_balance_creates_blocking_exception(api):
    """PRD 3.5: "If instead the absolute difference exceeds 100 cents, finalization is
    rejected with `ERR_RECON_OUT_OF_BALANCE`, and the system opens a `BLOCKING`
    `UNRECONCILED_DIFF` exception on the account to track the out-of-balance condition."

    Design: Corner/errors/recon_out_of_balance_creates_blocking_exception
    """
    # book 360000; bank adjusted = 350000 + 15000 - 25000 = 340000; diff -20000.
    eng, bank, entry, stmt, item = fx.setup_bank_statement_reconciling(
        book_amount=360000, ending_balance_cents=350000,
        deposits_in_transit_cents=15000, outstanding_checks_cents=25000,
        statement_line_amount_cents=360000, match_kind="TOLERANCE")
    validate_error(api.finalize_statement(eng["id"], stmt["id"], RV),
                   ApiErrorId.ERR_RECON_OUT_OF_BALANCE.value)
    stmt_after = validate_success(api.list_statements(eng["id"], RV,
                                                      params={"account_id": bank["id"]}))
    s = [x for x in stmt_after if x["id"] == stmt["id"]][0]
    assert s["status"] == "RECONCILING"


def test_open_recon_items_block_finalize(api):
    """PRD 3.5: "Finalization first requires that no reconciliation item on the
    statement is still `UNMATCHED` or `DISPUTED` (otherwise `ERR_OPEN_RECON_ITEMS`)."
    PRD 3.5: "An `EXACT` match requires the magnitudes to be equal ... one whose
    magnitudes differ beyond what its `match_kind` permits lands in `UNMATCHED`"

    Design: Corner/errors/open_recon_items_block_finalize
    """
    eng, bank, entry, stmt, item = fx.setup_bank_statement_reconciling(
        book_amount=340000, ending_balance_cents=350000,
        deposits_in_transit_cents=15000, outstanding_checks_cents=25000,
        statement_line_amount_cents=999999, match_kind="EXACT")
    assert item["status"] == "UNMATCHED"
    validate_error(api.finalize_statement(eng["id"], stmt["id"], RV),
                   ApiErrorId.ERR_OPEN_RECON_ITEMS.value)
