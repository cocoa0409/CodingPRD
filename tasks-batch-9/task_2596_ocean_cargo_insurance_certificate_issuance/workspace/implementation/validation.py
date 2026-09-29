"""Auth (PRD 2.1), schema validation (PRD 2.5), pagination (PRD 2.3) and money (PRD 2.7)."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from errors import ApiError

ROLES = (
    "Underwriter",
    "Assured",
    "ComplianceOfficer",
    "PremiumAuditor",
    "ClaimsAdjuster",
    "Surveyor",
    "PlatformAdmin",
)

_MISSING = object()


# --------------------------------------------------------------------------- #
# money / rate helpers -- all rounding in this system is half up (PRD 2.7)
# --------------------------------------------------------------------------- #
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
Q6 = Decimal("0.000001")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q2(value):
    return D(value).quantize(Q2, rounding=ROUND_HALF_UP)


def q4(value):
    return D(value).quantize(Q4, rounding=ROUND_HALF_UP)


def q6(value):
    return D(value).quantize(Q6, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal for the JSON body."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
def authenticate(allowed_roles):
    """Priority 1 then 2: headers, then role authorisation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# --------------------------------------------------------------------------- #
# body access
# --------------------------------------------------------------------------- #
def body():
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _present(payload, name):
    return name in payload and payload[name] is not None


def bad(name, why="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def get_str(payload, name, required=True, default=None, min_len=None, max_len=None,
            exact_len=None):
    if not _present(payload, name):
        if required:
            bad(name, "is required")
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        bad(name, "is too short")
    if max_len is not None and len(value) > max_len:
        bad(name, "is too long")
    if exact_len is not None and len(value) != exact_len:
        bad(name, "must be exactly %d characters" % exact_len)
    return value


def get_enum(payload, name, allowed, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad(name, "is required")
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def get_bool(payload, name, required=False, default=None):
    if not _present(payload, name):
        if required:
            bad(name, "is required")
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def _to_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        bad(name, "must be a number")
    try:
        dec = D(value)
    except (InvalidOperation, ValueError):
        bad(name, "must be a number")
    if not dec.is_finite():
        bad(name, "must be a finite number")
    return dec


def get_decimal(payload, name, required=True, default=None, minimum=None,
                maximum=None, gt=None, lte=None):
    """`minimum`/`maximum` are inclusive bounds, `gt` is a strict lower bound."""
    if not _present(payload, name):
        if required:
            bad(name, "is required")
        return default
    dec = _to_decimal(name, payload[name])
    if minimum is not None and dec < D(minimum):
        bad(name, "must be at least %s" % minimum)
    if gt is not None and dec <= D(gt):
        bad(name, "must be greater than %s" % gt)
    if maximum is not None and dec > D(maximum):
        bad(name, "must be at most %s" % maximum)
    if lte is not None and dec > D(lte):
        bad(name, "must be at most %s" % lte)
    return dec


def get_int(payload, name, required=True, default=None, minimum=None, maximum=None,
            gt=None):
    if not _present(payload, name):
        if required:
            bad(name, "is required")
        return default
    value = payload[name]
    if isinstance(value, bool):
        bad(name, "must be an integer")
    if isinstance(value, int):
        out = value
    elif isinstance(value, float) and float(value).is_integer():
        out = int(value)
    elif isinstance(value, str):
        try:
            out = int(value)
        except ValueError:
            bad(name, "must be an integer")
    else:
        bad(name, "must be an integer")
    if minimum is not None and out < minimum:
        bad(name, "must be at least %s" % minimum)
    if gt is not None and out <= gt:
        bad(name, "must be greater than %s" % gt)
    if maximum is not None and out > maximum:
        bad(name, "must be at most %s" % maximum)
    return out


def parse_dt(name, value):
    if not isinstance(value, str) or not value.strip():
        bad(name, "must be an ISO 8601 UTC datetime")
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            bad(name, "must be an ISO 8601 UTC datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_dt(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad(name, "is required")
        return default
    return parse_dt(name, payload[name])


def get_str_array(payload, name, allowed, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad(name, "is required")
        return default
    value = payload[name]
    if not isinstance(value, list) or not value:
        bad(name, "must be a non-empty array")
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad(name, "must contain only %s" % ", ".join(sorted(allowed)))
    return list(value)


# --------------------------------------------------------------------------- #
# pagination and query filters
# --------------------------------------------------------------------------- #
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("limit")
        if limit < 1 or limit > 100:
            bad("limit", "must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("offset")
        if offset < 0:
            bad("offset", "must be at least 0")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_dt(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return parse_dt(name, value)


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serializer(r) for r in page], limit, offset, total
