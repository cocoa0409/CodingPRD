"""In-memory data store, logical clock, and shared constants.

Storage is strictly in-memory: plain dicts keyed by id. Nothing is persisted
to disk, and nothing is seeded at startup — the store boots empty.
"""

import itertools
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.yaml calculations / PRD)
# ---------------------------------------------------------------------------

HOLD_HOURS = 72
STRIKE_ALLOWANCE_DAYS = 3
LOST_GRACE_DAYS = 7
USEFUL_LIFE_YEARS = 5
SALVAGE_FLOOR_PCT = "0.10"

INSURANCE_MIN_COVERAGE = {
    "THEATRE": 100000,
    "FILM": 500000,
    "EVENT": 250000,
    "INDIVIDUAL": 50000,
}

CLEANING_BUFFER_DAYS = {
    "COSTUME": 2,
    "PROP": 1,
    "SET_DRESSING": 1,
    "WEAPONRY": 3,
    "ACCESSORY": 1,
}

CLEANING_BASE_FEE_CENTS = {
    "COSTUME": 1500,
    "PROP": 800,
    "SET_DRESSING": 1200,
    "WEAPONRY": 2500,
    "ACCESSORY": 500,
}

BACKLOG_THRESHOLD = 10
RUSH_MULTIPLIER = "1.5"

# Condition multiplier for rental charges / late fees
CONDITION_MULT = {"A": "1.20", "B": "1.00", "C": "0.85"}
# Valuation grade multiplier for damage claims
VALUATION_GRADE_MULT = {"A": "1.00", "B": "0.80", "C": "0.60", "D": "0.40"}

RENTER_TYPES = ["THEATRE", "FILM", "EVENT", "INDIVIDUAL"]
PERIODS = ["ANCIENT", "MEDIEVAL", "RENAISSANCE", "REGENCY", "VICTORIAN",
           "EDWARDIAN", "TWENTIES", "FIFTIES", "EIGHTIES", "CONTEMPORARY",
           "FANTASY"]
CATEGORIES = ["COSTUME", "PROP", "SET_DRESSING", "WEAPONRY", "ACCESSORY"]
SIZE_CLASSES = ["NONE", "XS", "S", "M", "L", "XL", "PLUS"]
ALTERATION_POLICIES = ["PROHIBITED", "REVERSIBLE_ONLY", "TAILORING_ALLOWED"]
CONDITION_GRADES = ["A", "B", "C", "D"]
ALTERATION_TYPES = ["HEM", "TAKE_IN", "LET_OUT", "DYE", "DISTRESS", "TRIM"]
REVERSIBLE_ALTERATIONS = {"HEM", "TAKE_IN", "LET_OUT"}
DAMAGE_SEVERITIES = ["NONE", "MINOR", "REPAIRABLE", "DESTROYED"]
CLAIM_TYPES = ["DAMAGE", "LOSS"]
RENTER_STATUSES = ["PENDING_VERIFICATION", "ACTIVE", "SUSPENDED"]
CERT_STATUSES = ["SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED"]
RATE_CARD_STATUSES = ["PUBLISHED", "SUPERSEDED"]
ITEM_STATUSES = ["ACTIVE", "DEACCESSION_PENDING", "DEACCESSIONED"]
UNIT_STATUSES = ["AVAILABLE", "OUT", "CLEANING", "REPAIR",
                 "AWAITING_DISPOSAL", "DISPOSED"]
PRODUCTION_STATUSES = ["DRAFT", "CONFIRMED", "IN_RUN", "WRAP", "SETTLED",
                       "CANCELLED"]
RESERVATION_STATUSES = ["HELD", "CONFIRMED", "RELEASED", "EXPIRED",
                        "FULFILLED"]
PULL_LIST_STATUSES = ["DRAFT", "PICKING", "DISPATCHED", "CLOSED", "CANCELLED"]
LINE_STATUSES = ["PENDING", "PICKED", "OUT", "RETURNED", "DAMAGED", "LOST"]
FITTING_STATUSES = ["REQUESTED", "APPROVED", "REJECTED", "RESTORED"]
CLAIM_STATUSES = ["DRAFT", "POSTED", "DISPUTED", "WAIVED"]
TICKET_STATUSES = ["QUEUED", "IN_CLEANING", "INSPECTION", "REPAIR", "READY"]
INVOICE_STATUSES = ["OPEN", "ISSUED", "PARTIALLY_PAID", "PAID", "CREDITED",
                    "VOID"]

ROLES = {"HouseAdmin", "WardrobeStaff", "RenterContact", "Accountant"}


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.renters = {}
        self.certificates = {}
        self.rate_cards = {}
        self.items = {}
        self.units = {}
        self.productions = {}
        self.reservations = {}
        self.pull_lists = {}
        self.lines = {}
        self.fittings = {}
        self.assessments = {}
        self.claims = {}
        self.tickets = {}
        self.invoices = {}
        # Logical clock: fixed startup default, never the wall clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._seq = itertools.count(1)


DB = Store()


def reset_store():
    """Reset all state (used only by tests of the app itself)."""
    global DB
    DB = Store()


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def now_dt():
    return DB.clock


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(DB.clock)


def today():
    return DB.clock.date()


def next_seq():
    return next(DB._seq)


def new_id():
    return str(uuid.uuid4())


def new_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Record a mutation: refresh updated_at and increment version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def parse_date(s):
    """Parse a strict YYYY-MM-DD date. Returns a date or None."""
    if not isinstance(s, str):
        return None
    try:
        parts = s.split("-")
        if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
            return None
        from datetime import date
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None


def parse_datetime_iso(s):
    """Parse an ISO 8601 datetime (with Z or offset). Returns aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def public(rec):
    """Serialize a record: strip internal keys (prefixed with '_')."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_key(rec):
    return (rec.get("created_at", ""), rec.get("_seq", 0))
