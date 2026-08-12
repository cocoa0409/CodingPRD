"""In-memory store. The store starts EMPTY on every boot: no seeding, no
preload, no disk persistence. All records are plain dicts; keys starting
with '_' are internal (never serialized)."""
import itertools
import uuid

from flask import g

from clock import now_ts

_seq = itertools.count(1)


class Store:
    def __init__(self):
        self.customers = {}
        self.contracts = {}
        self.pobs = {}
        self.ssp_prices = {}
        self.estimates = {}
        self.modifications = {}
        self.clauses = {}
        self.review_tasks = {}
        self.invoices = {}
        self.periods = {}
        self.entries = {}
        self.cost_entries = {}
        self.packs = {}


STORE = Store()


def make_rec(table, fields, lean=False):
    """Create a record. Common fields: id/created_at (+ updated_at/version
    unless lean). RevenueEntry and CostEntry are lean (append-only)."""
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now_ts()
    if not lean:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next(_seq)
    table[rec["id"]] = rec
    return rec


def mark(rec, bump=True):
    """Apply a mutation's bookkeeping eagerly: at most one version bump per
    record per request (deduped via the request-scoped dirty set), plus an
    updated_at refresh. bump=False refreshes updated_at only (system-driven
    transitions that the PRD excludes from the contract version counter)."""
    if "version" not in rec:
        return
    dirty = g.__dict__.setdefault("_dirty", {})
    prev = dirty.get(rec["id"])
    if prev is None:
        if bump:
            rec["version"] += 1
        rec["updated_at"] = now_ts()
        dirty[rec["id"]] = bump
    else:
        dirty[rec["id"]] = prev or bump


def commit_dirty():
    # Bumps were applied eagerly in mark(); just clear the dedupe set.
    g.__dict__.pop("_dirty", None)


def discard_dirty():
    g.__dict__.pop("_dirty", None)


def pub(rec):
    """Public view: strip internal keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_created(recs):
    """created_at ascending; creation order breaks ties (identical logical
    timestamps). Ids never participate in ordering."""
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))
