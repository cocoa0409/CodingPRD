"""In-memory data store (PRD benchmark: no disk persistence, no seeding).

The store starts completely empty on every process boot. Every entity is
created exclusively through the declared API surface. No seed_* helpers,
no preloaded rows, no disk I/O.
"""

import itertools
import uuid

from logical_clock import CLOCK, format_iso

# Entity tables: id -> dict
STORE = {
    "programs": {},
    "markets": {},
    "vendors": {},
    "shoppers": {},
    "market_days": {},
    "token_batches": {},
    "issuances": {},
    "tokens": {},
    "submissions": {},
    "fraud_cases": {},
    "settlement_runs": {},
}

# Idempotency-Key -> {"fingerprint": str, "status": int, "body": dict}
IDEMPOTENCY = {}

# Global insertion sequence — used as the final deterministic tie-break for
# ordering (the spec forbids id-based tie-breaks; created_at may tie because
# all timestamps come from the logical clock).
SEQ = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Attach common system fields (PRD §2.5) to a freshly created entity."""
    now = CLOCK.now()
    entity["id"] = new_id()
    entity["created_at"] = format_iso(now)
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next(SEQ)
    return entity


def touch(entity):
    """Register a mutation: version +1 and updated_at refresh (PRD §2.5)."""
    entity["version"] = int(entity.get("version", 1)) + 1
    entity["updated_at"] = format_iso(CLOCK.now())


def idem_marker(key, fingerprint, status, envelope_body):
    """Store a successful (2xx) response for idempotent replay (PRD §2.7)."""
    if 200 <= int(status) < 300:
        IDEMPOTENCY[key] = {
            "fingerprint": fingerprint,
            "status": int(status),
            "body": envelope_body,
        }
