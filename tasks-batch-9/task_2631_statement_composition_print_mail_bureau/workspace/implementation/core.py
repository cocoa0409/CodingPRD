"""Core infrastructure: logical clock, in-memory store, envelope, errors, auth, validators."""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import g, jsonify, request

# --------------------------------------------------------------------------- roles
ROLE_BUREAU_ADMIN = "BureauAdmin"
ROLE_CLIENT_LIAISON = "ClientLiaison"
ROLE_COMPOSITION_OPERATOR = "CompositionOperator"
ROLE_PRODUCTION_SCHEDULER = "ProductionScheduler"
ROLE_POSTAGE_CONTROLLER = "PostageController"
ROLE_INTEGRITY_AUDITOR = "IntegrityAuditor"

ROLES = [
    ROLE_BUREAU_ADMIN,
    ROLE_CLIENT_LIAISON,
    ROLE_COMPOSITION_OPERATOR,
    ROLE_PRODUCTION_SCHEDULER,
    ROLE_POSTAGE_CONTROLLER,
    ROLE_INTEGRITY_AUDITOR,
]
ALL_ROLES = tuple(ROLES)

# --------------------------------------------------------------------------- clock
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock(object):
    def __init__(self):
        self.current = INITIAL_CLOCK

    def set(self, dt):
        self.current = dt


CLOCK = _Clock()


def now():
    return CLOCK.current


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|z|[+-]\d{2}:\d{2})$"
)


def parse_dt(value):
    """Parse an ISO 8601 UTC instant. Returns None when malformed or not UTC."""
    if not isinstance(value, str):
        return None
    if not _ISO_RE.match(value):
        return None
    text = value.strip()
    try:
        if text[-1] in ("Z", "z"):
            base = datetime.fromisoformat(text[:-1].replace(" ", "T"))
            return base.replace(tzinfo=timezone.utc)
        base = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    if base.tzinfo is None:
        return None
    if base.utcoffset() != timedelta(0):
        return None
    return base.astimezone(timezone.utc)


# --------------------------------------------------------------------------- rounding
def half_up(value, places=0):
    """Round half up. Returns int when places == 0, else Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    out = value.quantize(exp, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(out)
    return out


def ceil_div(numerator, denominator):
    if not isinstance(numerator, Decimal):
        numerator = Decimal(str(numerator))
    if not isinstance(denominator, Decimal):
        denominator = Decimal(str(denominator))
    return int((numerator / denominator).quantize(Decimal(1), rounding=ROUND_CEILING))


def minutes_between(start, end):
    """Signed minutes from start to end as a Decimal."""
    return Decimal(str((end - start).total_seconds())) / Decimal(60)


# --------------------------------------------------------------------------- store
class Store(object):
    def __init__(self):
        self.clients = {}
        self.templates = {}
        self.inserts = {}
        self.files = {}
        self.records = {}
        self.enrollments = {}
        self.jobs = {}
        self.pieces = {}
        self.scans = {}
        self.lines = {}
        self.runs = {}
        self.facilities = {}
        self.batches = {}
        self.returns = {}
        self.drsites = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_id():
    return str(uuid.uuid4())


def base_row():
    """id / created_at / updated_at / version quartet plus insertion sequence."""
    ts = now()
    return {
        "id": new_id(),
        "_seq": DB.next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def append_row():
    """Append-only audit row: id and created_at only."""
    return {"id": new_id(), "_seq": DB.next_seq(), "created_at": now()}


def touch(row):
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


# --------------------------------------------------------------------------- errors
ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_TEMPLATE_NOT_FOUND": 404,
    "ERR_INSERT_STOCK_NOT_FOUND": 404,
    "ERR_DATA_FILE_NOT_FOUND": 404,
    "ERR_RECORD_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_MAIL_PIECE_NOT_FOUND": 404,
    "ERR_PRESS_LINE_NOT_FOUND": 404,
    "ERR_PRINT_RUN_NOT_FOUND": 404,
    "ERR_ENTRY_FACILITY_NOT_FOUND": 404,
    "ERR_PRESORT_BATCH_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_DR_SITE_NOT_FOUND": 404,
    "ERR_CLIENT_MISMATCH": 422,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DR_SITE_ALREADY_EXISTS": 409,
    "ERR_RETURN_DUPLICATE": 409,
    "ERR_CLIENT_SUSPENDED": 409,
    "ERR_FILE_INVALID_STATE": 409,
    "ERR_TEMPLATE_NOT_ACTIVE": 409,
    "ERR_TEMPLATE_INVALID_STATE": 409,
    "ERR_JOB_INVALID_STATE": 409,
    "ERR_RUN_INVALID_STATE": 409,
    "ERR_BATCH_NOT_OPEN": 409,
    "ERR_BATCH_NOT_SEALED": 409,
    "ERR_PIECE_NOT_SCANNABLE": 409,
    "ERR_PIECE_NOT_REPRINT_ELIGIBLE": 409,
    "ERR_RETURN_INVALID_STATE": 409,
    "ERR_ENROLLMENT_INVALID_STATE": 409,
    "ERR_PRESS_LINE_UNAVAILABLE": 409,
    "ERR_ENTRY_FACILITY_CLOSED": 409,
    "ERR_STALE_COMPOSITION_JOB_VERSION": 412,
    "ERR_STALE_CLIENT_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INSERT_NOT_EFFECTIVE": 422,
    "ERR_INSERT_CODE_UNKNOWN": 422,
    "ERR_FILE_FORMAT_ERRORS": 422,
    "ERR_FILE_EMPTY": 422,
    "ERR_AMENDMENT_NO_CHANGE": 422,
    "ERR_DR_SITE_NOT_READY": 409,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_INVALID_INDUCTION_WINDOW": 422,
    "ERR_PRESS_LINE_CAPABILITY_MISMATCH": 422,
    "ERR_PRESS_WINDOW_CONFLICT": 409,
    "ERR_NO_ELIGIBLE_PRESS_LINE": 409,
    "ERR_NO_PENDING_FEEDBACK": 409,
    "ERR_PRESS_CAPACITY_EXCEEDED": 409,
    "ERR_INDUCTION_CAPACITY_EXCEEDED": 409,
    "ERR_INSERT_STOCK_INSUFFICIENT": 409,
    "ERR_POSTAGE_ESCROW_INSUFFICIENT": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def invalid(message):
    raise ApiError("ERR_VALIDATION", message)


# --------------------------------------------------------------------------- envelope
_RID_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_RID_ALPHABET) for _ in range(20))


def meta_base():
    rid = getattr(g, "api_request_id", None)
    if rid is None:
        rid = new_request_id()
        g.api_request_id = rid
    return {"api_request_id": rid, "api_request_timestamp": iso(now())}


def serialize(row):
    """Render a stored row: strip internals, format datetimes, floatify decimals."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def respond(data, code=200):
    body_out = {"meta": meta_base(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body_out), code


def respond_list(rows, total, limit, offset):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(error_id, message):
    body_out = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body_out), ERROR_STATUS.get(error_id, 400)


# --------------------------------------------------------------------------- auth
def require_auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "" or role not in ROLES:
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and a valid X-User-Role are required")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s is not permitted on this endpoint" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def acting_user():
    return getattr(g, "user_id", None)


# --------------------------------------------------------------------------- body / field validation
def json_body():
    if request.method not in ("POST", "PATCH", "PUT"):
        return {}
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        invalid("request body must be valid JSON")
    if not isinstance(parsed, dict):
        invalid("request body must be a JSON object")
    return parsed


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=None, max_len=None, pattern=None):
    if not _present(body, name):
        invalid("field '%s' is required" % name)
    return opt_str(body, name, min_len, max_len, pattern)


def opt_str(body, name, min_len=None, max_len=None, pattern=None, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        invalid("field '%s' must be a string" % name)
    if min_len is not None and len(value) < min_len:
        invalid("field '%s' must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("field '%s' must be at most %d characters" % (name, max_len))
    if pattern is not None and not re.match(pattern, value):
        invalid("field '%s' is malformed" % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        invalid("field '%s' is required" % name)
    return opt_int(body, name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        invalid("field '%s' must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("field '%s' must be <= %d" % (name, maximum))
    return value


def req_bool(body, name):
    if not _present(body, name):
        invalid("field '%s' is required" % name)
    return opt_bool(body, name)


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        invalid("field '%s' must be a boolean" % name)
    return value


def req_enum(body, name, allowed):
    if not _present(body, name):
        invalid("field '%s' is required" % name)
    return opt_enum(body, name, allowed)


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        invalid("field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def req_dt(body, name):
    if not _present(body, name):
        invalid("field '%s' is required" % name)
    return opt_dt(body, name)


def opt_dt(body, name, default=None):
    if not _present(body, name):
        return default
    parsed = parse_dt(body[name])
    if parsed is None:
        invalid("field '%s' must be a well-formed ISO 8601 UTC instant" % name)
    return parsed


def req_str_list(body, name, allow_duplicates=True, max_item_len=None):
    if not _present(body, name):
        invalid("field '%s' is required" % name)
    return opt_str_list(body, name, allow_duplicates, max_item_len, default=None)


def opt_str_list(body, name, allow_duplicates=True, max_item_len=None, default=None):
    if not _present(body, name):
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list):
        invalid("field '%s' must be an array" % name)
    for item in value:
        if not isinstance(item, str):
            invalid("field '%s' must be an array of strings" % name)
        if max_item_len is not None and len(item) > max_item_len:
            invalid("field '%s' entries are too long" % name)
    if not allow_duplicates and len(set(value)) != len(value):
        invalid("field '%s' must not contain duplicates" % name)
    return list(value)


# --------------------------------------------------------------------------- pagination & filters
_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not _INT_RE.match(raw.strip()):
            invalid("limit must be an integer between 1 and 100")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not _INT_RE.match(raw.strip()):
            invalid("offset must be an integer >= 0")
        offset = int(raw.strip())
        if offset < 0:
            invalid("offset must be >= 0")
    return limit, offset


def filter_value(name, allowed=None):
    """Read an optional exact-match query filter."""
    if name not in request.args:
        return None
    raw = request.args.get(name)
    if raw is None:
        return None
    if allowed is not None and raw not in allowed:
        invalid("filter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return raw


def filter_bool(name):
    if name not in request.args:
        return None
    raw = (request.args.get(name) or "").strip().lower()
    if raw in ("true", "1"):
        return True
    if raw in ("false", "0"):
        return False
    invalid("filter '%s' must be true or false" % name)


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serialize(row) for row in page], total


def sorted_rows(rows, keyfunc):
    return sorted(rows, key=lambda row: keyfunc(row) + (row["_seq"],))


def blank(value):
    return value is None or value == ""
