"""Entity construction, common-field management, serialization, pagination."""
from clock import clock
from db import db
from errors import err
from util import new_id, format_ts, add_days


# ---------------------------------------------------------------------------
# Common fields & mutation bookkeeping
# ---------------------------------------------------------------------------
def _stamp_create(entity):
    now = clock.now
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Bump version + updated_at on any mutation (PRD 2.4 / 2.8)."""
    entity["version"] += 1
    entity["updated_at"] = clock.now


# ---------------------------------------------------------------------------
# Serialization — strips internal keys, formats datetimes
# ---------------------------------------------------------------------------
_DATETIME_FIELDS = {
    "created_at", "updated_at", "draw_date", "claim_deadline", "exclusion_until",
    "entry_deadline", "period_start", "period_end", "entered_at", "escheated_at",
}


def serialize(entity, computed=None):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if k in _DATETIME_FIELDS:
            out[k] = format_ts(v) if v is not None else None
        else:
            out[k] = v
    if computed:
        out.update(computed)
    return out


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def parse_pagination(args):
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit_val = 10
    else:
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_FILTER_INVALID", "limit must be an integer")
        if limit_val < 1 or limit_val > 100:
            raise err("ERR_VALIDATION_FILTER_INVALID", "limit out of range [1,100]")
    if offset is None:
        offset_val = 0
    else:
        try:
            offset_val = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_FILTER_INVALID", "offset must be an integer")
        if offset_val < 0:
            raise err("ERR_VALIDATION_FILTER_INVALID", "offset must be >= 0")
    return limit_val, offset_val


def paginate(rows, limit, offset):
    """rows: list already sorted. Returns (page, pagination_meta)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def sort_by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(store, rid, label="resource"):
    if rid not in store:
        raise err("ERR_NOT_FOUND", f"{label} {rid} not found")
    return store[rid]
