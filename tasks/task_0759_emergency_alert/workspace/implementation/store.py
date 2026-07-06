"""In-memory data store, logical clock, and shared helpers.

Every process boot starts with an empty store and the logical clock pinned to
the spec default 2026-03-01T00:00:00Z. NOTHING is seeded here.
"""
import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD calculations)
# ---------------------------------------------------------------------------
SMS_SEGMENT_SIZE = 160
DEG_TO_M = 111320
RETRY_BASE_DELAY_SEC = 60
RETRY_MAX_BACKOFF_SEC = 3600
RETRY_MAX_ATTEMPTS = 3
THROTTLE_WINDOW_MINUTES = 60
DRILL_BUFFER_MINUTES = 30

SEVERITY_FACTOR = {"INFO": 1, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 4}

ROLES = {"Dispatcher", "Approver", "ContactAdmin", "Contact", "Integrator"}
LANGS = {"EN", "ES", "ZH", "VI"}
CHANNEL_TYPES = {"SMS", "VOICE", "EMAIL", "IPAWS"}
SEVERITIES = {"INFO", "ADVISORY", "WARNING", "CRITICAL"}


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self.contacts = {}
        self.channels = {}
        self.groups = {}
        self.subscriptions = {}
        self.templates = {}
        self.alerts = {}
        self.localizations = {}
        self.notifications = {}
        self.gateways = {}
        self.maintenance_windows = {}
        self.drills = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# ID / time helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_token():
    return uuid.uuid4().hex


def request_id():
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def parse_iso(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    t = value.strip()
    if not t:
        raise ValueError("empty")
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now():
    return db.clock


# ---------------------------------------------------------------------------
# Common-field lifecycle
# ---------------------------------------------------------------------------
def stamp_new(entity):
    """Attach id / created_at / updated_at / version / _seq if absent."""
    t = db.clock
    entity.setdefault("id", new_id())
    entity["created_at"] = t
    entity["updated_at"] = t
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Register a mutation: refresh updated_at, bump version."""
    entity["updated_at"] = db.clock
    entity["version"] = entity.get("version", 1) + 1
    return entity


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ceil_div(n, d):
    return -(-n // d)


# ---------------------------------------------------------------------------
# Throttle window
# ---------------------------------------------------------------------------
def current_window_bounds():
    c = db.clock
    start = c.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=THROTTLE_WINDOW_MINUTES)
    return start, end


# ---------------------------------------------------------------------------
# Derived counters (computed on read)
# ---------------------------------------------------------------------------
PENDING_STATES = {"QUEUED", "SENT", "RETRYING", "FAILED"}


def alert_pending_count(alert_id):
    return sum(
        1
        for n in db.notifications.values()
        if n["alert_id"] == alert_id and n["delivery_status"] in PENDING_STATES
    )


def group_member_count(group_id):
    return sum(
        1
        for s in db.subscriptions.values()
        if s["subscription_type"] == "GROUP"
        and s["group_id"] == group_id
        and s["status"] == "ACTIVE"
    )


def gateway_window_count(gateway):
    start, end = current_window_bounds()
    ct = gateway["channel_type"]
    total = 0
    for n in db.notifications.values():
        if n["channel_type"] != ct:
            continue
        if n["delivery_status"] == "SUPPRESSED":
            continue
        ca = n["created_at"]
        if start <= ca < end:
            total += 1
    return total


def gateway_for_channel(channel_type):
    """Return a gateway serving channel_type (prefer ONLINE), else None."""
    match = None
    for g in db.gateways.values():
        if g["channel_type"] == channel_type:
            if g["status"] == "ONLINE":
                return g
            if match is None:
                match = g
    return match


def contact_reliability(contact_id, mode="optimistic"):
    denom = 0
    optimistic = 0
    strict = 0
    for n in db.notifications.values():
        if n["contact_id"] != contact_id:
            continue
        st = n["delivery_status"]
        if st in {"SENT", "DELIVERED", "FAILED", "EXHAUSTED", "RETRYING"}:
            denom += 1
            if st in {"SENT", "DELIVERED", "RETRYING"}:
                optimistic += 1
            if st == "DELIVERED":
                strict += 1
    if denom == 0:
        return 0.00
    hits = strict if mode == "strict" else optimistic
    return round_half_up_2(hits / denom)


def geo_distance_m(lat1, lon1, lat2, lon2):
    dlat_m = (lat1 - lat2) * DEG_TO_M
    dlon_m = (lon1 - lon2) * DEG_TO_M
    raw = math.sqrt(dlat_m * dlat_m + dlon_m * dlon_m)
    return round_half_up_int(raw)
