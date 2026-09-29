"""Foundation: logical clock, in-memory store, errors, response envelope,
auth middleware and request-body validation helpers.

Every structural name in this module (header names, envelope field names,
pagination parameter names, error ids) is taken verbatim from PRD.md §2 and
SCAFFOLD.yaml (response_envelope / validations / errors).
"""

import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.current = CLOCK_EPOCH

    def now(self):
        return self.current

    def set(self, value):
        self.current = value


clock = _Clock()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now():
    return clock.now()


def now_iso():
    return iso(clock.now())


def parse_datetime(value):
    """Parse an ISO-8601 datetime. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict ISO-8601 calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Rounding discipline (PRD §2.6)
# ---------------------------------------------------------------------------

def rhu(value):
    """round half up — nearest integer, ties away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# In-memory store (no persistence, no seed data)
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.warehouses = {}
        self.parties = {}
        self.agreements = {}
        self.bins = {}
        self.tickets = {}
        self.receipts = {}
        self.liens = {}
        self.reports = {}
        self.orders = {}
        self.claims = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_row():
    stamp = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(row):
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1


def ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Errors (SCAFFOLD §1.6 / PRD §5)
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_UNAUTHORIZED": "The caller's role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The regulator who licensed this facility may not examine its reports.",
    "ERR_TRANSFER_CHANNEL_INVALID": "The transfer channel does not match the receipt medium and the caller's role.",
    "ERR_VALIDATION": "The request body is invalid.",
    "ERR_WAREHOUSE_NOT_FOUND": "Warehouse not found.",
    "ERR_PARTY_NOT_FOUND": "Party not found.",
    "ERR_AGREEMENT_NOT_FOUND": "Storage agreement not found.",
    "ERR_BIN_NOT_FOUND": "Bin not found.",
    "ERR_TICKET_NOT_FOUND": "Deposit ticket not found.",
    "ERR_RECEIPT_NOT_FOUND": "Warehouse receipt not found.",
    "ERR_LIEN_NOT_FOUND": "Collateral lien not found.",
    "ERR_REPORT_NOT_FOUND": "Position report not found.",
    "ERR_DELIVERY_ORDER_NOT_FOUND": "Delivery order not found.",
    "ERR_CLAIM_NOT_FOUND": "Indemnity claim not found.",
    "ERR_PARTY_KIND_INVALID": "The referenced party kind does not fit the slot it was supplied for.",
    "ERR_COMMODITY_MISMATCH": "The bin commodity differs from the storage agreement commodity.",
    "ERR_STALE_WAREHOUSE_VERSION": "expected_warehouse_version does not match the warehouse version.",
    "ERR_STALE_BIN_VERSION": "expected_bin_version does not match the bin version.",
    "ERR_INVALID_STATE": "The target row is not in a state that admits this transition.",
    "ERR_WAREHOUSE_NOT_LICENSED": "The warehouse is not LICENSED.",
    "ERR_WAREHOUSE_INSOLVENT": "The warehouse is not SOLVENT.",
    "ERR_POSTURE_RESTRICTED": "The warehouse operational posture is RESTRICTED.",
    "ERR_BIN_OUT_OF_CONDITION": "The bin is OUT_OF_CONDITION.",
    "ERR_GRADE_BELOW_MINIMUM": "The assigned grade ranks below the agreement minimum grade.",
    "ERR_COMMINGLING_NOT_PERMITTED": "Commingling rules forbid this bin for this agreement.",
    "ERR_RECEIPT_NOT_NEGOTIABLE": "Only NEGOTIABLE receipts may be transferred or pledged.",
    "ERR_REGISTRY_NOT_PARTICIPANT": "The warehouse does not participate in the electronic receipt registry.",
    "ERR_PERFECTION_METHOD_MISMATCH": "The perfection method does not match the receipt medium.",
    "ERR_RECEIPT_ENCUMBERED": "The receipt is PLEDGED.",
    "ERR_VOID_WINDOW_EXPIRED": "The receipt void window has expired.",
    "ERR_BIN_WINDOW_CONFLICT": "The requested bin fill window conflicts with an existing ticket.",
    "ERR_LOADOUT_CAPACITY_EXCEEDED": "Every loadout lane is occupied for the requested appointment.",
    "ERR_REPORT_PERIOD_OVERLAP": "The reporting period overlaps another report of this warehouse.",
    "ERR_RECEIPT_NUMBER_DUPLICATE": "receipt_number is already used at this warehouse.",
    "ERR_CLAIM_DUPLICATE": "The claimant already has a live claim on this receipt.",
    "ERR_NET_WORTH_INSUFFICIENT": "The net-worth shortfall exceeds the tolerance.",
    "ERR_BOND_INSUFFICIENT": "The posted bond is deficient.",
    "ERR_LICENSED_CAPACITY_EXCEEDED": "Issuance would exceed the licensed capacity.",
    "ERR_BIN_CAPACITY_EXCEEDED": "The bin has insufficient headroom.",
    "ERR_CREDIT_LINE_EXCEEDED": "The lender's available credit is insufficient.",
    "ERR_DELIVERY_EXCEEDS_RECEIPT": "The delivery quantity exceeds what the receipt permits.",
    "ERR_CLAIM_NOT_ELIGIBLE": "The claim is not eligible.",
}


def fail(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def respond_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def respond_error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------

ROLES = ("StateRegulator", "WarehouseOperator", "Depositor", "Lender",
         "RegistryAdministrator")


class Caller:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Ladder ranks 1 and 2 of PRD §2.8."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", 401)
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", 403)
    return Caller(user_id, role)


# ---------------------------------------------------------------------------
# Request body / query validation (ladder rank 6 -> ERR_VALIDATION)
# ---------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_VALIDATION", 422, "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", 422, "Request body must be a JSON object.")
    return parsed


def invalid(field, reason="is invalid"):
    fail("ERR_VALIDATION", 422, "Field '%s' %s." % (field, reason))


def req_str(data, field, allow_empty=False):
    if field not in data or data[field] is None:
        invalid(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        invalid(field, "must be a string")
    if not allow_empty and not value.strip():
        invalid(field, "must be a non-empty string")
    return value


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        invalid(field, "must be a string")
    return value


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        invalid(field, "is required")
    return _as_int(data[field], field, minimum, maximum)


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if field not in data or data[field] is None:
        return default
    return _as_int(data[field], field, minimum, maximum)


def _as_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid(field, "must be an integer")
    if minimum is not None and value < minimum:
        invalid(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        invalid(field, "must be <= %d" % maximum)
    return value


def req_number(data, field, minimum=None):
    if field not in data or data[field] is None:
        invalid(field, "is required")
    return _as_number(data[field], field, minimum)


def opt_number(data, field, minimum=None, default=None):
    if field not in data or data[field] is None:
        return default
    return _as_number(data[field], field, minimum)


def _as_number(value, field, minimum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid(field, "must be a number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        invalid(field, "must be a number")
    if minimum is not None and parsed < Decimal(str(minimum)):
        invalid(field, "must be >= %s" % minimum)
    return parsed


def req_bool(data, field):
    if field not in data or data[field] is None:
        invalid(field, "is required")
    if not isinstance(data[field], bool):
        invalid(field, "must be a boolean")
    return data[field]


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    if not isinstance(data[field], bool):
        invalid(field, "must be a boolean")
    return data[field]


def req_enum(data, field, members):
    value = req_str(data, field)
    if value not in members:
        invalid(field, "must be one of %s" % ", ".join(members))
    return value


def opt_enum(data, field, members, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str) or value not in members:
        invalid(field, "must be one of %s" % ", ".join(members))
    return value


def req_datetime(data, field):
    raw = req_str(data, field)
    parsed = parse_datetime(raw)
    if parsed is None:
        invalid(field, "must be an ISO-8601 datetime")
    return parsed


def req_date(data, field):
    raw = req_str(data, field)
    parsed = parse_date(raw)
    if parsed is None:
        invalid(field, "must be an ISO-8601 date")
    return parsed


def opt_date(data, field):
    if field not in data or data[field] is None:
        return None
    raw = data[field]
    if not isinstance(raw, str):
        invalid(field, "must be an ISO-8601 date")
    parsed = parse_date(raw)
    if parsed is None:
        invalid(field, "must be an ISO-8601 date")
    return parsed


def pagination():
    """PRD §2.3 — limit defaults to 10, min 1, max 100; offset defaults to 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            invalid("limit", "must be an integer")
        if limit < 1 or limit > 100:
            invalid("limit", "must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            invalid("offset", "must be an integer")
        if offset < 0:
            invalid("offset", "must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def query_filter(rows, field, param=None):
    value = request.args.get(param or field)
    if value is None or value == "":
        return rows
    return [r for r in rows if str(r.get(field)) == value]


def num_out(value):
    """Serialise a Decimal-backed numeric field as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
