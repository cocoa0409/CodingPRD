"""Shared helpers: timestamp/version bumping, field validation, listing."""
import db
import errors
from clock import clock
from datetime import datetime, timezone, timedelta


def iso_from_dt(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_years(dt, years):
    """Add calendar years, handling Feb 29 by clamping to Feb 28."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in a non-leap target year.
        return dt.replace(year=dt.year + years, day=28)


def touch(entity):
    """Refresh updated_at and increment version on a mutation (PRD §2.4)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def bump_version(entity):
    """Increment version + refresh updated_at. Alias of touch for cascade clarity."""
    touch(entity)


def require_fields(body, fields):
    """Ensure each required field is present (not None). -> ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_string(body, field):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return v


def require_enum(body, field, allowed):
    require_fields(body, [field])
    v = body[field]
    if v not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, allowed))
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if v not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, allowed))
    return v


def require_int(body, field):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return v


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return v


def require_number(body, field):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return v


def require_bool(body, field):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return v


def parse_iso(value):
    """Parse an ISO 8601 instant (accepts trailing Z) -> aware UTC datetime.
    Invalid -> ERR_INVALID_REQUEST."""
    try:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid ISO 8601 datetime: %s" % value)


def require_datetime(body, field):
    require_fields(body, [field])
    return parse_iso(body[field])


def find_or_404(store, entity_id):
    """Lookup a path-referenced resource; missing -> ERR_NOT_FOUND (PRD §2.6)."""
    item = store.items.get(entity_id)
    if item is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource %s not found" % entity_id)
    return item


def fk_or_422(store, entity_id, label):
    """Validate a body FK references an existing resource of the correct type;
    dangling -> ERR_FK_NOT_FOUND (PRD §2.6)."""
    item = store.items.get(entity_id)
    if item is None:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "%s %s does not exist" % (label, entity_id))
    return item


def paginate_list(store, limit, offset, predicate=None):
    """Return (page_items, total_count) sorted by created_at ascending (PRD §2.3).

    Ties on created_at are broken by insertion sequence to keep ordering stable.
    """
    items = list(store.items.values())
    if predicate is not None:
        items = [i for i in items if predicate(i)]
    items.sort(key=lambda i: (i["created_at"], i.get("_seq", 0)))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
