"""Double-entry ledger engine: posted-balance recomputation, trial balance,
journal-entry posting and the reversal cascade (PRD §2.5, §2.6, §3.4).

All balance math is exact integer cents — no rounding (PRD §2.8).
"""
import db

DEBIT_POSITIVE_TYPES = {"ASSET", "EXPENSE"}  # signed = debit - credit
# LIABILITY, EQUITY, REVENUE: signed = -(debit - credit)

# Entries whose lines have "taken effect" in the ledger. Per PRD §2.6, voiding
# an entry does NOT erase it — the original's lines remain in effect and a
# compensating REVERSAL (also POSTED) cancels them, so the original + reversal
# net to zero and the trial-balance invariant survives. Hence a VOIDED entry's
# lines are still counted; the reversal does the canceling.
EFFECTIVE_STATUSES = {"POSTED", "VOIDED"}


def _signed_contribution(account_type, debit_cents, credit_cents):
    natural = debit_cents - credit_cents
    if account_type in DEBIT_POSITIVE_TYPES:
        return natural
    return -natural


def _lines_for_entry(entry_id):
    return [ln for ln in db.journal_lines.values() if ln["journal_entry_id"] == entry_id]


def account_balance(account_id, include_drafts=False):
    """Signed posted-balance arithmetic for one account.

    posted variant: POSTED entries only.
    projected variant (include_drafts): POSTED + DRAFT entries.
    """
    acct = db.accounts[account_id]
    statuses = set(EFFECTIVE_STATUSES)
    if include_drafts:
        statuses.add("DRAFT")
    total = 0
    for ln in db.journal_lines.values():
        if ln["account_id"] != account_id:
            continue
        entry = db.journal_entries.get(ln["journal_entry_id"])
        if not entry or entry["status"] not in statuses:
            continue
        total += _signed_contribution(
            acct["account_type"], ln["debit_cents"], ln["credit_cents"]
        )
    return total


def recompute_account_balance(account_id):
    """Recompute and store posted_balance_cents from effective (POSTED/VOIDED)
    lines (see EFFECTIVE_STATUSES and account_balance).

    Per PRD §2.6 this is a server-managed mutation of a derived field, so the
    account's updated_at/version advance.
    """
    acct = db.accounts.get(account_id)
    if not acct:
        return
    new_balance = account_balance(account_id, include_drafts=False)
    if acct["posted_balance_cents"] != new_balance:
        acct["posted_balance_cents"] = new_balance
        db.touch(acct)


def recompute_balances_for_entry(entry_id):
    """Recompute posted_balance_cents for every account touched by the entry."""
    account_ids = {ln["account_id"] for ln in _lines_for_entry(entry_id)}
    for aid in account_ids:
        recompute_account_balance(aid)


def company_total_posted_sides(company_id):
    """Sum of POSTED debit_cents and POSTED credit_cents across the company's
    accounts (PRD §2.5 trial balance)."""
    company_account_ids = {
        aid for aid, a in db.accounts.items() if a["company_id"] == company_id
    }
    total_debit = 0
    total_credit = 0
    for ln in db.journal_lines.values():
        if ln["account_id"] not in company_account_ids:
            continue
        entry = db.journal_entries.get(ln["journal_entry_id"])
        if not entry or entry["status"] not in EFFECTIVE_STATUSES:
            continue
        total_debit += ln["debit_cents"]
        total_credit += ln["credit_cents"]
    return total_debit, total_credit


def recompute_trial_balance(company_id):
    company = db.companies.get(company_id)
    if not company:
        return
    td, tc = company_total_posted_sides(company_id)
    status = "BALANCED" if td == tc else "OUT_OF_BALANCE"
    if company["trial_balance_status"] != status:
        company["trial_balance_status"] = status
        db.touch(company)


def add_line(entry_id, account_id, debit_cents, credit_cents, line_memo=""):
    """Create a JournalLine (id + created_at only; PRD §2.4)."""
    rec = db.make_record(
        {
            "journal_entry_id": entry_id,
            "account_id": account_id,
            "debit_cents": debit_cents,
            "credit_cents": credit_cents,
            "line_memo": line_memo,
        },
        with_version=False,
    )
    db.journal_lines[rec["id"]] = rec
    return rec


def recompute_entry_totals(entry):
    lines = _lines_for_entry(entry["id"])
    entry["total_debit_cents"] = sum(ln["debit_cents"] for ln in lines)
    entry["total_credit_cents"] = sum(ln["credit_cents"] for ln in lines)


def create_system_entry(company_id, period_id, entry_date, source, memo="",
                        reverses_journal_entry_id=None,
                        created_by_user_id="system"):
    """Create a system journal entry already destined to be POSTED. Returns the
    entry record (status still DRAFT until post_system_entry)."""
    rec = db.make_record(
        {
            "company_id": company_id,
            "period_id": period_id,
            "entry_date": entry_date,
            "memo": memo,
            "source": source,
            "created_by_user_id": created_by_user_id,
            "reverses_journal_entry_id": reverses_journal_entry_id,
            "total_debit_cents": 0,
            "total_credit_cents": 0,
            "status": "DRAFT",
        }
    )
    db.journal_entries[rec["id"]] = rec
    return rec


def post_entry(entry):
    """Drive an entry to POSTED and run the balance/trial-balance recompute
    cascade (PRD §2.6)."""
    recompute_entry_totals(entry)
    entry["status"] = "POSTED"
    db.touch(entry)
    recompute_balances_for_entry(entry["id"])
    recompute_trial_balance(entry["company_id"])


def reverse_entry(entry):
    """CASCADE B (PRD §2.6): create a REVERSAL entry with every line's debit and
    credit swapped, post it immediately, recompute affected balances and the
    company trial balance. Returns the reversal entry. Does NOT mutate the
    original's status (callers set VOIDED/etc. as appropriate)."""
    reversal = create_system_entry(
        company_id=entry["company_id"],
        period_id=entry["period_id"],
        entry_date=entry["entry_date"],
        source="REVERSAL",
        memo="Reversal of %s" % entry["id"],
        reverses_journal_entry_id=entry["id"],
    )
    for ln in _lines_for_entry(entry["id"]):
        add_line(
            reversal["id"],
            ln["account_id"],
            debit_cents=ln["credit_cents"],
            credit_cents=ln["debit_cents"],
            line_memo=ln["line_memo"],
        )
    post_entry(reversal)
    return reversal
