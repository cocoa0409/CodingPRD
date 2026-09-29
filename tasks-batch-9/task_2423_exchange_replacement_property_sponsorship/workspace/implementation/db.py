"""In-memory data store.

Every collection starts empty on every boot; nothing is ever seeded,
preloaded or written to disk.
"""
import clock
from util import new_uuid

# --- collections ----------------------------------------------------------
properties = {}
trusts = {}
offerings = {}
investors = {}
exchange_files = {}
identifications = {}
subscriptions = {}
loans = {}
leases = {}
ledger_entries = {}
capital_needs = {}
distributions = {}
allocations = {}
tax_statements = {}
exit_events = {}
exit_consents = {}

COLLECTIONS = {
    "property": properties,
    "trust": trusts,
    "offering": offerings,
    "investor": investors,
    "exchange_file": exchange_files,
    "identification": identifications,
    "subscription": subscriptions,
    "loan": loans,
    "lease": leases,
    "ledger_entry": ledger_entries,
    "capital_need": capital_needs,
    "distribution": distributions,
    "allocation": allocations,
    "tax_statement": tax_statements,
    "exit_event": exit_events,
    "exit_consent": exit_consents,
}

_counter = {"n": 0}


def _next_seq():
    _counter["n"] += 1
    return _counter["n"]


def new_row(collection, fields, journal=False):
    """Create a row with the common fields of PRD 2.5.

    Journal-only rows (TrustLedgerEntry, DistributionAllocation, ExitConsent)
    carry only ``id`` and ``created_at``: no ``updated_at`` and no ``version``.
    """
    now = clock.now()
    row = {"id": new_uuid(), "created_at": now}
    if not journal:
        row["updated_at"] = now
        row["version"] = 1
    row.update(fields)
    row["_seq"] = _next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """Record a mutation: bump ``version`` by exactly one, restamp ``updated_at``.

    At most one bump per row per request, so that a single API operation
    advances a row's version by exactly one no matter how many derived
    fields it recomputes.
    """
    if row is None or "version" not in row:
        return row
    try:
        from flask import g, has_request_context
        if has_request_context():
            seen = getattr(g, "_touched", None)
            if seen is None:
                seen = set()
                g._touched = seen
            if row["id"] in seen:
                row["updated_at"] = clock.now()
                return row
            seen.add(row["id"])
    except Exception:  # pragma: no cover - defensive
        pass
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = clock.now()
    return row


def serialize(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sorted_rows(collection):
    """Default list order: created_at ascending, insertion order as tie-break."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def find(collection, **filters):
    out = []
    for row in sorted_rows(collection):
        ok = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out
