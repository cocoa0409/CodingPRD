"""Foundation: errors, logical clock, in-memory store, response envelope,
auth/RBAC, validation helpers.  Every structural name here is taken from
SCAFFOLD.yaml response_envelope / validations and PRD sections 2.1-2.11.
"""
import re
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request, jsonify

# ---------------------------------------------------------------- roles
ROLE_CITY_CLERK = "CityClerk"
ROLE_DEPUTY_CLERK = "DeputyClerk"
ROLE_PRESIDING = "PresidingOfficer"
ROLE_RECORDS = "RecordsOfficer"
ROLE_CODIFICATION = "CodificationEditor"
ROLE_REQUESTER = "Requester"
ROLE_ANONYMOUS = "Anonymous"

ALL_ROLES = (
    ROLE_CITY_CLERK,
    ROLE_DEPUTY_CLERK,
    ROLE_PRESIDING,
    ROLE_RECORDS,
    ROLE_CODIFICATION,
    ROLE_REQUESTER,
    ROLE_ANONYMOUS,
)

# "All staff roles" per PRD section 4.
STAFF_ROLES = (
    ROLE_CITY_CLERK,
    ROLE_DEPUTY_CLERK,
    ROLE_PRESIDING,
    ROLE_RECORDS,
    ROLE_CODIFICATION,
)


# ---------------------------------------------------------------- errors
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").capitalize() + "."


def invalid(message="Request payload failed validation."):
    return ApiError("ERR_INVALID_REQUEST", 422, message)


# ------------------------------------------------------- logical clock
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    """Pure in-memory store.  Starts completely empty on every boot."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self.seq = 0
        self.venues = {}
        self.meetings = {}
        self.packets = {}
        self.agenda_items = {}
        self.motions = {}
        self.minutes = {}
        self.number_series = {}
        self.instruments = {}
        self.notices = {}
        self.code_titles = {}
        self.cycles = {}
        self.submissions = {}
        self.requests = {}
        self.record_series = {}
        self.batches = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now_dt():
    return db.clock


def now_date():
    return db.clock.date()


# ------------------------------------------------------- serialisation
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(d):
    if d is None:
        return None
    return d.isoformat()


def parse_datetime(value):
    if not isinstance(value, str) or not TS_RE.match(value.strip()):
        raise invalid("Malformed ISO 8601 datetime.")
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("Malformed ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise invalid("Malformed ISO 8601 date.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise invalid("Malformed ISO 8601 date.")


def serialise(value):
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if key.startswith("_"):
                continue
            out[key] = serialise(val)
        return out
    if isinstance(value, (list, tuple)):
        return [serialise(v) for v in value]
    if isinstance(value, datetime):
        return iso_ts(value)
    if isinstance(value, date):
        return iso_date(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


# ------------------------------------------------------- record helpers
def new_record(versioned=True):
    stamp = db.clock
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "created_at": stamp,
    }
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Advance updated_at / version at most once per HTTP request per record."""
    if rec is None or "version" not in rec:
        return
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if rec["id"] in touched:
        return
    touched.add(rec["id"])
    rec["version"] = rec["version"] + 1
    rec["updated_at"] = db.clock


def sort_records(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ------------------------------------------------------- response envelope
def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20].upper(),
        "api_request_timestamp": iso_ts(db.clock),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialise(data) if data is not None else {},
    }
    return jsonify(body), status


def ok_list(records, limit, offset, total):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total,
                "has_more": (offset + len(records)) < total,
            }
        ),
        "response_type": "array",
        "data": [serialise(r) for r in records],
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ------------------------------------------------------- auth / RBAC
def authorize(allowed_roles, owner_request_id=None):
    """PRD 2.1 / 2.11: missing headers -> unknown role -> role permitted ->
    Requester ownership.  Nothing else about the request is examined first."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_MISSING_AUTH_HEADERS", 401)
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", 401)
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", 403)
    if role == ROLE_REQUESTER and owner_request_id is not None:
        if user_id != owner_request_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    g.user_id = user_id
    g.role = role
    return user_id, role


# ------------------------------------------------------- body / query
def body_dict():
    raw = request.get_json(silent=True)
    if raw is None:
        if request.data and request.data.strip():
            raise invalid("Body is not valid JSON.")
        return {}
    if not isinstance(raw, dict):
        raise invalid("Body must be a JSON object.")
    return raw


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args["limit"] != "":
        try:
            limit = int(str(args["limit"]).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", 422)
    if "offset" in args and args["offset"] != "":
        try:
            offset = int(str(args["offset"]).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", 422)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", 422)
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    return records[offset: offset + limit], total


def listing(records, filters=None, sort_key=None):
    limit, offset = pagination()
    if filters:
        for field, wanted in filters.items():
            if wanted is None:
                continue
            records = [r for r in records if r.get(field) == wanted]
    if sort_key is None:
        records = sort_records(records)
    else:
        records = sorted(records, key=sort_key)
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# ------------------------------------------------------- field validators
def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, allow_empty=False):
    if not _present(body, key):
        raise invalid("Field '%s' is required." % key)
    value = body[key]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        raise invalid("Field '%s' must not be empty." % key)
    return value


def opt_str(body, key, default=None, allow_empty=True):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        raise invalid("Field '%s' must not be empty." % key)
    return value


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        raise invalid("Field '%s' is required." % key)
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        return default
    return req_int(body, key, minimum, maximum)


def req_bool(body, key):
    if not _present(body, key):
        raise invalid("Field '%s' is required." % key)
    value = body[key]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % key)
    return value


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    return req_bool(body, key)


def req_enum(body, key, choices):
    value = req_str(body, key)
    if value not in choices:
        raise invalid("Field '%s' must be one of %s." % (key, ", ".join(choices)))
    return value


def opt_enum(body, key, choices, default=None):
    if not _present(body, key):
        return default
    return req_enum(body, key, choices)


def req_date(body, key):
    if not _present(body, key):
        raise invalid("Field '%s' is required." % key)
    return parse_date(body[key])


def req_datetime(body, key):
    if not _present(body, key):
        raise invalid("Field '%s' is required." % key)
    return parse_datetime(body[key])


def req_list(body, key):
    if not _present(body, key):
        raise invalid("Field '%s' is required." % key)
    value = body[key]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % key)
    return value


def req_decimal(body, key, minimum_exclusive=None, max_places=None):
    if not _present(body, key):
        raise invalid("Field '%s' is required." % key)
    value = body[key]
    if isinstance(value, bool):
        raise invalid("Field '%s' must be a number." % key)
    if isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        dec = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except Exception:
            raise invalid("Field '%s' must be a number." % key)
    else:
        raise invalid("Field '%s' must be a number." % key)
    if not dec.is_finite():
        raise invalid("Field '%s' must be a finite number." % key)
    if minimum_exclusive is not None and dec <= Decimal(minimum_exclusive):
        raise invalid("Field '%s' must be greater than %s." % (key, minimum_exclusive))
    if max_places is not None and -dec.as_tuple().exponent > max_places:
        raise invalid("Field '%s' allows at most %d decimal places." % (key, max_places))
    return dec


def round_half_up(value):
    """Half-up rounding to a whole unit; returns int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def add_years(anchor, years):
    """Whole-year calendar addition; 29 Feb clamps to 28 Feb (PRD 2.9)."""
    year = anchor.year + years
    try:
        return anchor.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def add_days(value, days):
    return value + timedelta(days=days)


def fetch(table, key, error_id):
    """Path/body FK resolution: a missing row is a 404 with the entity's own id."""
    record = table.get(key) if isinstance(key, str) else None
    if record is None:
        raise ApiError(error_id, 404)
    return record


def fk(body, key, table, error_id):
    """Body foreign key: absent is left to the shape pass, present must resolve."""
    if not _present(body, key):
        return None
    value = body[key]
    if not isinstance(value, str):
        raise ApiError(error_id, 404)
    return fetch(table, value, error_id)


def occ(body, key, parent, error_id):
    expected = req_int(body, key)
    if parent is None or expected != parent["version"]:
        raise ApiError(error_id, 412)
    return expected
