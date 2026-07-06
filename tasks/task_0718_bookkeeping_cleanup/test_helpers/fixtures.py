"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, since the server database is empty at the start of each test. Setup
calls use get_success_data() so a setup failure surfaces as a clear error.

Identity note: mark-reconciled enforces segregation of duties — the Reviewer's
X-User-ID must differ from the Bookkeeper who categorized the account. These
fixtures categorize as bookkeeper "bk-1" and sign off as reviewer "reviewer-1",
so the two identities are always distinct unless a test overrides them.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_engagement_manager_headers,
    make_bookkeeper_headers,
    make_reviewer_headers,
    make_tax_preparer_headers,
)

EM = make_engagement_manager_headers("em-1")
BK = make_bookkeeper_headers("bk-1")
RV = make_reviewer_headers("reviewer-1")
RV2 = make_reviewer_headers("reviewer-2")
TP = make_tax_preparer_headers("tp-1")


# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------

def create_client(legal_name="Test Co", entity_type="LLC", accounting_basis="ACCRUAL"):
    payload = {"legal_name": legal_name, "entity_type": entity_type, "accounting_basis": accounting_basis}
    return get_success_data(api_client.create_client(payload, EM))


def create_engagement(client_id, title="Eng", period_start="2025-01-01",
                      period_end="2025-06-30", complexity_tier="MEDIUM"):
    payload = {
        "client_id": client_id, "title": title,
        "period_start": period_start, "period_end": period_end,
        "complexity_tier": complexity_tier,
    }
    return get_success_data(api_client.create_engagement(payload, EM))


def create_client_and_engagement(accounting_basis="ACCRUAL", period_start="2025-01-01",
                                 period_end="2025-06-30", complexity_tier="MEDIUM",
                                 entity_type="LLC"):
    """Returns the freshly created DRAFT engagement (version 1)."""
    client = create_client(accounting_basis=accounting_basis, entity_type=entity_type)
    return create_engagement(
        client["id"], period_start=period_start, period_end=period_end,
        complexity_tier=complexity_tier,
    )


# ---------------------------------------------------------------------------
# Tier 1: State progression on the engagement workflow dimension
# ---------------------------------------------------------------------------

def setup_scoping_engagement(accounting_basis="ACCRUAL", period_start="2025-01-01",
                             period_end="2025-06-30", complexity_tier="MEDIUM"):
    """DRAFT -> SCOPING. Returns engagement after start-scoping (version unchanged
    semantically, re-read)."""
    eng = create_client_and_engagement(accounting_basis, period_start, period_end, complexity_tier)
    eng = get_success_data(api_client.start_scoping(eng["id"], EM))
    return eng


def setup_scoping_with_estimate(monthly_txn_rate=220, **eng_kwargs):
    """SCOPING engagement with one PROPOSED ScopeEstimate.
    Returns (engagement, estimate). engagement carries the pre-accept version."""
    eng = create_client_and_engagement(**eng_kwargs)
    eng = get_success_data(api_client.start_scoping(eng["id"], EM))
    est = get_success_data(
        api_client.create_scope_estimate(eng["id"], {"monthly_txn_rate": monthly_txn_rate}, EM)
    )
    return eng, est


def setup_reconstruction_engagement(monthly_txn_rate=220, **eng_kwargs):
    """Scope accepted -> RECONSTRUCTION. Returns the engagement read after accept."""
    eng, est = setup_scoping_with_estimate(monthly_txn_rate=monthly_txn_rate, **eng_kwargs)
    get_success_data(
        api_client.accept_scope_estimate(
            eng["id"], est["id"], {"expected_engagement_version": eng["version"]}, EM
        )
    )
    return get_success_data(api_client.get_engagement(eng["id"], EM))


# ---------------------------------------------------------------------------
# Tier 2: Account + entry building blocks inside an engagement
# ---------------------------------------------------------------------------

def add_posted_entry(engagement_id, account_id, side="DEBIT", amount_cents=1000,
                     txn_date="2025-02-01"):
    """Create a DRAFT entry on the account and post it. Returns the posted entry."""
    entry = get_success_data(api_client.create_entry(
        engagement_id,
        {"account_id": account_id, "txn_date": txn_date, "side": side, "amount_cents": amount_cents},
        BK,
    ))
    return get_success_data(api_client.post_entry(engagement_id, entry["id"], BK))


def add_account(engagement_id, account_code="1000", name="Cash",
                account_type="ASSET", is_bank_account=False):
    return get_success_data(api_client.create_account(
        engagement_id,
        {"account_code": account_code, "name": name,
         "account_type": account_type, "is_bank_account": is_bank_account},
        BK,
    ))


def add_categorized_account(engagement_id, account_code="1000", name="Cash",
                            account_type="ASSET", is_bank_account=False,
                            entry_side="DEBIT", entry_amount=1000):
    """Create account, post one entry, categorize. Returns (account, posted_entry)."""
    acct = add_account(engagement_id, account_code, name, account_type, is_bank_account)
    entry = add_posted_entry(engagement_id, acct["id"], side=entry_side, amount_cents=entry_amount)
    acct = get_success_data(api_client.categorize_account(engagement_id, acct["id"], BK))
    return acct, entry


def setup_reconstruction_with_categorized_account(account_type="ASSET",
                                                  is_bank_account=False,
                                                  entry_amount=1000, **eng_kwargs):
    """RECONSTRUCTION engagement with one CATEGORIZED account.
    Returns (engagement, account, entry)."""
    eng = setup_reconstruction_engagement(**eng_kwargs)
    acct, entry = add_categorized_account(
        eng["id"], account_type=account_type, is_bank_account=is_bank_account,
        entry_amount=entry_amount,
    )
    return eng, acct, entry


def setup_reconciliation_with_categorized_account(account_type="ASSET",
                                                  entry_amount=1000, **eng_kwargs):
    """RECONCILIATION engagement with one CATEGORIZED non-bank account.
    Returns (engagement, account, entry)."""
    eng, acct, entry = setup_reconstruction_with_categorized_account(
        account_type=account_type, is_bank_account=False, entry_amount=entry_amount, **eng_kwargs
    )
    get_success_data(api_client.advance_to_reconciliation(eng["id"], EM))
    eng = get_success_data(api_client.get_engagement(eng["id"], EM))
    return eng, acct, entry


# ---------------------------------------------------------------------------
# Tier 3: Bank reconciliation chains
# ---------------------------------------------------------------------------

def setup_bank_statement_reconciling(book_amount=340000, ending_balance_cents=350000,
                                     deposits_in_transit_cents=15000,
                                     outstanding_checks_cents=25000,
                                     statement_line_amount_cents=None,
                                     match_kind="EXACT", **eng_kwargs):
    """RECONCILIATION engagement: bank account CATEGORIZED with one posted entry,
    a statement imported and one reconciliation item created (statement RECONCILING).
    Returns (engagement, bank_account, posted_entry, statement, item)."""
    if statement_line_amount_cents is None:
        statement_line_amount_cents = book_amount
    eng = setup_reconstruction_engagement(**eng_kwargs)
    bank = add_account(eng["id"], account_code="1010", name="Checking",
                       account_type="ASSET", is_bank_account=True)
    entry = add_posted_entry(eng["id"], bank["id"], side="DEBIT", amount_cents=book_amount)
    bank = get_success_data(api_client.categorize_account(eng["id"], bank["id"], BK))
    get_success_data(api_client.advance_to_reconciliation(eng["id"], EM))
    stmt = get_success_data(api_client.create_statement(
        eng["id"],
        {"account_id": bank["id"], "statement_start": "2025-02-01",
         "statement_end": "2025-02-28", "ending_balance_cents": ending_balance_cents,
         "deposits_in_transit_cents": deposits_in_transit_cents,
         "outstanding_checks_cents": outstanding_checks_cents},
        RV,
    ))
    item = get_success_data(api_client.create_reconciliation_item(
        eng["id"], stmt["id"],
        {"ledger_entry_id": entry["id"],
         "statement_line_amount_cents": statement_line_amount_cents,
         "match_kind": match_kind},
        RV,
    ))
    return eng, bank, entry, stmt, item


def setup_bank_account_reconciled(book_amount=340000, **eng_kwargs):
    """RECONCILIATION engagement: bank account marked RECONCILED via a balanced,
    finalized statement (its entry is cash_settled).
    Returns (engagement, bank_account, posted_entry, statement)."""
    eng, bank, entry, stmt, item = setup_bank_statement_reconciling(
        book_amount=book_amount,
        ending_balance_cents=book_amount + 10000,
        deposits_in_transit_cents=15000,
        outstanding_checks_cents=25000,
        statement_line_amount_cents=book_amount,
        match_kind="EXACT",
        **eng_kwargs,
    )
    get_success_data(api_client.finalize_statement(eng["id"], stmt["id"], RV))
    bank = get_success_data(api_client.mark_reconciled(eng["id"], bank["id"], RV2))
    return eng, bank, entry, stmt


# ---------------------------------------------------------------------------
# Tier 4: Billing chains
# ---------------------------------------------------------------------------

def setup_quoted_engagement(**eng_kwargs):
    """Scope accepted then quote: billing_status QUOTED (workflow stays RECONSTRUCTION).
    Returns the engagement read after quote."""
    eng = setup_reconstruction_engagement(**eng_kwargs)
    eng = get_success_data(api_client.quote(eng["id"], EM))
    return eng


def setup_quoted_with_phases(weights, **eng_kwargs):
    """Quoted engagement with PLANNED phases for the given weight_bp list.
    Returns (engagement, [phase, ...])."""
    eng = setup_quoted_engagement(**eng_kwargs)
    phases = []
    for i, w in enumerate(weights, start=1):
        ph = get_success_data(api_client.create_phase(
            eng["id"], {"phase_index": i, "label": f"P{i}", "weight_bp": w}, EM
        ))
        phases.append(ph)
    return eng, phases


def setup_phased_engagement(weights, **eng_kwargs):
    """Quoted engagement with phases generated: billing_status PHASED, phases BILLABLE.
    Returns (engagement, [phase, ...] re-read after generate)."""
    eng, phases = setup_quoted_with_phases(weights, **eng_kwargs)
    get_success_data(api_client.generate_phases(eng["id"], EM))
    data, _ = _list_phases(eng["id"])
    by_index = {p["phase_index"]: p for p in data}
    refreshed = [by_index[i] for i in range(1, len(weights) + 1)]
    eng = get_success_data(api_client.get_engagement(eng["id"], EM))
    return eng, refreshed


def setup_single_phase_invoiced(**eng_kwargs):
    """Single-phase (weight 10000) engagement: phased, phase invoiced, awaiting payment.
    Returns (engagement, phase, invoice)."""
    eng, phases = setup_phased_engagement([10000], **eng_kwargs)
    phase = phases[0]
    invoice = get_success_data(api_client.invoice_phase(eng["id"], phase["id"], EM))
    return eng, phase, invoice


def _list_phases(engagement_id):
    resp = api_client.list_phases(engagement_id, EM)
    body = resp.json()
    return body["data"], body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 5: Exceptions
# ---------------------------------------------------------------------------

def add_exception(engagement_id, account_id, kind, severity="NORMAL",
                  doc_due_date=None, as_headers=None):
    payload = {"account_id": account_id, "kind": kind, "severity": severity}
    if doc_due_date is not None:
        payload["doc_due_date"] = doc_due_date
    headers = as_headers if as_headers is not None else BK
    return get_success_data(api_client.create_exception(engagement_id, payload, headers))


def setup_missing_doc_exception_open(**eng_kwargs):
    """RECONSTRUCTION engagement with an account and an OPEN MISSING_DOC exception.
    Returns (engagement, account, exception)."""
    eng = setup_reconstruction_engagement(**eng_kwargs)
    acct = add_account(eng["id"])
    exc = add_exception(eng["id"], acct["id"], "MISSING_DOC",
                        severity="NORMAL", doc_due_date="2025-07-15")
    return eng, acct, exc
