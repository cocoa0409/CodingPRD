"""Account balance reads (posted vs projected) and financial statements.

Translates queue-A (Difficulty) dual_variant_calc /
account_balance_posted_vs_projected_revenue, and queue-B (Corner) endpoints /
financial_statements_net_income_computed.
"""
from test_helpers import (
    validate_success,
    setup_company_with_accounts, create_posted_entry, create_draft_entry_with_lines,
    make_accountant_headers, TEST_USERS,
)

ACCT = make_accountant_headers("u_acct")
AUDITOR = TEST_USERS["auditor_headers"]


def _revenue_with_posted_and_draft():
    """Build a company whose revenue account has 100000 POSTED and a separate
    30000 DRAFT credit. Returns (rev_account_id, auditor-readable)."""
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    create_posted_entry(co, per,
                        [(accts["ar"]["id"], 100000, 0), (accts["rev"]["id"], 0, 100000)],
                        memo="posted sale")
    create_draft_entry_with_lines(
        co, per, [(accts["ar"]["id"], 30000, 0), (accts["rev"]["id"], 0, 30000)],
        entry_date="2026-01-11T00:00:00.000Z", memo="draft sale")
    return accts["rev"]["id"]


def test_revenue_posted_balance_counts_only_posted(api):
    """PRD §2.5: "The **posted** variant is the default and is exactly what the
    stored `posted_balance_cents` holds: it counts only `POSTED` entries."

    Design: Difficulty/dual_variant_calc/account_balance_posted_vs_projected_revenue
    """
    rev = _revenue_with_posted_and_draft()
    bal = validate_success(api.get_account_balance(rev, ACCT))
    assert bal["posted_balance_cents"] == 100000, \
        f"posted should ignore the draft, expected 100000, got {bal['posted_balance_cents']}"


def test_revenue_projected_balance_adds_draft(api):
    """PRD §2.5: "The **projected** variant, requested with the `include_drafts`
    query flag set to true, runs the identical signed-sum arithmetic but over lines
    whose parent entry is in either `POSTED` or `DRAFT` status — that is, draft
    entries are projected as if they had been posted."

    Design: Difficulty/dual_variant_calc/account_balance_posted_vs_projected_revenue
    """
    rev = _revenue_with_posted_and_draft()
    bal = validate_success(
        api.get_account_balance(rev, ACCT, params={"include_drafts": "true"}))
    assert bal["projected_balance_cents"] == 130000, \
        f"projected should add the 30000 draft, expected 130000, got {bal['projected_balance_cents']}"
    assert bal["projected_balance_cents"] - bal["posted_balance_cents"] == 30000, \
        "projected minus posted must equal the draft amount 30000"


def test_financial_statements_net_income_computed(api):
    """PRD §3.10: "It returns the company's `trial_balance_status`, the
    `total_revenue_cents`, the `total_expense_cents`, the `net_income_cents`, the
    `total_assets_cents`, the `total_liabilities_cents`, and the
    `total_equity_cents`."

    Design: Corner/endpoints/financial_statements_net_income_computed
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    per = env["period"]["id"]
    accts = env["accounts"]
    create_posted_entry(co, per,
                        [(accts["ar"]["id"], 100000, 0), (accts["rev"]["id"], 0, 100000)],
                        memo="sale")
    create_posted_entry(co, per,
                        [(accts["exp"]["id"], 30000, 0), (accts["cash"]["id"], 0, 30000)],
                        memo="exp")
    fs = validate_success(api.get_financial_statements(co, AUDITOR))
    assert fs["total_revenue_cents"] == 100000, f"got {fs['total_revenue_cents']}"
    assert fs["total_expense_cents"] == 30000, f"got {fs['total_expense_cents']}"
    assert fs["net_income_cents"] == 70000, f"got {fs['net_income_cents']}"
