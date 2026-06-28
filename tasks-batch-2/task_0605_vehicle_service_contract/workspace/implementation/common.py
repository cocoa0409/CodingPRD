"""Common system field management, validation helpers, pagination, ledger/calc utilities."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

from db import db, new_id, now_iso
from errors import err


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------
def make_common(full=True):
    """full=True -> id, created_at, updated_at, version.
    full=False -> id, created_at only (LedgerEntry, ClockState, AuditEvent)."""
    ts = now_iso()
    rec = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if full:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on mutation."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serialization (strip internal fields)
# ---------------------------------------------------------------------------
def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def require_body(body):
    if body is None or not isinstance(body, dict):
        return {}
    return body


def req_field(body, name, typ=None):
    """Required field present and well-typed -> ERR_INVALID_REQUEST."""
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    val = body[name]
    if typ is not None and not _typed(val, typ):
        raise err("ERR_INVALID_REQUEST", f"Field {name} is ill-typed")
    return val


def opt_field(body, name, default, typ=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if typ is not None and not _typed(val, typ):
        raise err("ERR_INVALID_REQUEST", f"Field {name} is ill-typed")
    return val


def _typed(val, typ):
    if typ == "int":
        return isinstance(val, int) and not isinstance(val, bool)
    if typ == "number":
        return (isinstance(val, (int, float)) and not isinstance(val, bool))
    if typ == "str":
        return isinstance(val, str)
    if typ == "bool":
        return isinstance(val, bool)
    return True


def non_negative(val, name):
    if val < 0:
        raise err("ERR_VALIDATION_RANGE", f"{name} must be non-negative")
    return val


def at_least(val, minimum, name):
    if val < minimum:
        raise err("ERR_VALIDATION_RANGE", f"{name} must be >= {minimum}")
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(args, items):
    """items: list already sorted. Returns (page, limit, offset, total)."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit out of bounds")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset out of bounds")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_created(items):
    """Sort by created_at ascending, tie-break by internal seq."""
    return sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def fk_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced resource not found")
    return rec


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value (in cents, possibly fractional) to whole cents."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Clock / time
# ---------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO 8601 datetime string; return aware datetime in UTC or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def floor_days(later, earlier):
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Ledger postings & pool surplus (PRD §2.9)
# ---------------------------------------------------------------------------
CEDED_TYPES = {"PREMIUM_CEDED", "REFUND_CLAWBACK"}
LOSS_TYPES = {"LOSS_PAID", "LOSS_REVERSED"}
RESERVE_TYPES = {"RESERVE_SET", "RESERVE_RELEASE"}


def post_ledger(pool_id, entry_type, amount_cents, memo, contract_id=None):
    rec = make_common(full=False)
    rec["reinsurance_pool_id"] = pool_id
    rec["contract_id"] = contract_id
    rec["entry_type"] = entry_type
    rec["amount_cents"] = amount_cents
    rec["memo"] = memo
    db.ledger_entries[rec["id"]] = rec
    recompute_pool(pool_id)
    return rec


def recompute_pool(pool_id):
    pool = db.reinsurance_pools.get(pool_id)
    if pool is None:
        return
    ceded = paid = reserve = 0
    for e in db.ledger_entries.values():
        if e["reinsurance_pool_id"] != pool_id:
            continue
        et = e["entry_type"]
        amt = e["amount_cents"]
        if et in CEDED_TYPES:
            ceded += amt
        elif et in LOSS_TYPES:
            paid += amt
        elif et in RESERVE_TYPES:
            reserve += amt
    pool["ceded_premium_cents"] = ceded
    pool["paid_loss_cents"] = paid
    pool["reserve_held_cents"] = reserve
    pool["surplus_cents"] = ceded - paid - reserve


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def audit(actor_role, entity_type, entity_id, action):
    rec = make_common(full=False)
    rec["actor_role"] = actor_role
    rec["entity_type"] = entity_type
    rec["entity_id"] = entity_id
    rec["action"] = action
    db.audit_events[rec["id"]] = rec
    return rec
