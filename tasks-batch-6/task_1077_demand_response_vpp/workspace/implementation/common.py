"""Shared request-handling helpers: envelope, auth, RBAC, body/field validation,
pagination, numeric helpers."""
from decimal import Decimal, ROUND_HALF_UP
from flask import request, jsonify

from errors import err
from store import db, serialize, request_id, real_now_iso

ROLES = {"ProgramOperator", "Aggregator", "Customer", "Auditor"}


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": real_now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, meta_extra=None, response_type="object"):
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_object(rec, status=200):
    return ok(serialize(rec), status=status, response_type="object")


def ok_list(records, status=200):
    """records already paginated. Wrap with array response_type."""
    return ok([serialize(r) for r in records], status=status, response_type="array")


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1, §2.8 steps 1-2)
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "Missing or unrecognized X-User-ID / X-User-Role.")
    return user_id, role


def authorize(role, allowed_roles):
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED",
                  "Role %s is not permitted for this operation." % role)


def require(allowed_roles):
    """Run auth + authz, returning (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


ALL_ROLES = ROLES  # every role may perform GET reads


# ---------------------------------------------------------------------------
# Body parsing and field validation (PRD §2.8 steps 6-7)
# ---------------------------------------------------------------------------
def get_body():
    if request.data:
        try:
            payload = request.get_json(force=True, silent=True)
        except Exception:
            payload = None
    else:
        payload = None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


def is_bool(v):
    return isinstance(v, bool)


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", "Field %s must be a non-empty string." % field)
    return v


def require_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", "Missing required field: %s" % field)
    v = body[field]
    if is_bool(v) or not isinstance(v, int):
        raise err("ERR_VALIDATION", "Field %s must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", "Field %s must be >= %s." % (field, minimum))
    return v


def require_number(body, field, gt=None, ge=None):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", "Missing required field: %s" % field)
    v = body[field]
    if is_bool(v) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", "Field %s must be a number." % field)
    if gt is not None and not v > gt:
        raise err("ERR_VALIDATION", "Field %s must be > %s." % (field, gt))
    if ge is not None and not v >= ge:
        raise err("ERR_VALIDATION", "Field %s must be >= %s." % (field, ge))
    return v


def opt_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        return None
    return require_int(body, field, minimum=minimum)


def opt_number(body, field, gt=None, ge=None, le=None):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if is_bool(v) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", "Field %s must be a number." % field)
    if gt is not None and not v > gt:
        raise err("ERR_VALIDATION", "Field %s must be > %s." % (field, gt))
    if ge is not None and not v >= ge:
        raise err("ERR_VALIDATION", "Field %s must be >= %s." % (field, ge))
    if le is not None and not v <= le:
        raise err("ERR_VALIDATION", "Field %s must be <= %s." % (field, le))
    return v


def require_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise err("ERR_VALIDATION", "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_ENUM", "Field %s must be one of %s." % (field, sorted(allowed)))
    if v not in allowed:
        raise err("ERR_INVALID_ENUM", "Field %s must be one of %s." % (field, sorted(allowed)))
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) and listing
# ---------------------------------------------------------------------------
def _parse_page_param(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < minimum:
        v = minimum
    if maximum is not None and v > maximum:
        v = maximum
    return v


def paginate(records):
    """records: full filtered list already sorted. Returns (page, meta_extra)."""
    limit = _parse_page_param("limit", 10, 1, 100)
    offset = _parse_page_param("offset", 0, 0)
    total = len(records)
    page = records[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta_extra


def sorted_by_created(records):
    """Stable sort oldest-first (created_at asc; insertion order tiebreak)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(all_records):
    page = sorted_by_created(list(all_records))
    page, meta_extra = paginate(page)
    body_items = [serialize(r) for r in page]
    return ok(body_items, status=200, meta_extra=meta_extra, response_type="array")


# ---------------------------------------------------------------------------
# Numeric helpers (PRD §2.5)
# ---------------------------------------------------------------------------
def rhu(value, places):
    """Round half-up to `places` decimals; returns a Decimal."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def num(value, places=None):
    """Convert a Decimal/number to a clean JSON number (int when integral)."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    if places is not None:
        d = rhu(d, places)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def kw_sum(values):
    """Exact sum of kW values (PRD §2.5: kW held exactly, no rounding)."""
    total = Decimal("0")
    for v in values:
        total += Decimal(str(v))
    return num(total)
