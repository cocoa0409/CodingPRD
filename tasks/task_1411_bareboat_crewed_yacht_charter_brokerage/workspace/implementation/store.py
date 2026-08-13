"""In-memory data store and the logical clock.

The store starts completely empty on every boot (PRD benchmark contract):
no seeding, no preloading. The logical clock starts at exactly
2026-08-01T00:00:00Z and moves only via POST /_clock/set_current_utc
(PRD §2.5); it never falls back to wall-clock time.
"""

from datetime import datetime, timezone

from util import new_uuid

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

db = {
    "operators": {},
    "brokers": {},
    "clients": {},
    "yachts": {},
    "availability_blocks": {},
    "charter_requests": {},
    "charter_agreements": {},
    "escrow_accounts": {},
    "escrow_movements": {},
    "expenses": {},
    "itinerary_legs": {},
    "port_permits": {},
    "insurance_certificates": {},
    "commission_statements": {},
}


class _LogicalClock:
    def __init__(self):
        self.current = CLOCK_DEFAULT

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


clock = _LogicalClock()

_seq = [0]


def next_seq():
    """Monotonic insertion counter; tie-breaks equal created_at values."""
    _seq[0] += 1
    return _seq[0]


def new_record(common=True):
    """Mint a record skeleton. `common` adds updated_at/version (absent on
    EscrowMovement and CommissionStatement per PRD §2.4)."""
    rec = {"id": new_uuid(), "created_at": clock.now(), "_seq": next_seq()}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def mutate(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.9)."""
    rec["version"] = rec.get("version", 0) + 1
    rec["updated_at"] = clock.now()
