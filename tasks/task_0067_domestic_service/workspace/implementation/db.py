"""In-memory data store with deterministic clock support."""
import uuid
from datetime import datetime, timedelta, timezone
from threading import RLock


class Store:
    def __init__(self):
        self.lock = RLock()
        # Entity tables keyed by id
        self.personnel = {}            # id -> ServicePersonnel dict
        self.certifications = {}       # id -> SkillCertification dict
        self.service_items = {}        # id -> ServiceItem dict
        self.customers = {}            # id -> Customer dict
        self.orders = {}               # id -> Order dict
        self.recurring_orders = {}     # id -> RecurringOrder dict
        self.executions = {}           # id -> ServiceExecution dict
        self.executions_by_order = {}  # order_id -> ServiceExecution id
        self.abnormal_events = {}      # id -> AbnormalEvent dict
        self.ratings = {}              # id -> OrderRating dict
        self.ratings_by_order = {}     # order_id -> OrderRating id
        self.settlement_entries = {}   # id -> SettlementLedgerEntry dict
        self.insurance_claims = {}     # id -> InsuranceClaim dict
        self.audit_log = {}            # id -> AuditLogEntry dict
        self.evidence_items = {}       # claim_id -> list of evidence dicts

        # Per-order in-memory exclusion sets for redispatch
        self.exclusion_sets = {}       # order_id -> set(personnel_id)

        # Logical clock offset in seconds for test-driving
        self._clock_offset_seconds = 0.0

    # ----- ID / clock helpers -----
    def new_id(self) -> str:
        return str(uuid.uuid4())

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self._clock_offset_seconds)

    def now_iso(self) -> str:
        n = self.now()
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"

    def advance_clock(self, seconds: float):
        self._clock_offset_seconds += seconds


# Singleton store
store = Store()


def iso_to_dt(s):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str):
        return None
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # Try to truncate fractional seconds beyond microsecond precision
        try:
            # split on '+' or '-' timezone
            return None
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dt_to_iso(dt) -> str:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
