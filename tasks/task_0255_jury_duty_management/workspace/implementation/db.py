"""In-memory data store (PRD §2.4).

All state lives in module-level dicts keyed by UUID. The store starts EMPTY on
every process boot — nothing is seeded, preloaded, or hardcoded. Every entity is
constructed by tests via the declared API surface. Because the test harness
restarts the server before each test (`--isolation per-test-server`), a fresh
import of this module is a clean slate.

System-managed fields per PRD §2.4:
  - mutable aggregates carry id, created_at, updated_at, version (starts at 1)
  - append-only audit rows (QualificationResponse, CheckIn, Strike) carry only
    id and created_at.
"""
import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Collections — one dict per entity, keyed by id.
# ---------------------------------------------------------------------------
service_terms = {}
jurors = {}
summonses = {}
qualification_responses = {}
dispositions = {}
trials = {}
panels = {}
panel_assignments = {}
check_ins = {}
strikes = {}
pay_vouchers = {}

# A stable monotone insertion counter so created_at ties can be broken
# deterministically (created_at ASC, then insertion sequence ASC). Two rows
# created within the same millisecond still keep a stable, auditable order.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def utcnow_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq)
