"""In-memory data store.

Every collection is a dict keyed by the entity id. The store starts EMPTY on
every process boot — nothing is seeded, preloaded, or hardcoded. Tests build all
state through the API surface.

Common system fields (PRD §2.4):
  - id: server-minted UUID, no type prefix
  - created_at: ISO 8601 UTC with three fractional digits, set on create
  - updated_at: refreshed on every mutation
  - version: integer starting at 1, +1 on every mutation
JournalLine is the exception: only id + created_at (PRD §2.4).
"""
import uuid

from response import now_iso

# Each collection is a plain dict {id: record_dict}. Insertion order is preserved
# (Python 3.7+), which we rely on as a stable proxy for created_at-ascending sort
# given that several records may share the same millisecond timestamp.
companies = {}
accounts = {}
accounting_periods = {}
journal_entries = {}
journal_lines = {}
bank_accounts = {}
bank_feed_transactions = {}
reconciliations = {}
customers = {}
invoices = {}
invoice_payments = {}
vendors = {}
bills = {}
tax_rates = {}

# Monotonic counter to break created_at ties for deterministic ascending sort.
_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def make_record(fields, with_version=True):
    """Build a fresh record dict with system common fields populated."""
    ts = now_iso()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["_seq"] = _next_seq()
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on mutation (PRD §2.6)."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] = rec.get("version", 1) + 1


def reset_all():
    for coll in (
        companies, accounts, accounting_periods, journal_entries, journal_lines,
        bank_accounts, bank_feed_transactions, reconciliations, customers,
        invoices, invoice_payments, vendors, bills, tax_rates,
    ):
        coll.clear()
    global _seq
    _seq = 0
