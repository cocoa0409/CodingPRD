"""In-memory data store for the WIC Benefits Management API.

Starts EMPTY on every boot — no seeding, no preload, no persistence. Every entity
any test needs is constructed through the declared API surface. Per-test-server
isolation re-imports this module fresh, so all state is wiped between tests.

Timestamp model (PRD §2.4 vs §2.5): `created_at`/`updated_at` are server-minted
wall-clock instants used for record bookkeeping and list ordering. The *domain*
clock that drives temporal decisions (cert expiry, proration, no-show, reinstate
gate) is each Agency's own `current_utc` field — a separate value, defaulting to
the epoch and advanced only via POST /_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

from response import iso_ms


class DB:
    def __init__(self):
        self.agencies = {}
        self.clinics = {}
        self.vendors = {}
        self.households = {}
        self.participants = {}
        self.applications = {}
        self.income_records = {}
        self.certifications = {}
        self.food_prescriptions = {}
        self.ebt_accounts = {}
        self.redemptions = {}
        self.clinic_appointments = {}
        self.peer_sessions = {}
        self._seq = 0

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def _now():
    return datetime.now(timezone.utc)


def new_common(with_version=True):
    """System-managed common fields.

    `version` starts at 1 and increments on every mutation. IncomeRecord and
    Redemption are append-only evidence (with_version=False): they carry only
    id + created_at, no updated_at and no version (PRD §2.4).
    """
    now = _now()
    fields = {
        "id": db.new_id(),
        "created_at": iso_ms(now),
        "_created_seq": db.next_seq(),  # monotonic creation-order tie-break for sorting
    }
    if with_version:
        fields["updated_at"] = iso_ms(now)
        fields["version"] = 1
    return fields


def touch(entity):
    """Refresh updated_at and bump version by one — every mutation of a
    versioned entity, including derived-field changes (PRD §2.4)."""
    entity["updated_at"] = iso_ms(_now())
    entity["version"] = entity.get("version", 1) + 1
