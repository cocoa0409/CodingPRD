"""Journal-entry posting: balance boundary, maker-checker, open-period gate,
validation precedence, and immediate balance visibility.

Translates queue-A (Difficulty) instances boundary_precision_check /
journal_entry_balance_off_by_one_cent, priority_pair_validation_conflict /
post_into_nonopen_period_state_vs_fiscal, cross_entity_state_dependency /
journal_post_requires_open_period, and consistency_model immediate visibility;
plus queue-B (Corner) rbac instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_company_payload, create_account_payload, configure_company_payload,
    create_accounting_period_payload, create_journal_entry_payload,
    create_journal_line_payload,
    setup_company_with_accounts, create_draft_entry_with_lines, create_posted_entry,
    setup_period_in_closing, complete_checklist, begin_close,
    make_owner_headers, make_accountant_headers, make_bookkeeper_headers, make_headers,
    TEST_USERS,
)

OWNER = make_owner_headers("u_owner")
ACCT = make_accountant_headers("u_acct")
BOOK = make_bookkeeper_headers("u_book")


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / journal_entry_balance_off_by_one_cent
# ---------------------------------------------------------------------------

def test_post_unbalanced_off_by_one_cent_rejected(api):
    """PRD §3.4: "`total_debit_cents` must equal `total_credit_cents`, that common
    total must be greater than zero, and the entry must have at least two
    `JournalLine` rows — any of these failing is rejected with
    `ERR_ENTRY_NOT_BALANCED`."

    Design: Difficulty/boundary_precision_check/journal_entry_balance_off_by_one_cent
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    entry = create_draft_entry_with_lines(
        co, per, [(accts["exp"]["id"], 50000, 0), (accts["cash"]["id"], 0, 49999)],
        memo="off by one")
    resp = api.post_journal_entry(entry["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_BALANCED.value)
    after = validate_success(api.get_journal_entry(entry["id"], ACCT))
    assert after["status"] == "DRAFT", f"entry must stay DRAFT, got {after['status']}"


def test_post_exactly_balanced_succeeds(api):
    """PRD §3.4: "`total_debit_cents` must equal `total_credit_cents`, that common
    total must be greater than zero, and the entry must have at least two
    `JournalLine` rows — any of these failing is rejected with
    `ERR_ENTRY_NOT_BALANCED`."

    Design: Difficulty/boundary_precision_check/journal_entry_balance_off_by_one_cent
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    entry = create_draft_entry_with_lines(
        co, per, [(accts["exp"]["id"], 50000, 0), (accts["cash"]["id"], 0, 50000)],
        memo="balanced")
    posted = validate_success(api.post_journal_entry(entry["id"], ACCT))
    assert posted["status"] == "POSTED", f"expected POSTED, got {posted['status']}"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / journal_post_requires_open_period
# ---------------------------------------------------------------------------

def test_post_into_closing_period_rejected_period_not_open(api):
    """PRD §3.4: "The entry's `period_id` must refer to a period in `OPEN` status,
    or the post is rejected with `ERR_PERIOD_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/journal_post_requires_open_period
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    # Post a balanced entry so begin-close's no-draft precondition can be met,
    # then move the period to CLOSING.
    create_posted_entry(co, per,
                        [(accts["exp"]["id"], 10000, 0), (accts["cash"]["id"], 0, 10000)],
                        memo="first")
    complete_checklist(per)
    begin_close(per)
    # New DRAFT entry created in the now-CLOSING period.
    entry = create_draft_entry_with_lines(
        co, per, [(accts["exp"]["id"], 5000, 0), (accts["cash"]["id"], 0, 5000)],
        entry_date="2026-01-20T00:00:00.000Z", memo="late")
    resp = api.post_journal_entry(entry["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)
    after = validate_success(api.get_journal_entry(entry["id"], ACCT))
    assert after["status"] == "DRAFT", f"entry must stay DRAFT, got {after['status']}"


def test_post_into_open_period_succeeds(api):
    """PRD §3.4: "The entry's `period_id` must refer to a period in `OPEN` status,
    or the post is rejected with `ERR_PERIOD_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/journal_post_requires_open_period
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    posted = create_posted_entry(
        co, per, [(accts["exp"]["id"], 5000, 0), (accts["cash"]["id"], 0, 5000)],
        memo="open period post")
    assert posted["status"] == "POSTED", f"expected POSTED, got {posted['status']}"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
#             post_into_nonopen_period_state_vs_fiscal
# ---------------------------------------------------------------------------

def test_repost_posted_entry_in_closing_period_returns_invalid_state(api):
    """PRD §3.11: "Only once existence is established does the system check that a
    target resource is in a state from which the requested transition is defined
    (`ERR_INVALID_STATE`)."
    PRD §3.11: "Fiscal-period rules follow: the open-period requirement
    (`ERR_PERIOD_NOT_OPEN`) for posting, categorizing, sending, approving, and
    paying, then the closed-period rejection (`ERR_PERIOD_CLOSED`) for voids and
    reverses."

    Design: Difficulty/priority_pair_validation_conflict/post_into_nonopen_period_state_vs_fiscal
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    # A balanced entry is posted, then the period advances to CLOSING.
    posted = create_posted_entry(
        co, per, [(accts["exp"]["id"], 50000, 0), (accts["cash"]["id"], 0, 50000)], memo="e")
    complete_checklist(per)
    begin_close(per)
    # Re-posting the already-POSTED entry: state-check (priority 5) fires before
    # the fiscal open-period check (priority 10).
    resp = api.post_journal_entry(posted["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_repost_posted_entry_open_period_returns_invalid_state(api):
    """PRD §3.11: "Only once existence is established does the system check that a
    target resource is in a state from which the requested transition is defined
    (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/post_into_nonopen_period_state_vs_fiscal
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    posted = create_posted_entry(
        co, per, [(accts["exp"]["id"], 50000, 0), (accts["cash"]["id"], 0, 50000)], memo="e")
    # Period still OPEN: re-posting is still an invalid-state transition.
    resp = api.post_journal_entry(posted["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Difficulty: consistency_model — immediate balance visibility
# Note: this Corner instance lives under section consistency_model.
# ---------------------------------------------------------------------------

def test_balance_visible_immediately_after_post(api):
    """PRD §3.4: "On success the entry becomes `POSTED`, each referenced account's
    `posted_balance_cents` is recomputed per its normal side, and the company's
    `trial_balance_status` is recomputed."

    Design: Corner/consistency_model/immediate_visibility_of_balance_after_post
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    create_posted_entry(
        co, per, [(accts["cash"]["id"], 8000, 0), (accts["rev"]["id"], 0, 8000)],
        memo="cash sale")
    bal = validate_success(api.get_account_balance(accts["cash"]["id"], TEST_USERS["auditor_headers"]))
    assert bal["posted_balance_cents"] == 8000, \
        f"expected 8000 immediately after post, got {bal['posted_balance_cents']}"


# ---------------------------------------------------------------------------
# Corner: rbac
# ---------------------------------------------------------------------------

def test_bookkeeper_cannot_post_journal_entry(api):
    """PRD §2.1: "a `Bookkeeper` may not post journal entries, approve bills, run
    the close, or finalize a reconciliation."

    Design: Corner/rbac/bookkeeper_cannot_post_journal_entry
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    entry = create_draft_entry_with_lines(
        co, per, [(accts["exp"]["id"], 5000, 0), (accts["cash"]["id"], 0, 5000)], memo="x")
    # A different bookkeeper id attempts to post.
    resp = api.post_journal_entry(entry["id"], make_bookkeeper_headers("u_book2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    after = validate_success(api.get_journal_entry(entry["id"], ACCT))
    assert after["status"] == "DRAFT", f"entry must stay DRAFT, got {after['status']}"


def test_maker_cannot_post_own_entry_segregation(api):
    """PRD §3.4: "the posting caller's `X-User-ID` must differ from the entry's
    `created_by_user_id`, so the maker of an entry can never post their own work;
    a self-post is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/maker_cannot_post_own_entry_segregation
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    drafter = make_accountant_headers("u_acct")
    # Draft AND post under the same Accountant X-User-ID.
    entry = validate_success(api.create_journal_entry(
        create_journal_entry_payload(co, per, "2026-01-10T00:00:00.000Z", memo="x"), drafter), 201)
    validate_success(api.create_journal_line(
        create_journal_line_payload(entry["id"], accts["exp"]["id"], debit_cents=5000), drafter), 201)
    validate_success(api.create_journal_line(
        create_journal_line_payload(entry["id"], accts["cash"]["id"], credit_cents=5000), drafter), 201)
    resp = api.post_journal_entry(entry["id"], drafter)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    # A present X-User-ID but an X-User-Role that is not a recognized role.
    bad_headers = make_headers("u_x", "NotARole")
    resp = api.create_company(create_company_payload(), bad_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
