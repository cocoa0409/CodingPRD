"""In-memory data store. All state lives in process memory and is wiped on
every fresh boot (start.sh re-invocation). No seeding, no preload.
"""
import uuid

from clock import parse_iso, to_iso_z, DEFAULT_CLOCK


def logical_now():
    """Current logical-clock value, normalized to ISO 8601 UTC with three
    fractional digits. The entire system is time-driven by this logical clock
    (PRD §1, §3.9), so created_at/updated_at are stamped from it — keeping all
    temporal comparisons (warranty, RUL, deadlines, report dates) coherent.
    """
    return to_iso_z(parse_iso(db.current_utc))


class DB(object):
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.patients = {}
        self.physicians = {}
        self.suppliers = {}
        self.prescriptions = {}
        self.device_orders = {}
        self.prior_auths = {}
        self.claim_lines = {}
        self.fabrication_milestones = {}
        self.adjustments = {}
        self.repair_requests = {}
        self.compliance_checks = {}
        self.clock_states = {}
        # Logical clock value (ISO 8601 UTC string). Startup default per PRD §3.9.
        self.current_utc = DEFAULT_CLOCK
        # Monotonic sequence to provide a stable creation order for sorting even
        # when many records are created within the same millisecond.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


def base_common_fields():
    """id/created_at/updated_at/version for full-common-field entities.

    `_seq` is an internal sort key (creation order) never exposed in output.
    """
    ts = logical_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def base_audit_fields():
    """id/created_at only (ComplianceCheck, ClockState)."""
    return {
        "id": new_id(),
        "created_at": logical_now(),
        "_seq": db.next_seq(),
    }


# Single global store instance — populated only via the declared API surface.
db = DB()
