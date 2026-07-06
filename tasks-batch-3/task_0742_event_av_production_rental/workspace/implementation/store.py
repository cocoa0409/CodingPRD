"""In-memory data store, id/timestamp/clock helpers, error type and response envelope.

All state lives in module-level dicts and is wiped every time the process boots
(the test harness relaunches start.sh before every test). Nothing is seeded.
"""
import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# In-memory collections (keyed by id). Empty at boot — never seeded.
# ---------------------------------------------------------------------------
customers = {}
venues = {}
equipment = {}
crew_members = {}
rental_orders = {}
reservations = {}
crew_assignments = {}
sub_rentals = {}
certificates = {}
damage_reports = {}
deposit_ledger = {}

# Monotonic insertion counter -> stable created_at-ascending list ordering.
_seq = {"n": 0}

# ---------------------------------------------------------------------------
# Logical clock (§2.6). Reads exactly this instant until a client advances it.
# Used ONLY for rush-window and COI-expiry evaluation, never for created_at.
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def reset_state():
    for d in (customers, venues, equipment, crew_members, rental_orders,
              reservations, crew_assignments, sub_rentals, certificates,
              damage_reports, deposit_ledger):
        d.clear()
    _seq["n"] = 0
    _clock["now"] = CLOCK_DEFAULT


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Id / timestamp helpers
# ---------------------------------------------------------------------------
def new_id():
    # UUID with no type prefix (§2.4).
    return str(uuid.uuid4())


def now_ts():
    # ISO 8601 UTC with exactly three fractional digits and a Z suffix (§2.4).
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def _next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_record(fields, common=True):
    """Build a record dict with server-managed common fields prepended."""
    rec = {"id": new_id(), "created_at": now_ts()}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec.update(fields)
    rec["_seq"] = _next_seq()
    return rec


def touch(rec):
    """Mark a common-field record as mutated: bump updated_at and version."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal bookkeeping keys before serialising to the client."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Rounding (§2.5): every fractional cent rounds half up, away from zero.
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope (§2.2)
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_ts(),
    }
    if extra:
        m.update(extra)
    return m


def envelope_object(data):
    return {"meta": _meta(), "response_type": "object", "data": data}


def envelope_array(items, limit, offset, total_count, has_more):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    return {"meta": meta, "response_type": "array", "data": items}


def envelope_error(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
