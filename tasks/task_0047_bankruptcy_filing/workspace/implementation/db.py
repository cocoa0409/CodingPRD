"""In-memory data store.

PRD section 2.4: every persisted resource carries a server-minted UUID id (no
type prefix), a created_at (ISO 8601 UTC, three fractional digits), an
updated_at (refreshed on every mutation), and an integer version that starts at
1 and increments by one on every mutation.

The store starts EMPTY on every process boot. Nothing is seeded. All state is
built by tests via the API surface.
"""

import threading
import uuid
from datetime import datetime, timezone


# One dict per entity collection, keyed by id.
debtors = {}
creditors = {}
trustees = {}
cases = {}
means_tests = {}
schedules = {}
debts = {}
meetings = {}
claims = {}
plans = {}
plan_payments = {}
stay_relief_motions = {}

# Uniqueness index for Debtor.email (PRD 3.1: email unique across debtors).
debtor_emails = {}

lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits, 'Z' suffix."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(obj):
    """Set audit fields on a freshly created resource."""
    ts = now_iso()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def touch(obj):
    """Record a mutation: refresh updated_at and bump version by one.

    PRD 2.4 / 2.5: every mutation, including cascaded side effects, refreshes
    updated_at and increments version by exactly one.
    """
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
