"""In-memory data store.

All state lives in module-level dicts keyed by id. There is NO persistence,
no SQLite, no disk dump — re-launching the process via start.sh wipes every
byte of state. NOTHING is seeded here; every entity is created by a test via
the declared API surface.
"""
import itertools
import threading
import uuid

from response import now_iso

# A single coarse lock guards all mutations so cascade side-effects are atomic
# under the concurrent test harness.
LOCK = threading.RLock()

# Entity tables (id -> record dict). Empty at boot; never seeded.
applications = {}
awards = {}
indirect_cost_rates = {}
subawards = {}
restricted_funds = {}
drawdowns = {}
fund_allocations = {}
financial_reports = {}
progress_reports = {}
single_audits = {}
audit_findings = {}

# Monotonic counter to break created_at ties deterministically (creation order).
_seq = itertools.count(1)


def reset():
    """Clear every table. Used only as a defensive no-op safety; the process
    starts empty regardless."""
    for table in (
        applications, awards, indirect_cost_rates, subawards, restricted_funds,
        drawdowns, fund_allocations, financial_reports, progress_reports,
        single_audits, audit_findings,
    ):
        table.clear()


def new_id():
    """Server-minted UUID, no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp_create(record):
    """Apply common system fields on creation (PRD §2.4): id, created_at,
    updated_at, version=1, plus a hidden _seq for stable ordering."""
    ts = now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def stamp_create_light(record):
    """Lighter create stamp for FundAllocation (PRD §2.4): id + created_at
    only — no updated_at, no version."""
    record.setdefault("id", new_id())
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Bump updated_at and version on mutation (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
