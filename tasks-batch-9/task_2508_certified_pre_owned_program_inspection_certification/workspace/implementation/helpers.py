"""Envelopes, timestamp handling, schema validation, auth ladder, pagination."""
import random
import re
import string
from datetime import date, datetime, timedelta

from flask import g, request

from db import db
from errors import ApiError

ROLES = (
    "ProgramAdministrator",
    "ProgramAuditor",
    "DealerPrincipal",
    "InspectionTechnician",
    "CustomerAdvocate",
)

ENTITY_BACKED = {"DealerPrincipal": "dealers", "InspectionTechnician": "technicians"}


# --------------------------------------------------------------------------- #
# timestamps
# --------------------------------------------------------------------------- #
def fmt_instant(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def fmt_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%Y-%m-%d")


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(text, field="timestamp"):
    """Parse an ISO-8601 instant into a naive UTC datetime."""
    if not isinstance(text, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string." % field)
    m = _INSTANT_RE.match(text.strip())
    if not m:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 instant." % field)
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1000000))
        if micro > 999999:
            micro = 999999
    try:
        value = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid instant." % field)
    offset = m.group(8)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        value = value - sign * timedelta(hours=int(body[:2]), minutes=int(body[2:]))
    return value


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(text, field="date"):
    if not isinstance(text, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD string." % field)
    m = _DATE_RE.match(text.strip())
    if not m:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be formatted YYYY-MM-DD." % field)
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid calendar date." % field)


def clock_date():
    return db.clock.date()


# --------------------------------------------------------------------------- #
# envelopes
# --------------------------------------------------------------------------- #
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_instant(db.clock),
    }


def object_response(data, status=200):
    return {"meta": base_meta(), "response_type": "object", "data": data}, status


def list_response(rows, limit, offset, total):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return {"meta": meta, "response_type": "array", "data": rows}, 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------- #
# auth ladder (rungs 1-3)
# --------------------------------------------------------------------------- #
def auth_headers():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and a declared X-User-Role header are required.",
        )
    return user_id, role


def check_role(role, allowed):
    if role not in allowed:
        raise ApiError(
            "ERR_ROLE_FORBIDDEN",
            "Role %s is not authorised for this operation." % role,
        )


def resolve_identity(user_id, role):
    """Rung 3 — only meaningful for the two entity-backed roles."""
    table = ENTITY_BACKED.get(role)
    if table is None:
        return None
    row = getattr(db, table).get(user_id)
    if row is None:
        raise ApiError(
            "ERR_IDENTITY_NOT_RECOGNIZED",
            "X-User-ID does not resolve to an existing %s."
            % ("dealer" if role == "DealerPrincipal" else "technician"),
        )
    return row


def authorize(allowed):
    """Run rungs 1, 2 and 3 in order and return (user_id, role, principal)."""
    user_id, role = auth_headers()
    check_role(role, allowed)
    principal = resolve_identity(user_id, role)
    return user_id, role, principal


def require_dealer_scope(user_id, role, dealer_id):
    """Rung 7 for a `DealerPrincipal`.

    2.1: "ownership checks on any resource that references a `Dealer` compare
    that resource's dealer foreign-key field to `X-User-ID`" and "If the
    identity resolves but the targeted inspection, certification, listing,
    claim, or technician belongs to a different dealership, the rejection is
    `ERR_DEALER_SCOPE_VIOLATION`". The rule is stated over the *targeted*
    resource, so it governs retrievals as much as writes.
    """
    if role == "DealerPrincipal" and dealer_id != user_id:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "That record belongs to another dealership.",
        )


# --------------------------------------------------------------------------- #
# mutation bookkeeping
# --------------------------------------------------------------------------- #
def touch(row):
    """Refresh updated_at and bump version at most once per row per request."""
    if row is None:
        return
    seen = getattr(g, "touched_rows", None)
    if seen is None:
        seen = set()
        g.touched_rows = seen
    key = id(row)
    if key in seen:
        return
    seen.add(key)
    row["updated_at"] = db.clock
    row["version"] = row.get("version", 1) + 1


def new_common(row):
    row["created_at"] = db.clock
    row["updated_at"] = db.clock
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def new_evidence(row):
    row["created_at"] = db.clock
    row["_seq"] = db.next_seq()
    return row


# --------------------------------------------------------------------------- #
# body / query schema validation (rung 4)
# --------------------------------------------------------------------------- #
def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body_dict():
    raw = request.get_data()
    if raw is None or not raw.strip():
        return {}
    parsed = request.get_json(silent=True, force=True)
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


def _present(body, name):
    return name in body and body[name] is not None


def f_string(body, name, required=True, default=None, allow_empty=False):
    if not _present(body, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        bad_request("Field '%s' must not be empty." % name)
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def f_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if not _is_int(value):
        bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be at most %s." % (name, maximum))
    return value


def f_number(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if not _is_number(value):
        bad_request("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be at most %s." % (name, maximum))
    return float(value)


def f_bool(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % name)
    return value


def f_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad_request(
            "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def f_list(body, name, required=True, default=None, non_empty=True):
    if not _present(body, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % name)
    if non_empty and len(value) == 0:
        bad_request("Field '%s' must not be empty." % name)
    return value


def f_enum_list(body, name, allowed, required=True, default=None, non_empty=True):
    value = f_list(body, name, required, None, non_empty)
    if value is None:
        return default
    for entry in value:
        if not isinstance(entry, str) or entry not in allowed:
            bad_request(
                "Field '%s' accepts only %s." % (name, ", ".join(sorted(allowed)))
            )
    return list(value)


def f_date(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    return parse_date(body[name], "Field '%s'" % name)


def f_instant(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            bad_request("Field '%s' is required." % name)
        return default
    return parse_instant(body[name], "Field '%s'" % name)


# --------------------------------------------------------------------------- #
# query parameters
# --------------------------------------------------------------------------- #
def q_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad_request("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Query parameter '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("Query parameter '%s' must be at most %s." % (name, maximum))
    return value


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad_request(
            "Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed)))
        )
    return raw


def q_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw in ("true", "True", "TRUE"):
        return True
    if raw in ("false", "False", "FALSE"):
        return False
    bad_request("Query parameter '%s' must be true or false." % name)


def pagination():
    limit = q_int("limit", 10, 1, 100)
    offset = q_int("offset", 0, 0, None)
    return limit, offset


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paged(rows, limit, offset, serializer):
    rows = sort_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)
