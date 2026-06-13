"""Bank-feed categorization loop, reconciliation difference and finalize, and the
period-open optimistic-concurrency check.

Translates queue-A (Difficulty) non_linear_state_machine /
bank_feed_transaction_categorize_recategorize_cycle and
priority_pair_validation_conflict / finalize_recon_unbalanced_vs_stale_bank; plus
queue-B (Corner) state_machines / bank_feed_transaction_initial_state_unmatched,
state_machines / abandon_then_finalize_reconciliation_invalid_state, calculations /
reconciliation_difference_balanced_zero, validations /
recategorize_cleared_transaction_rejected, and cross_cutting_complexity_layers /
occ_stale_company_version_on_period_open.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_company_with_accounts, import_transaction, import_and_categorize,
    setup_reconciliation,
    create_company_payload, create_account_payload, configure_company_payload,
    create_accounting_period_payload, create_bank_feed_transaction_payload,
    finalize_reconciliation_payload, categorize_payload,
    make_owner_headers, make_accountant_headers, make_bookkeeper_headers, TEST_USERS,
)

OWNER = make_owner_headers("u_owner")
ACCT = make_accountant_headers("u_acct")
BOOK = make_bookkeeper_headers("u_book")


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine /
#             bank_feed_transaction_categorize_recategorize_cycle
# ---------------------------------------------------------------------------

def test_recategorize_returns_transaction_to_unmatched(api):
    """PRD §3.5: "Recategorization voids the linked `BANK_FEED` entry through the
    reversal cascade, resets both `journal_entry_id` and `counter_account_id` to
    null, and returns the transaction to `UNMATCHED`".

    Design: Difficulty/non_linear_state_machine/bank_feed_transaction_categorize_recategorize_cycle
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    txn = import_and_categorize(co, bank, -20000, accts["exp"]["id"], description="OFFICE SUPPLY")
    assert txn["status"] == "CATEGORIZED"
    recat = validate_success(api.recategorize_transaction(txn["id"], BOOK))
    assert recat["status"] == "UNMATCHED", f"expected UNMATCHED, got {recat['status']}"
    assert recat["journal_entry_id"] is None, \
        f"journal_entry_id must reset to null, got {recat['journal_entry_id']}"


def test_recategorize_voids_linked_entry_and_zeroes_balance(api):
    """PRD §3.5: "Recategorization voids the linked `BANK_FEED` entry through the
    reversal cascade, resets both `journal_entry_id` and `counter_account_id` to
    null, and returns the transaction to `UNMATCHED`".

    Design: Difficulty/non_linear_state_machine/bank_feed_transaction_categorize_recategorize_cycle
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    txn = import_and_categorize(co, bank, -20000, accts["exp"]["id"], description="OFFICE SUPPLY")
    je1 = txn["journal_entry_id"]
    api.recategorize_transaction(txn["id"], BOOK)
    entry = validate_success(api.get_journal_entry(je1, ACCT))
    assert entry["status"] == "VOIDED", f"linked entry should be VOIDED, got {entry['status']}"
    exp_bal = validate_success(api.get_account_balance(accts["exp"]["id"], ACCT))
    assert exp_bal["posted_balance_cents"] == 0, \
        f"expense balance should reset to 0, got {exp_bal['posted_balance_cents']}"


def test_bank_feed_transaction_initial_state_unmatched(api):
    """PRD §3.5: "An imported transaction begins `UNMATCHED` with `cleared` false."

    Design: Corner/state_machines/bank_feed_transaction_initial_state_unmatched
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    bank = env["bank"]["id"]
    txn = validate_success(api.create_bank_feed_transaction(
        create_bank_feed_transaction_payload(co, bank, -5000, description="FEE"), BOOK), 201)
    assert txn["status"] == "UNMATCHED", f"expected UNMATCHED, got {txn['status']}"
    assert txn["cleared"] is False, f"expected cleared False, got {txn['cleared']}"


# ---------------------------------------------------------------------------
# Corner: calculations / reconciliation_difference_balanced_zero
# ---------------------------------------------------------------------------

def test_reconciliation_difference_balanced_zero(api):
    """PRD §3.9: "it sums the signed `amount_cents` over the included transactions
    to obtain the cleared movement, adds that movement to
    `statement_opening_balance_cents` to obtain the expected ending balance, and
    sets `difference_cents` to `statement_ending_balance_cents` minus that expected
    ending balance."

    Design: Corner/calculations/reconciliation_difference_balanced_zero
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    t1 = import_and_categorize(co, bank, 50000, accts["rev"]["id"],
                               posted_date="2026-01-05T00:00:00.000Z", description="DEP")
    t2 = import_and_categorize(co, bank, -20000, accts["exp"]["id"],
                               posted_date="2026-01-06T00:00:00.000Z", description="PAY")
    # opening 100000 + movement (+50000 - 20000 = +30000) = 130000 expected; ending 130000 -> diff 0
    rec = setup_reconciliation(100000, 130000, [t1["id"], t2["id"]], co, bank)
    assert rec["difference_cents"] == 0, f"expected difference 0, got {rec['difference_cents']}"
    assert rec["status"] == "IN_PROGRESS", f"expected IN_PROGRESS, got {rec['status']}"


# ---------------------------------------------------------------------------
# Corner: state_machines / abandon_then_finalize_reconciliation_invalid_state
# ---------------------------------------------------------------------------

def test_abandoned_reconciliation_cannot_finalize(api):
    """PRD §3.9: "An `Accountant` or `Owner` finalizes an `IN_PROGRESS`
    reconciliation, moving it to the terminal `RECONCILED` state."
    PRD §3.11: "Only once existence is established does the system check that a
    target resource is in a state from which the requested transition is defined
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/abandon_then_finalize_reconciliation_invalid_state
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    bank_v = env["bank"]["version"]
    txn = import_and_categorize(co, bank, 50000, accts["rev"]["id"], description="DEP")
    rec = setup_reconciliation(0, 50000, [txn["id"]], co, bank)
    validate_success(api.abandon_reconciliation(rec["id"], ACCT))
    resp = api.finalize_reconciliation(rec["id"], finalize_reconciliation_payload(bank_v), ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner: validations / recategorize_cleared_transaction_rejected
# ---------------------------------------------------------------------------

def test_recategorize_cleared_transaction_rejected(api):
    """PRD §3.5: "a transaction already cleared by a reconciliation cannot be
    recategorized and is rejected with `ERR_TRANSACTION_CLEARED`."

    Design: Corner/validations/recategorize_cleared_transaction_rejected
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    bank_v = env["bank"]["version"]
    txn = import_and_categorize(co, bank, 50000, accts["rev"]["id"], description="DEP")
    rec = setup_reconciliation(0, 50000, [txn["id"]], co, bank)
    validate_success(api.finalize_reconciliation(
        rec["id"], finalize_reconciliation_payload(bank_v), ACCT))
    cleared = validate_success(api.get_bank_feed_transaction(txn["id"], ACCT))
    assert cleared["cleared"] is True, "transaction should be cleared after finalize"
    resp = api.recategorize_transaction(txn["id"], BOOK)
    validate_error(resp, ApiErrorId.ERR_TRANSACTION_CLEARED.value)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
#             finalize_recon_unbalanced_vs_stale_bank
# ---------------------------------------------------------------------------

def _unbalanced_recon_with_stale_version():
    """Build an IN_PROGRESS reconciliation whose difference is 1 (unbalanced), and
    return (rec_id, stale_version, co, bank_current_version)."""
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    bank_v = env["bank"]["version"]  # 1 at creation
    txn = import_and_categorize(co, bank, 50000, accts["rev"]["id"], description="DEPOSIT")
    # opening 0 + 50000 = 50000 expected; ending 50001 -> difference 1.
    rec = setup_reconciliation(0, 50001, [txn["id"]], co, bank)
    return rec, bank_v


def test_finalize_unbalanced_recon_difference_is_one(api):
    """PRD §3.9: "it sums the signed `amount_cents` over the included transactions
    to obtain the cleared movement, adds that movement to
    `statement_opening_balance_cents` to obtain the expected ending balance, and
    sets `difference_cents` to `statement_ending_balance_cents` minus that expected
    ending balance."

    Design: Difficulty/priority_pair_validation_conflict/finalize_recon_unbalanced_vs_stale_bank
    """
    rec, _ = _unbalanced_recon_with_stale_version()
    assert rec["difference_cents"] == 1, f"expected difference 1, got {rec['difference_cents']}"


def test_finalize_unbalanced_beats_stale_version(api):
    """PRD §3.11: "Optimistic-concurrency checks (`ERR_STALE_VERSION`) are the last
    business gate, applying to period creation and reconciliation finalize."
    PRD §3.9: "Finalize requires `difference_cents` to be exactly zero with no
    tolerance (a non-zero difference is rejected with `ERR_RECONCILIATION_UNBALANCED`)".

    Design: Difficulty/priority_pair_validation_conflict/finalize_recon_unbalanced_vs_stale_bank
    """
    rec, bank_v = _unbalanced_recon_with_stale_version()
    # bank version is 1; pass a stale 0 AND keep the reconciliation unbalanced.
    stale = bank_v - 1
    resp = api.finalize_reconciliation(rec["id"], finalize_reconciliation_payload(stale), ACCT)
    validate_error(resp, ApiErrorId.ERR_RECONCILIATION_UNBALANCED.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / occ_stale_company_version_on_period_open
# ---------------------------------------------------------------------------

def test_open_period_with_stale_company_version_rejected(api):
    """PRD §2.7: "If that value does not match the company's current `version` —
    because another open has already advanced it since the client read it — the
    create is rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_company_version_on_period_open
    """
    company = validate_success(api.create_company(create_company_payload(), OWNER), 201)
    co = company["id"]
    co_v1 = company["version"]
    re = validate_success(api.create_account(
        create_account_payload(co, "3900", "RE", "EQUITY"), OWNER), 201)
    company = validate_success(api.configure_company(
        co, configure_company_payload(re["id"], co_v1), OWNER))
    co_v2 = company["version"]
    # First open advances company.version beyond co_v2.
    validate_success(api.create_accounting_period(
        create_accounting_period_payload(co, co_v2), OWNER), 201)
    # Replay the now-stale co_v2 for the contiguous next period.
    resp = api.create_accounting_period(
        create_accounting_period_payload(
            co, co_v2, period_label="2026-02",
            start_date="2026-02-01T00:00:00.000Z", end_date="2026-03-01T00:00:00.000Z"), OWNER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
#             categorize_requires_active_counter_account
# ---------------------------------------------------------------------------

def test_categorize_onto_archived_counter_account_rejected(api):
    """PRD §3.5: "the `counter_account_id` must reference an existing `ACTIVE`
    account in the same company (a missing account yields `ERR_ACCOUNT_NOT_FOUND`,
    an archived one yields `ERR_ACCOUNT_ARCHIVED`)".

    Design: Difficulty/cross_entity_state_dependency/categorize_requires_active_counter_account
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    # Archive the expense account, then try to categorize onto it.
    validate_success(api.archive_account(accts["exp"]["id"], ACCT))
    txn = import_transaction(co, bank, -3000, description="ATM")
    resp = api.categorize_transaction(txn["id"], categorize_payload(accts["exp"]["id"]), BOOK)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ARCHIVED.value)
    after = validate_success(api.get_bank_feed_transaction(txn["id"], ACCT))
    assert after["status"] == "UNMATCHED", f"must stay UNMATCHED, got {after['status']}"


def test_categorize_onto_active_counter_account_succeeds(api):
    """PRD §3.5: "the `counter_account_id` must reference an existing `ACTIVE`
    account in the same company (a missing account yields `ERR_ACCOUNT_NOT_FOUND`,
    an archived one yields `ERR_ACCOUNT_ARCHIVED`)".

    Design: Difficulty/cross_entity_state_dependency/categorize_requires_active_counter_account
    """
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    bank = env["bank"]["id"]
    # The expense account stays ACTIVE -> categorization succeeds.
    txn = import_transaction(co, bank, -3000, description="ATM")
    categorized = validate_success(
        api.categorize_transaction(txn["id"], categorize_payload(accts["exp"]["id"]), BOOK))
    assert categorized["status"] == "CATEGORIZED", \
        f"active counter account should categorize, got {categorized['status']}"
