from decimal import Decimal, ROUND_HALF_UP
from flask import request
from errors import err
from store import store, new_id, now_iso

VALID_ROLES = {"Customer", "StoreAssociate", "StoreManager", "FramingSpecialist"}


def round_half_up(value):
    """Round a numeric value half-up to an integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_user_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid user context headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role not permitted for this operation")


def auth(allowed_roles):
    """Validate headers then role permission; return (uid, role)."""
    uid, role = get_user_context()
    require_role(role, allowed_roles)
    return uid, role


def get_json():
    if request.data and len(request.data) > 0:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if body is None:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be an object")
        return body
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def pagination():
    args = request.args
    limit = args.get("limit", None)
    offset = args.get("offset", None)
    try:
        limit = 10 if limit is None else int(limit)
        offset = 0 if offset is None else int(offset)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Invalid pagination parameter")
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
    return page, total


def base_entity(extra=None):
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    ent["_seq"] = store.next_seq()
    if extra:
        ent.update(extra)
    return ent


def touch(ent):
    """Bump version and updated_at for a mutation."""
    ent["version"] = ent.get("version", 1) + 1
    ent["updated_at"] = now_iso()


# Fields internal to the server, stripped from serialized output.
_HIDDEN = {"_seq", "_applied_coupons", "_picked_up_at",
           "_valid_from", "_valid_to", "_starts_at", "_ends_at"}


def serialize(ent):
    if ent is None:
        return None
    return {k: v for k, v in ent.items() if k not in _HIDDEN}


def sort_created(items):
    return sorted(items, key=lambda e: e["_seq"])
