"""In-memory data store, logical clock, and low-level helpers.

Storage is process-local Python dicts only. Nothing is persisted and no
entities are seeded at startup — the store is empty on every boot.
"""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta

# --------------------------------------------------------------------------
# Constants (from PRD / SCAFFOLD)
# --------------------------------------------------------------------------
FREE_SHIP_MIN_MEALS = 12
REFEREE_DISCOUNT_PCT = "0.15"          # applied per line, round-half-up
REFERRAL_BASE_CENTS = 2000
PREMIUM_BONUS_CENTS = 1500
PREMIUM_MIN_MEALS = 12
LINE_BUFFER_MINUTES = 30               # kitchen-line cleaning buffer
REFERRAL_EXPIRY_DAYS = 30

KNOWN_ROLES = {"PlatformAdmin", "Customer", "Anonymous"}
LEDGER_REASONS = {"REFERRAL_REWARD", "SWAP_CREDIT", "REFUND_CREDIT", "CREDIT_APPLIED"}

CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0)  # naive == UTC


class DB:
    """All mutable state lives here so a fresh process starts empty."""

    def __init__(self):
        self.zones = {}
        self.plans = {}
        self.meals = {}
        self.runs = {}
        self.customers = {}
        self.subscriptions = {}
        self.pause_windows = {}
        self.plan_changes = {}
        self.boxes = {}
        self.box_items = {}
        self.referrals = {}
        self.ledger = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self._codes = set()  # minted referral codes

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def now_clock():
    return db.clock


def format_ms(dt):
    """ISO 8601 UTC with three fractional digits and a trailing Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def format_sec(dt):
    """Second-resolution ISO 8601 UTC (trailing Z)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_flexible(dt):
    if dt.microsecond:
        return format_ms(dt)
    return format_sec(dt)


def parse_iso(s):
    """Parse an ISO 8601 instant into a naive-UTC datetime. Returns None on failure."""
    if not isinstance(s, str) or not s:
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(s):
    """Parse a YYYY-MM-DD date into a date object. Returns None on failure."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Identity / envelope helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def mint_referral_code():
    while True:
        code = "REF" + "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        if code not in db._codes:
            db._codes.add(code)
            return code


# --------------------------------------------------------------------------
# Common resource field helpers
# --------------------------------------------------------------------------
def base_fields(mutable=True):
    """id + created_at (+ updated_at/version when mutable)."""
    ts = format_ms(now_clock())
    ent = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if mutable:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def touch(ent):
    """Refresh updated_at to now and bump version by one (a mutation)."""
    ent["updated_at"] = format_ms(now_clock())
    ent["version"] = ent.get("version", 1) + 1
