"""Foundation: errors, response envelope, logical clock, in-memory store,
timestamp production and the shared rungs of the validation ladder (PRD 2.8).

TIMESTAMP THREE-CASE POLICY (all rendering goes through this module):

  (a) Server-written identity stamps -- ``created_at`` / ``updated_at`` and the
      envelope's ``api_request_timestamp`` -- are produced by ``now_stamp()``
      in ONE canonical rendering: ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (PRD 2.4 "three
      fractional digits").  They are strictly monotonic, which is what PRD 2.12
      requires of multiple ledger rows written inside one request.

  (b) A caller-supplied instant is echoed back BYTE-VERBATIM.  The raw request
      string is stored and re-served untouched: ``recorded_at_utc``,
      ``scheduled_start_utc``, ``scheduled_window_start_utc``,
      ``scheduled_window_end_utc`` and the clock's own ``current_utc``.

  (c) A stamp DERIVED from a caller-supplied instant is rendered in that source
      string's style.  Every business stamp read off the logical clock
      (``issued_at``, ``expires_at``, ``notified_at``, ``released_at``,
      ``accepted_at``, ``started_at``, ``completed_at``, ``posted_at_utc``)
      is rendered with the fractional-digit count and the UTC suffix of the
      string the administrator used to set the clock.  Before any clock set the
      style is that of ``2026-05-01T00:00:00Z`` -- no fractional digits, ``Z``.

Timestamps are never compared as strings internally; every comparison parses to
an aware ``datetime`` first.
"""

import json
import random
import re
import string
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_ACTOR_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_VALUE_OUT_OF_RANGE": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_LOCATION_NOT_FOUND": 404,
    "ERR_INSTRUMENT_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_SERVICE_ORDER_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_DUPLICATE_SERIAL_NUMBER": 409,
    "ERR_DUPLICATE_LOT_CODE": 409,
    "ERR_OWNERSHIP_MISMATCH": 409,
    "ERR_CLIENT_NOT_ACTIVE": 409,
    "ERR_INVALID_CUSTODY_STATE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_INSTRUMENT_VERSION": 412,
    "ERR_STALE_ROUTE_DAY_VERSION": 412,
    "ERR_STALE_PARTS_LOT_VERSION": 412,
    "ERR_STALE_WARRANTY_VERSION": 412,
    "ERR_PITCH_REFERENCE_MISMATCH": 422,
    "ERR_PITCH_TIER_CONFLICT": 409,
    "ERR_SERVICE_PREREQUISITE_NOT_MET": 422,
    "ERR_TECH_CERT_INSUFFICIENT": 422,
    "ERR_MOVE_CREW_NOT_CERTIFIED": 422,
    "ERR_CRANE_REQUIRED": 422,
    "ERR_CLIMATE_OUT_OF_BAND": 422,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_CONSIGNMENT_EXPIRED": 409,
    "ERR_APPOINTMENT_LEAD_TIME": 422,
    "ERR_APPOINTMENT_DATE_MISMATCH": 422,
    "ERR_ROUTE_DAY_LOCK_LEAD": 409,
    "ERR_TECHNICIAN_ZONE_MISMATCH": 422,
    "ERR_APPOINTMENT_OVERLAP": 409,
    "ERR_INSTRUMENT_DOUBLE_BOOKED": 409,
    "ERR_MOVE_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_ACTIVE_QUOTE": 409,
    "ERR_MILESTONE_SEQUENCE": 409,
    "ERR_ATTEMPT_LIMIT_EXCEEDED": 409,
    "ERR_PARTS_INSUFFICIENT": 409,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 409,
    "ERR_SALE_BELOW_FLOOR": 422,
    "ERR_DEPOSIT_NOT_SETTLED": 402,
    "ERR_INSUFFICIENT_CREDIT": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ts_lock = threading.Lock()
_ts_last = [0]


def _mono_ms():
    with _ts_lock:
        v = int((datetime.now(timezone.utc) - _EPOCH).total_seconds() * 1000)
        if v <= _ts_last[0]:
            v = _ts_last[0] + 1
        _ts_last[0] = v
        return v


def now_stamp():
    """Case (a): canonical server identity stamp, strictly monotonic."""
    dt = _EPOCH + timedelta(milliseconds=_mono_ms())
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, off = m.groups()
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss), micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        raw = off[1:].replace(":", "")
        dt = dt - sign * timedelta(hours=int(raw[:2]), minutes=int(raw[2:]))
    return dt


def iso_style(value):
    """(fractional_digits, suffix) of an ISO string -- used for case (c)."""
    m = _ISO_RE.match(value.strip())
    if not m:
        return (0, "Z")
    frac, off = m.group(7), m.group(8)
    digits = len(frac) - 1 if frac else 0
    suffix = "Z" if (not off or off in ("Z", "z")) else off
    return (digits, suffix)


def render_style(dt, style):
    digits, suffix = style
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if digits:
        base += "." + ("%06d" % dt.microsecond)[:digits]
    return base + suffix


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def date_str(d):
    return d.isoformat()


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"


class LogicalClock(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.raw = CLOCK_DEFAULT_UTC
        self.dt = parse_iso(CLOCK_DEFAULT_UTC)
        self.style = iso_style(CLOCK_DEFAULT_UTC)

    def set(self, raw, dt):
        self.raw = raw
        self.dt = dt
        self.style = iso_style(raw)

    def stamp(self, dt=None):
        """Case (c): a clock-derived stamp in the source string's style."""
        return render_style(self.dt if dt is None else dt, self.style)

    @property
    def date(self):
        return self.dt.date()


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# In-memory store.  Empty on every boot -- nothing is ever seeded.
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "clients", "locations", "climate_readings", "instruments", "tuning_recalls",
    "technicians", "route_days", "appointments", "quotes", "service_orders",
    "milestones", "move_jobs", "warranties", "warranty_claims",
    "consignment_agreements", "parts_lots", "parts_allocations",
    "ledger_entries",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})

    def rows(self, name):
        return list(getattr(self, name).values())


DB = Store()
LOCK = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def make_row(**fields):
    """A row carrying the full common-field set (id/created_at/updated_at/version)."""
    stamp = now_stamp()
    row = {"id": new_id(), "created_at": stamp, "updated_at": stamp, "version": 1}
    row.update(fields)
    return row


def make_append_row(**fields):
    """A row carrying only id/created_at (ClimateReading, LedgerEntry)."""
    row = {"id": new_id(), "created_at": now_stamp()}
    row.update(fields)
    return row


def touch(row):
    row["updated_at"] = now_stamp()
    row["version"] = row.get("version", 1) + 1


def by_created(rows):
    return sorted(rows, key=lambda r: r["created_at"])


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta_block(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_stamp()}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return {"meta": meta_block(), "response_type": "object", "data": data}, status


def ok_list(items, limit, offset, total):
    meta = meta_block({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    })
    return {"meta": meta, "response_type": "array", "data": items}, 200


def error_body(error_id, message):
    return {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Rounding helpers (PRD 2.6 -- money is integer cents, ROUND_HALF_UP)
# ---------------------------------------------------------------------------

def D(value):
    return Decimal(str(value))


def round_half_up(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def floor_div_int(value):
    d = D(value)
    return int(d.to_integral_value(rounding="ROUND_FLOOR"))


def ceil_int(value):
    d = D(value)
    return int(d.to_integral_value(rounding="ROUND_CEILING"))


# ---------------------------------------------------------------------------
# Enum member lists
# ---------------------------------------------------------------------------

ROLES = ("PlatformAdmin", "ShopManager", "Technician", "Client",
         "MoveCoordinator", "ShowroomAgent")

CLIENT_TYPES = ("INDIVIDUAL", "INSTITUTION", "DEALER")
CLIENT_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
ZONES = ("ZONE_A", "ZONE_B", "ZONE_C")
INSTRUMENT_CLASSES = ("UPRIGHT", "CONSOLE", "BABY_GRAND", "GRAND", "CONCERT_GRAND")
USAGE_TIERS = ("HOME", "STUDIO", "INSTITUTIONAL", "PERFORMANCE")
SERVICE_TYPES = ("TUNE", "PITCH_RAISE", "REGULATE", "VOICE", "REBUILD")
CONDITION_STATUSES = ("NEEDS_ASSESSMENT", "SERVICEABLE", "NEEDS_REGULATION",
                      "NEEDS_VOICING", "REBUILD_REQUIRED", "RESTORED")
CUSTODY_STATUSES = ("AT_CLIENT_SITE", "IN_TRANSIT", "IN_SHOP", "SHOWROOM_FLOOR",
                    "SOLD")
RECALL_STATUSES = ("PENDING", "NOTIFIED", "SCHEDULED", "FULFILLED", "LAPSED")
OVERDUE_TIERS = ("ON_TIME", "OVERDUE_T1", "OVERDUE_T2", "LAPSED_TIER")
CERT_LEVELS = ("APPRENTICE", "JOURNEYMAN", "MASTER")
TECH_STATUSES = ("ACTIVE", "INACTIVE")
ROUTE_DAY_STATUSES = ("OPEN", "LOCKED", "DISPATCHED")
SCHEDULING_STATUSES = ("REQUESTED", "SCHEDULED", "CONFIRMED", "RESCHEDULED",
                       "CANCELLED")
FULFILLMENT_STATUSES = ("PENDING", "EN_ROUTE", "IN_PROGRESS", "COMPLETED",
                        "NO_SHOW", "ABORTED")
QUOTE_STATUSES = ("DRAFT", "ISSUED", "APPROVED", "DECLINED", "EXPIRED",
                  "SUPERSEDED")
ORDER_STATUSES = ("PENDING", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED",
                  "VOIDED_BY_REBUILD")
MILESTONE_STATUSES = ("PENDING", "READY", "RELEASED", "ACCEPTED", "REJECTED",
                      "CANCELLED")
MOVE_STATUSES = ("DRAFT", "SCHEDULED", "DISPATCHED", "IN_TRANSIT", "DELIVERED",
                 "CANCELLED")
WARRANTY_STATUSES = ("ACTIVE", "VOIDED", "EXPIRED", "TRANSFERRED")
VOID_REASONS = ("UNAUTHORIZED_MOVE", "CLIMATE_OUT_OF_BAND", "TUNING_CYCLE_LAPSED",
                "MANUAL")
CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED_RESERVICE",
                  "APPROVED_CREDIT", "DENIED")
DECISIONS = ("APPROVE", "DENY")
CONSIGNMENT_STATUSES = ("DRAFT", "ACTIVE", "LISTED", "SOLD", "EXPIRED",
                        "WITHDRAWN")
PART_TYPES = ("HAMMER_SET", "STRING_SET", "ACTION_PARTS")
LOT_STATUSES = ("OPEN", "DEPLETED")
ALLOCATION_STATUSES = ("RESERVED", "PARTIAL", "CONSUMED", "RELEASED")
ENTRY_TYPES = ("DEPOSIT_CHARGE", "MILESTONE_CHARGE", "WARRANTY_CREDIT",
               "CONSIGNMENT_PROCEEDS", "DEPOSIT_REFUND", "CANCELLATION_FEE",
               "MANUAL_ADJUSTMENT", "REVERSAL")

# Operations that demand X-User-ID from EVERY role (PRD 2.8 rung 1).
SOD_OPERATIONS = frozenset({
    ("POST", "milestone-release"),
    ("POST", "claim-adjudicate"),
    ("POST", "consignment-create"),
    ("POST", "consignment-record-sale"),
})


# ---------------------------------------------------------------------------
# Request context -- rungs 1..8 of the ladder
# ---------------------------------------------------------------------------

class Ctx(object):
    def __init__(self, roles, sod=False):
        self.roles = roles
        self.role = None
        self.user_id = None
        self.body = {}
        self._authenticate(roles, sod)

    # -- rungs 1..3 -----------------------------------------------------
    def _authenticate(self, roles, sod):
        role = request.headers.get("X-User-Role")
        user_id = request.headers.get("X-User-ID")
        if role is None or role.strip() == "":
            fail("ERR_MISSING_AUTH_HEADER", "X-User-Role is required.")
        role = role.strip()
        needs_uid = sod or role in ("Technician", "Client")
        if needs_uid and (user_id is None or user_id.strip() == ""):
            fail("ERR_MISSING_AUTH_HEADER", "X-User-ID is required.")
        if role not in ROLES:
            fail("ERR_INVALID_ROLE", "Unknown role '%s'." % role)
        if role not in roles:
            fail("ERR_UNAUTHORIZED_ROLE",
                 "Role %s may not perform this operation." % role)
        self.role = role
        self.user_id = user_id.strip() if user_id else None

    # -- rung 4 ---------------------------------------------------------
    @property
    def is_client(self):
        return self.role == "Client"

    @property
    def is_tech(self):
        return self.role == "Technician"

    def scope_client(self, *client_ids):
        """Reject a Client actor addressing a row it does not own."""
        if not self.is_client:
            return
        vals = [c for c in client_ids if c]
        if vals and self.user_id not in vals:
            fail("ERR_ACTOR_SCOPE_VIOLATION",
                 "This client may only address its own resources.")

    def scope_tech(self, *technician_ids):
        """Reject a Technician actor addressing a RouteDay/ServiceOrder it does
        not own.  A null owner is not an ownership violation."""
        if not self.is_tech:
            return
        vals = [t for t in technician_ids if t]
        if vals and self.user_id not in vals:
            fail("ERR_ACTOR_SCOPE_VIOLATION",
                 "This technician may only address its own resources.")

    def peek_body(self):
        """Best-effort body read for rung 4 (which precedes rung 5)."""
        try:
            raw = request.get_data(as_text=True)
            if not raw or not raw.strip():
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    # -- rung 5 ---------------------------------------------------------
    def read_body(self, required=()):
        raw = request.get_data(as_text=True)
        if raw is None or raw.strip() == "":
            body = {}
        else:
            try:
                body = json.loads(raw)
            except Exception:
                fail("ERR_VALIDATION", "Request body must be a JSON object.")
            if not isinstance(body, dict):
                fail("ERR_VALIDATION", "Request body must be a JSON object.")
        for field in required:
            if field not in body or body[field] is None:
                fail("ERR_VALIDATION", "Field '%s' is required." % field)
        self.body = body
        return body

    # -- rung 6 ---------------------------------------------------------
    def enum(self, field, members, source=None, required=False):
        src = self.body if source is None else source
        if field not in src or src[field] is None:
            if required:
                fail("ERR_VALIDATION", "Field '%s' is required." % field)
            return None
        value = src[field]
        if not isinstance(value, str) or value not in members:
            fail("ERR_INVALID_ENUM", "Field '%s' carries an undeclared member." % field)
        return value

    def enum_q(self, field, members):
        value = request.args.get(field)
        if value is None:
            return None
        if value not in members:
            fail("ERR_INVALID_ENUM", "Filter '%s' carries an undeclared member." % field)
        return value

    def enum_list(self, field, members, required=False):
        if field not in self.body or self.body[field] is None:
            if required:
                fail("ERR_VALIDATION", "Field '%s' is required." % field)
            return None
        value = self.body[field]
        if not isinstance(value, list) or not value:
            fail("ERR_VALIDATION", "Field '%s' must be a non-empty array." % field)
        for item in value:
            if not isinstance(item, str) or item not in members:
                fail("ERR_INVALID_ENUM",
                     "Field '%s' carries an undeclared member." % field)
        return value

    # -- rung 7 ---------------------------------------------------------
    def number(self, field, lo=None, hi=None, lo_exclusive=False,
               integer=False, required=False):
        if field not in self.body or self.body[field] is None:
            if required:
                fail("ERR_VALIDATION", "Field '%s' is required." % field)
            return None
        value = self.body[field]
        if isinstance(value, bool):
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' must be numeric." % field)
        if integer:
            if not isinstance(value, int):
                fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' must be an integer." % field)
        else:
            if not isinstance(value, (int, float)):
                fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' must be numeric." % field)
        if lo is not None:
            if lo_exclusive:
                if not D(value) > D(lo):
                    fail("ERR_VALUE_OUT_OF_RANGE",
                         "Field '%s' is out of range." % field)
            elif D(value) < D(lo):
                fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is out of range." % field)
        if hi is not None and D(value) > D(hi):
            fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is out of range." % field)
        return value

    # -- rung 8 ---------------------------------------------------------
    def pagination(self):
        limit, offset = 10, 0
        raw_limit = request.args.get("limit")
        raw_offset = request.args.get("offset")
        if raw_limit is not None:
            if not re.match(r"^-?\d+$", raw_limit.strip()):
                fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
            limit = int(raw_limit)
            if limit < 1 or limit > 100:
                fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
        if raw_offset is not None:
            if not re.match(r"^-?\d+$", raw_offset.strip()):
                fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
            offset = int(raw_offset)
            if offset < 0:
                fail("ERR_INVALID_PAGINATION", "offset must not be negative.")
        return limit, offset


def page(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Existence resolution -- rungs 9..14, in ladder order
# ---------------------------------------------------------------------------

def need_client(client_id):
    row = DB.clients.get(client_id) if isinstance(client_id, str) else None
    if row is None:
        fail("ERR_CLIENT_NOT_FOUND", "Client %s does not exist." % client_id)
    return row


def need_location(location_id):
    row = DB.locations.get(location_id) if isinstance(location_id, str) else None
    if row is None:
        fail("ERR_LOCATION_NOT_FOUND", "Location %s does not exist." % location_id)
    return row


def need_instrument(instrument_id):
    row = DB.instruments.get(instrument_id) if isinstance(instrument_id, str) else None
    if row is None:
        fail("ERR_INSTRUMENT_NOT_FOUND",
             "Instrument %s does not exist." % instrument_id)
    return row


def need_quote(quote_id):
    row = DB.quotes.get(quote_id) if isinstance(quote_id, str) else None
    if row is None:
        fail("ERR_QUOTE_NOT_FOUND", "Quote %s does not exist." % quote_id)
    return row


def need_order(order_id):
    row = DB.service_orders.get(order_id) if isinstance(order_id, str) else None
    if row is None:
        fail("ERR_SERVICE_ORDER_NOT_FOUND",
             "Service order %s does not exist." % order_id)
    return row


def need_other(collection, row_id):
    table = getattr(DB, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "Resource %s does not exist." % row_id)
    return row


def not_terminal(current, terminal_states):
    if current in terminal_states:
        fail("ERR_ALREADY_TERMINAL",
             "Resource already sits in terminal state %s." % current)


def add_days(d, days):
    return d + timedelta(days=days)


def days_between(later, earlier):
    return (later - earlier).days
