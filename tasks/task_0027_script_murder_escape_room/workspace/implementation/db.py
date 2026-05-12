"""In-memory data store and shared utilities."""
import uuid
from datetime import datetime, timezone
from typing import Optional


# ---- Constants ----
FREE_CANCEL_LEAD_MINUTES = 1440
LATE_CANCEL_LEAD_MINUTES = 120
LATE_CANCEL_PAID_REFUND_BPS = 5000
MATCH_CUTOFF_MINUTES = 60
DEPOSIT_HOLD_TTL_MINUTES = 15
START_GRACE_MINUTES = 30
NO_SHOW_BAN_THRESHOLD = 3
NO_SHOW_WINDOW_DAYS = 30
SHORT_COMMENT_THRESHOLD = 50
REPEAT_REVIEW_THRESHOLD = 3
SCORE_SPREAD_THRESHOLD = 3
SPAM_SIGNAL_SOFT = 2
SPAM_SIGNAL_HARD_BLOCK = 4
MAX_MODERATION_ROUNDS = 3


# ---- ID and timestamp helpers ----
def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    from clock import clock
    n = clock.now()
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}" + "Z"


def now_dt() -> datetime:
    from clock import clock
    return clock.now()


def parse_iso(ts: str) -> datetime:
    if not isinstance(ts, str):
        raise ValueError("timestamp must be string")
    s = ts.strip()
    # Accept Z suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception as e:
        raise ValueError(f"invalid iso8601: {ts}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


# ---- Store ----
class Store:
    def __init__(self):
        # entity dict id -> dict
        self.venues = {}
        self.rooms = {}
        self.themes = {}
        self.maintenance_windows = {}
        self.session_slots = {}
        self.bookings = {}
        self.waitlist_entries = {}
        self.players = {}
        self.staff_members = {}
        self.staff_assignments = {}
        self.reviews = {}
        self.settlement_runs = {}
        self.audit_log = []  # list of dicts in insertion order
        # idempotency: keys -> stored result (booking dict)
        self.payment_idempotency = {}  # key=(booking_id, idempotency_key) -> resolved booking snapshot id

    def get(self, table: dict, key: str):
        return table.get(key)


store = Store()


def make_common(extra: dict | None = None, with_version: bool = True) -> dict:
    """Generate id, created_at, updated_at, version."""
    base = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if with_version:
        base["version"] = 1
    if extra:
        base.update(extra)
    return base


def bump(entity: dict):
    entity["updated_at"] = now_iso()
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
