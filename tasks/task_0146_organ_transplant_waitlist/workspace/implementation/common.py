"""Common helpers: auth, field validation, pagination, system fields."""
import uuid
from datetime import datetime

from flask import request

from errors import err
from store import db
from timeutil import parse_iso, format_iso

VALID_ROLES = {"UNOSAdmin", "TransplantCenter", "OrganProcurementOrg"}


# ----------------------------------------------------------------------------
# Auth (PRD §2.1 / validations priority 1)
# ----------------------------------------------------------------------------
def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED.

    Both X-User-ID and X-User-Role must be present and the role must be one of
    the three recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Authorization (PRD §2.1 / validations priority 2)."""
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")


# ----------------------------------------------------------------------------
# System fields (PRD §2.4)
# ----------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _utcnow():
    from datetime import timezone
    return datetime.now(timezone.utc)


def base_fields(full=True):
    """Return id/created_at/updated_at/version for a new entity.

    created_at/updated_at are record-management timestamps (real wall-clock),
    distinct from the deterministic business clock used for 'now' reasoning
    (PRD §2.5). A monotonic _seq stamps insertion order for stable sorting.
    """
    now = format_iso(_utcnow())
    rec = {
        "id": new_id(),
        "created_at": now,
        "_seq": db.next_seq(),
    }
    if full:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    rec["updated_at"] = format_iso(_utcnow())
    if "version" in rec:
        rec["version"] = rec.get("version", 1) + 1


def touch_no_version(rec):
    """Refresh updated_at without advancing version.

    Used for donor-organ open_offer_count bookkeeping on offer decline/expire/
    rescind: PRD §2.7 enumerates the organ-version-advancing operations as
    match, offer-issue, accept, transplant, and discard — decline/expire/rescind
    decrement open_offer_count but must NOT advance the OCC token, or the OPO's
    held version would go stale during the re-offer loop."""
    rec["updated_at"] = format_iso(_utcnow())


def public_view(rec):
    """Strip internal-only keys (those prefixed with '_') from a record."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ----------------------------------------------------------------------------
def parse_pagination():
    """Parse limit/offset query params. Defaults limit=10 (min 1, max 100),
    offset=0 (min 0). Out-of-range values are clamped into the allowed band."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def sorted_by_created(values):
    """List endpoints sort by creation timestamp ascending (PRD §2.3),
    using the insertion sequence as the deterministic tiebreaker."""
    return sorted(values, key=lambda r: (r.get("created_at"), r.get("_seq", 0)))


# ----------------------------------------------------------------------------
# Field-shape validation (PRD §2.8 priority 5 -> ERR_INVALID_REQUEST)
# ----------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict; treat missing/invalid as empty dict."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def require_int_range(body, field, lo, hi):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer" % field)
    if v < lo or v > hi:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be in [%s,%s]" % (field, lo, hi))
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a number" % field)
    return float(v)


def require_positive_number(body, field):
    v = require_number(body, field)
    if v <= 0:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be > 0" % field)
    return v


def require_hla_array(body, field):
    v = body.get(field)
    if not isinstance(v, list) or len(v) != 2 or not all(isinstance(x, str) for x in v):
        raise err("ERR_INVALID_REQUEST",
                  "Field '%s' must be an array of exactly two strings" % field)
    return list(v)


def optional_str_array(body, field, default=None):
    if field not in body or body.get(field) is None:
        return list(default) if default is not None else []
    v = body.get(field)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings" % field)
    return list(v)


def require_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % field)
    return v


def require_timestamp(body, field):
    v = body.get(field)
    dt = parse_iso(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp" % field)
    return dt
