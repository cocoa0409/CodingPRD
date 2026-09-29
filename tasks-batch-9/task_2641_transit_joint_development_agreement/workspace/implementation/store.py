"""In-memory data store, logical clock and record helpers.

Storage is process-local Python dicts only.  The store starts completely EMPTY on
every boot: no entity is ever seeded, preloaded or hardcoded here.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from errors import fail

# ---------------------------------------------------------------- collections ---
# Every collection maps id -> record dict.  All empty at boot, always.
sites = {}
assessments = {}
developers = {}
solicitations = {}
proposals = {}
negotiation_periods = {}
valuations = {}
agreements = {}
disposition_requests = {}
facility_replacements = {}
shared_facilities = {}
staging_windows = {}
maintenance_charges = {}

COLLECTIONS = {
    "site": sites,
    "assessment": assessments,
    "developer": developers,
    "solicitation": solicitations,
    "proposal": proposals,
    "negotiation_period": negotiation_periods,
    "valuation": valuations,
    "agreement": agreements,
    "disposition_request": disposition_requests,
    "facility_replacement": facility_replacements,
    "shared_facility": shared_facilities,
    "staging_window": staging_windows,
    "maintenance_charge": maintenance_charges,
}

NOT_FOUND = {
    "site": "ERR_SITE_NOT_FOUND",
    "assessment": "ERR_ASSESSMENT_NOT_FOUND",
    "developer": "ERR_DEVELOPER_NOT_FOUND",
    "solicitation": "ERR_SOLICITATION_NOT_FOUND",
    "proposal": "ERR_PROPOSAL_NOT_FOUND",
    "negotiation_period": "ERR_NEGOTIATION_PERIOD_NOT_FOUND",
    "valuation": "ERR_VALUATION_NOT_FOUND",
    "agreement": "ERR_AGREEMENT_NOT_FOUND",
    "disposition_request": "ERR_DISPOSITION_REQUEST_NOT_FOUND",
    "facility_replacement": "ERR_FACILITY_REPLACEMENT_NOT_FOUND",
    "shared_facility": "ERR_SHARED_FACILITY_NOT_FOUND",
    "staging_window": "ERR_STAGING_WINDOW_NOT_FOUND",
}

# --------------------------------------------------------------- logical clock ---
# PRD 2.5: before the clock is ever set the logical current UTC instant is this.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_state = {"clock": DEFAULT_CLOCK, "seq": 0}


def now():
    """Current logical UTC instant."""
    return _state["clock"]


def set_now(dt):
    _state["clock"] = dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(now())


def today():
    return now().date()


# ------------------------------------------------------------------- parsing ---
def parse_dt(value):
    """Parse an ISO 8601 datetime; returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict ISO 8601 calendar date YYYY-MM-DD; returns date or None."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_plus(d, days):
    return d + timedelta(days=days)


def midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# ------------------------------------------------------------------- records ---
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def create(collection_key, fields, versioned=True):
    """Insert a new record.  `id` is a server-minted UUID with no type prefix."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = next_seq()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    COLLECTIONS[collection_key][rec["id"]] = rec
    return rec


def touch(rec):
    """Bump version by exactly 1 and refresh updated_at to the same instant."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()
    return rec


def get(collection_key, rec_id):
    return COLLECTIONS[collection_key].get(rec_id)


def require(collection_key, rec_id):
    rec = COLLECTIONS[collection_key].get(rec_id)
    if rec is None:
        fail(NOT_FOUND[collection_key])
    return rec


def all_of(collection_key):
    return list(COLLECTIONS[collection_key].values())


def by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])
