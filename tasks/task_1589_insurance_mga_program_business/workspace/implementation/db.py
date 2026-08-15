"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding of any kind.
The platform never consults wall-clock time: every timestamp derives from the
logical clock, which starts at 2026-08-01T00:00:00Z and advances only via
POST /mga/_clock/set_current_utc (PRD section 2.5).
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.carriers = {}
        self.tpas = {}
        self.programs = {}
        self.guidelines = {}
        self.capacity_allocations = {}
        self.rate_filings = {}
        self.policies = {}
        self.claims = {}
        self.tpa_appointments = {}
        self.trust_ledger = {}
        self.bordereaux = {}
        self.carrier_audits = {}
        self.loss_evaluations = {}
        self.seq = 0
        # Logical clock: fixed startup instant, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    STORE.seq += 1
    return STORE.seq


def now_dt():
    return STORE.clock


def format_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def now_iso():
    return format_dt(STORE.clock)


def new_entity():
    ts = now_iso()
    return {
        'id': new_id(),
        'created_at': ts,
        'updated_at': ts,
        'version': 1,
        '_seq': next_seq(),
    }


def new_ledger_entity():
    """TrustLedgerEntry: immutable, append-only; id + created_at only (no
    updated_at, no version) per PRD section 2.4."""
    return {
        'id': new_id(),
        'created_at': now_iso(),
        '_seq': next_seq(),
    }


def touch(entity):
    entity['updated_at'] = now_iso()
    entity['version'] += 1
