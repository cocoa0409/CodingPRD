"""Foundation layer: clock, in-memory store, response envelope, errors, auth, validators."""
import random
import re
import string
import uuid
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLE_OPERATOR_ADMIN = "OperatorAdmin"
ROLE_SITE_MANAGER = "SiteManager"
ROLE_FITNESS_STAFF = "FitnessStaff"
ROLE_CLIENT_SPONSOR = "ClientSponsor"
ROLE_MEMBER = "Member"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"

ROLES = (
    ROLE_OPERATOR_ADMIN,
    ROLE_SITE_MANAGER,
    ROLE_FITNESS_STAFF,
    ROLE_CLIENT_SPONSOR,
    ROLE_MEMBER,
    ROLE_COMPLIANCE_AUDITOR,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message if message else error_id


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


# --------------------------------------------------------------------------
# Logical clock (PRD 2.5) — fixed startup instant, movable by admin endpoint
# --------------------------------------------------------------------------
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_START}


def now():
    return _clock["now"]


def today():
    return _clock["now"].date()


def set_now(value):
    _clock["now"] = value


def wall_now():
    return datetime.now(timezone.utc)


def fmt_dt(value):
    if value is None:
        return None
    d = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000,
    )


_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?([Zz]|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _DT_RE.match(text):
        return None
    text = text.replace(" ", "T").replace("t", "T")
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
    """Parse a YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return _date.fromisoformat(value.strip())
    except ValueError:
        return None


def to_date(value):
    if value is None:
        return None
    if isinstance(value, _date) and not isinstance(value, datetime):
        return value
    return parse_date(value)


def days_between(later, earlier):
    """Whole-day difference later - earlier for date values."""
    return (to_date(later) - to_date(earlier)).days


def rhu(value):
    """round_half_up to a whole unit."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))


def month_of(instant):
    if instant is None:
        return None
    d = instant.astimezone(timezone.utc)
    return "%04d-%02d" % (d.year, d.month)


# --------------------------------------------------------------------------
# In-memory store — empty on every boot, never seeded
# --------------------------------------------------------------------------
KINDS = (
    "contract", "staff", "credential", "room", "asset", "offering", "session",
    "assignment", "member", "waiver", "participation", "incident", "invoice",
)

NOT_FOUND_ERRORS = {
    "contract": "ERR_CONTRACT_NOT_FOUND",
    "staff": "ERR_STAFF_NOT_FOUND",
    "credential": "ERR_CREDENTIAL_NOT_FOUND",
    "room": "ERR_ROOM_NOT_FOUND",
    "asset": "ERR_ASSET_NOT_FOUND",
    "offering": "ERR_OFFERING_NOT_FOUND",
    "session": "ERR_SESSION_NOT_FOUND",
    "assignment": "ERR_ASSIGNMENT_NOT_FOUND",
    "member": "ERR_MEMBER_NOT_FOUND",
    "waiver": "ERR_WAIVER_NOT_FOUND",
    "participation": "ERR_PARTICIPATION_NOT_FOUND",
    "incident": "ERR_INCIDENT_NOT_FOUND",
    "invoice": "ERR_INVOICE_NOT_FOUND",
}


class Store(object):
    def __init__(self):
        self.data = {}
        self.seq = 0
        self.reset()

    def reset(self):
        for kind in KINDS:
            self.data[kind] = {}
        self.seq = 0

    def col(self, kind):
        return self.data[kind]

    def all(self, kind):
        return sorted(self.data[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()


def new_record(kind, fields, versioned=True):
    rec = {"_kind": kind, "_seq": DB.next_seq()}
    rec["id"] = str(uuid.uuid4())
    for key, value in fields.items():
        rec[key] = value
    rec["created_at"] = now()
    if versioned:
        rec["updated_at"] = now()
        rec["version"] = 1
    DB.col(kind)[rec["id"]] = rec
    return rec


def touch(rec):
    if "version" in rec:
        rec["updated_at"] = now()
        rec["version"] = rec["version"] + 1


def upd(rec, **fields):
    """Apply field changes; bump version/updated_at only when something changed."""
    changed = False
    for key, value in fields.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


def find(kind, ident):
    if not isinstance(ident, str):
        return None
    return DB.col(kind).get(ident)


def get_or_404(kind, ident):
    rec = find(kind, ident)
    if rec is None:
        raise ApiError(NOT_FOUND_ERRORS[kind], 404)
    return rec


# --------------------------------------------------------------------------
# Query helpers
# --------------------------------------------------------------------------
def where(kind, **filters):
    out = []
    for rec in DB.all(kind):
        ok = True
        for key, value in filters.items():
            if rec.get(key) != value:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def offering_of_session(session):
    return find("offering", session["offering_id"])


def contract_id_of_session(session):
    offering = offering_of_session(session)
    return offering["contract_id"] if offering else None


def session_of_assignment(assignment):
    return find("session", assignment["session_id"])


def sessions_of_contract(contract_id):
    out = []
    for offering in where("offering", contract_id=contract_id):
        out.extend(where("session", offering_id=offering["id"]))
    out.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return out


def assignments_of_contract(contract_id):
    out = []
    for session in sessions_of_contract(contract_id):
        out.extend(where("assignment", session_id=session["id"]))
    return out


def credentials_of_staff(staff_id):
    return where("credential", staff_member_id=staff_id)


def newest_credential(staff_id, credential_type):
    rows = [c for c in credentials_of_staff(staff_id) if c["credential_type"] == credential_type]
    if not rows:
        return None
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))[-1]


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2 / 2.3)
# --------------------------------------------------------------------------
_ID_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": getattr(g, "request_id", None) or new_request_id(),
        "api_request_timestamp": fmt_dt(wall_now()),
    }
    if extra:
        for key, value in extra.items():
            meta[key] = value
    return meta


def view(rec):
    """Serialize a stored record: drop internals, format instants."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        elif isinstance(value, _date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def ok(data, status=200, meta_extra=None):
    if isinstance(data, list):
        response_type = "array"
    elif data is None:
        response_type = "object"
    else:
        response_type = "object"
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, http_status, message=None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(body), http_status


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100


def _int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise bad_request("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("%s below minimum" % name)
    if maximum is not None and value > maximum:
        raise bad_request("%s above maximum" % name)
    return value


def paginate(rows, serializer=None):
    limit = _int_arg("limit", PAGE_DEFAULT_LIMIT, PAGE_MIN_LIMIT, PAGE_MAX_LIMIT)
    offset = _int_arg("offset", 0, 0, None)
    total = len(rows)
    window = rows[offset:offset + limit]
    fn = serializer or view
    data = [fn(r) for r in window]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }
    return ok(data, 200, meta_extra)


# --------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1, validation priorities 1-3)
# --------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if role is None:
        role = request.headers.get("X-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def require(*roles):
    authenticate()
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403)
    return g.user_id, g.role


def scope_contract(contract_id):
    """Priority 3: entity-backed principals must belong to the target contract."""
    if g.role == ROLE_CLIENT_SPONSOR:
        if g.user_id != contract_id:
            raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    elif g.role in (ROLE_SITE_MANAGER, ROLE_FITNESS_STAFF):
        staff = find("staff", g.user_id)
        if staff is not None and staff["contract_id"] != contract_id:
            raise ApiError("ERR_FORBIDDEN_SCOPE", 403)


def scope_member(member):
    if g.role == ROLE_MEMBER:
        if g.user_id != member["id"]:
            raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    else:
        scope_contract(member["contract_id"])


# --------------------------------------------------------------------------
# Body / field validators (priority 8)
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise bad_request("body must be a JSON object")
    if not isinstance(payload, dict):
        raise bad_request("body must be a JSON object")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=1, max_len=None):
    if not _present(data, key):
        raise bad_request("%s is required" % key)
    value = data[key]
    if not isinstance(value, str):
        raise bad_request("%s must be a string" % key)
    if len(value) < min_len:
        raise bad_request("%s is too short" % key)
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s is too long" % key)
    return value


def opt_str(data, key, min_len=1, max_len=None, default=None):
    if not _present(data, key):
        return default
    return req_str(data, key, min_len, max_len)


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        raise bad_request("%s is required" % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        raise bad_request("%s below minimum" % key)
    if maximum is not None and value > maximum:
        raise bad_request("%s above maximum" % key)
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum, maximum)


def req_num(data, key, minimum=None, maximum=None, max_decimals=None,
            exclusive_min=None):
    if not _present(data, key):
        raise bad_request("%s is required" % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("%s must be a number" % key)
    dec = Decimal(str(value))
    if max_decimals is not None and -dec.as_tuple().exponent > max_decimals:
        raise bad_request("%s has too many decimal places" % key)
    if minimum is not None and dec < Decimal(str(minimum)):
        raise bad_request("%s below minimum" % key)
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        raise bad_request("%s below minimum" % key)
    if maximum is not None and dec > Decimal(str(maximum)):
        raise bad_request("%s above maximum" % key)
    return float(dec) if -dec.as_tuple().exponent > 0 else int(dec)


def req_bool(data, key, default=None):
    if not _present(data, key):
        if default is None:
            raise bad_request("%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean" % key)
    return value


def opt_bool(data, key, default=False):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean" % key)
    return value


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        raise bad_request("%s is not one of %s" % (key, ",".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_date(data, key):
    value = req_str(data, key)
    parsed = parse_date(value)
    if parsed is None:
        raise bad_request("%s must be a YYYY-MM-DD date" % key)
    return parsed.isoformat()


def opt_date(data, key, default=None):
    if not _present(data, key):
        return default
    return req_date(data, key)


def req_instant(data, key):
    value = req_str(data, key)
    parsed = parse_dt(value)
    if parsed is None:
        raise bad_request("%s must be an ISO-8601 instant" % key)
    return parsed


def opt_instant(data, key, default=None):
    if not _present(data, key):
        return default
    return req_instant(data, key)


def req_month(data, key):
    value = req_str(data, key)
    if not _MONTH_RE.match(value):
        raise bad_request("%s must be YYYY-MM" % key)
    return value


def req_str_list(data, key, allowed, default=None):
    if not _present(data, key):
        return list(default) if default is not None else None
    value = data[key]
    if not isinstance(value, list) or not value:
        raise bad_request("%s must be a non-empty array" % key)
    out = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad_request("%s contains an unsupported value" % key)
        if item not in out:
            out.append(item)
    return out


def id_ref(data, key, required=True):
    if not _present(data, key):
        if required:
            raise bad_request("%s is required" % key)
        return None
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise bad_request("%s must be a string identifier" % key)
    return value


def query_required(name):
    value = request.args.get(name)
    if value is None or not str(value).strip():
        raise bad_request("%s is required" % name)
    return str(value).strip()
