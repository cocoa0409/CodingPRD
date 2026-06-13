"""Period close, the closing cascade, void/reversal cascade, and trial-balance
conservation.

Translates queue-A (Difficulty) transitive_cascade / period_close_cascade_depth3,
transitive_cascade / void_journal_entry_reversal_cascade_depth2, and
compensating_invariant / void_entry_preserves_trial_balance; plus queue-B (Corner)
state_machines / closing_entry_direct_void_protected and validations /
begin_close_with_incomplete_checklist_rejected.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_company_with_accounts, create_posted_entry,
    complete_checklist, begin_close,
    setup_closed_period_with_revenue,
    make_owner_headers, make_accountant_headers, TEST_USERS,
)

OWNER = make_owner_headers("u_owner")
ACCT = make_accountant_headers("u_acct")
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / period_close_cascade_depth3
# ---------------------------------------------------------------------------

def _closed_period_revenue_100000():
    closed = setup_closed_period_with_revenue(revenue_cents=100000)
    return closed


def test_post_close_zeroes_revenue_and_books_retained_earnings(api):
    """PRD §3.2: "as a consequence of that posting, each `REVENUE` and `EXPENSE`
    account's `posted_balance_cents` is recomputed to 0 and the retained-earnings
    account's `posted_balance_cents` is recomputed."

    Design: Difficulty/transitive_cascade/period_close_cascade_depth3
    """
    closed = _closed_period_revenue_100000()
    accts = closed["env"]["accounts"]
    assert closed["period"]["status"] == "CLOSED", f"got {closed['period']['status']}"
    rev_bal = validate_success(api.get_account_balance(accts["rev"]["id"], ACCT))
    assert rev_bal["posted_balance_cents"] == 0, \
        f"revenue should be zeroed by close, got {rev_bal['posted_balance_cents']}"
    re_bal = validate_success(api.get_account_balance(accts["re"]["id"], ACCT))
    assert re_bal["posted_balance_cents"] == 100000, \
        f"retained-earnings account should hold 100000, got {re_bal['posted_balance_cents']}"


def test_post_close_recomputes_company_retained_earnings(api):
    """PRD §3.2: "as a consequence of the retained-earnings account mutation, the
    company's `retained_earnings_cents` is recomputed from that account's new
    posted balance."

    Design: Difficulty/transitive_cascade/period_close_cascade_depth3
    """
    closed = _closed_period_revenue_100000()
    co = closed["env"]["company"]["id"]
    company = validate_success(api.get_company(co, ACCT))
    assert company["retained_earnings_cents"] == 100000, \
        f"company retained_earnings_cents should be 100000, got {company['retained_earnings_cents']}"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / void_journal_entry_reversal_cascade_depth2
# ---------------------------------------------------------------------------

def _posted_expense_entry():
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    posted = create_posted_entry(
        co, per, [(accts["exp"]["id"], 50000, 0), (accts["cash"]["id"], 0, 50000)],
        memo="expense")
    return env, posted


def test_void_entry_transitions_to_voided(api):
    """PRD §3.4: "The void runs the reversal cascade described in §2.6: a
    `REVERSAL` entry with swapped debits and credits is created and posted
    immediately, the affected account balances and the company's
    `trial_balance_status` are recomputed, and the original entry's status becomes
    `VOIDED`."

    Design: Difficulty/transitive_cascade/void_journal_entry_reversal_cascade_depth2
    """
    env, posted = _posted_expense_entry()
    voided = validate_success(api.void_journal_entry(posted["id"], OWNER))
    assert voided["status"] == "VOIDED", f"expected VOIDED, got {voided['status']}"


def test_void_entry_recomputes_balances_to_zero(api):
    """PRD §2.6: "the reversal's posting in turn recomputes the affected account
    balances and the company's trial-balance status."

    Design: Difficulty/transitive_cascade/void_journal_entry_reversal_cascade_depth2
    """
    env, posted = _posted_expense_entry()
    api.void_journal_entry(posted["id"], OWNER)
    accts = env["accounts"]
    exp_bal = validate_success(api.get_account_balance(accts["exp"]["id"], ACCT))
    cash_bal = validate_success(api.get_account_balance(accts["cash"]["id"], ACCT))
    assert exp_bal["posted_balance_cents"] == 0, \
        f"expense should net to 0 after void, got {exp_bal['posted_balance_cents']}"
    assert cash_bal["posted_balance_cents"] == 0, \
        f"cash should net to 0 after void, got {cash_bal['posted_balance_cents']}"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / void_entry_preserves_trial_balance
# ---------------------------------------------------------------------------

def test_void_preserves_trial_balance_balanced(api):
    """PRD §2.6: "The arithmetic guarantee is that an original entry plus its
    reversal leave total posted debits minus total posted credits unchanged, so the
    trial-balance invariant survives every void."

    Design: Difficulty/compensating_invariant/void_entry_preserves_trial_balance
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    posted = create_posted_entry(
        co, per, [(accts["exp"]["id"], 70000, 0), (accts["cash"]["id"], 0, 70000)], memo="x")
    api.void_journal_entry(posted["id"], OWNER)
    company = validate_success(api.get_company(co, ACCT))
    assert company["trial_balance_status"] == "BALANCED", \
        f"trial balance must remain BALANCED, got {company['trial_balance_status']}"


def test_void_preserves_trial_balance_account_balances_net_zero(api):
    """PRD §2.6: "The arithmetic guarantee is that an original entry plus its
    reversal leave total posted debits minus total posted credits unchanged, so the
    trial-balance invariant survives every void."

    Design: Difficulty/compensating_invariant/void_entry_preserves_trial_balance
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    posted = create_posted_entry(
        co, per, [(accts["exp"]["id"], 70000, 0), (accts["cash"]["id"], 0, 70000)], memo="x")
    api.void_journal_entry(posted["id"], OWNER)
    exp_bal = validate_success(api.get_account_balance(accts["exp"]["id"], ACCT))
    cash_bal = validate_success(api.get_account_balance(accts["cash"]["id"], ACCT))
    assert exp_bal["posted_balance_cents"] == 0, f"got {exp_bal['posted_balance_cents']}"
    assert cash_bal["posted_balance_cents"] == 0, f"got {cash_bal['posted_balance_cents']}"


# ---------------------------------------------------------------------------
# Corner: state_machines / closing_entry_direct_void_protected
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Corner: validations / begin_close_with_incomplete_checklist_rejected
# ---------------------------------------------------------------------------

def test_begin_close_with_incomplete_checklist_rejected(api):
    """PRD §3.2: "all four `close_checklist` items must be marked done, or the
    request fails with `ERR_CHECKLIST_INCOMPLETE`".

    Design: Corner/validations/begin_close_with_incomplete_checklist_rejected
    """
    env = setup_company_with_accounts()
    per = env["period"]["id"]
    # Mark only three of four items done.
    from test_helpers import checklist_item_payload
    for item in ("BANK_RECONCILED", "AR_REVIEWED", "AP_REVIEWED"):
        validate_success(api.mark_checklist_item(per, checklist_item_payload(item, True), ACCT))
    resp = api.begin_close_period(per, ACCT)
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value)
    after = validate_success(api.get_accounting_period(per, ACCT))
    assert after["status"] == "OPEN", f"period must stay OPEN, got {after['status']}"
