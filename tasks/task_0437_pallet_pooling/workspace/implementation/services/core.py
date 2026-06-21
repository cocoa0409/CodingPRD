"""Core shared services: entity lifecycle, recompute, pagination, validation.

Field naming (PRD §2.4 Common Resource Properties):
  - id           : UUID, no type prefix, set at creation
  - created_at   : ISO 8601 UTC, 3 fractional digits, fixed at creation
  - updated_at   : refreshed on every mutation
  - version      : integer, starts at creation, +1 on every mutation
Every entity in this domain is mutable and carries all four (PRD §2.4).
"""
from db import db, new_id, now_iso
from errors import err
from middleware import get_json_body

# Pagination defaults (PRD §2.3 / scaffold §1.0).
PAG_DEFAULT_LIMIT = 10
PAG_MIN_LIMIT = 1
PAG_MAX_LIMIT = 100
PAG_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Common-field lifecycle
# ---------------------------------------------------------------------------
def stamp_new(entity):
    """Attach the common system fields to a freshly built entity dict."""
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Mutation bookkeeping: bump updated_at and version (PRD §2.4, §2.6)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def public(entity):
    """Strip internal-only keys (those prefixed with '_') for the response."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Existence resolution (PRD §2.7 — left-to-right, first miss -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def require(collection, resource_id):
    ent = collection.get(resource_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource %s does not exist" % resource_id)
    return ent


def resolve_body_fk(body, name, collection):
    """Existence check (priority 3) for a body foreign-key field.

    Per PRD §2.10 existence is evaluated BEFORE body well-formedness. When the FK
    field is present as a non-empty string, its target must exist (else 404). When
    the field is absent/None/non-string, this is a well-formedness concern handled
    later (priority 4), so we skip the existence check here and return None.
    """
    v = body.get(name)
    if isinstance(v, str) and v.strip():
        return require(collection, v)
    return None


def resolve_body_fk_list(body, name, collection):
    """Existence check (priority 3) for a body FK list of ids.

    Each present id string must resolve (left-to-right). Non-string entries and
    list-shape problems are deferred to well-formedness (priority 4).
    """
    v = body.get(name)
    if isinstance(v, list):
        for item in v:
            if isinstance(item, str) and item.strip():
                require(collection, item)


# ---------------------------------------------------------------------------
# Body field validation (validation priority 4 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v.strip():
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return v


def require_int(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be >= %s" % (name, minimum))
    return v


def optional_int(body, name, default, minimum=None):
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, minimum)


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def optional_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    return require_enum(body, name, allowed)


def require_id_list(body, name, allow_empty):
    v = body.get(name)
    if not isinstance(v, list):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a list" % name)
    if not allow_empty and len(v) == 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be non-empty" % name)
    for item in v:
        if not isinstance(item, str) or not item.strip():
            raise err("ERR_INVALID_REQUEST",
                      "Field %s must contain id strings" % name)
    return v


def require_datetime(body, name):
    from db import parse_dt
    v = body.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be an ISO 8601 datetime" % name)
    return dt


# ---------------------------------------------------------------------------
# Pagination + list assembly (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination(args):
    limit = PAG_DEFAULT_LIMIT
    offset = PAG_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAG_MIN_LIMIT or limit > PAG_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST",
                      "limit must be between %d and %d" % (PAG_MIN_LIMIT, PAG_MAX_LIMIT))
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def sort_by_creation(entities):
    """Default list ordering: creation timestamp ascending (PRD §2.3).

    Uses the monotonic _seq as the creation order so entities created in the
    same millisecond still sort deterministically by actual creation order.
    """
    return sorted(entities, key=lambda e: e["_seq"])


def paginate(entities, args):
    limit, offset = parse_pagination(args)
    ordered = sort_by_creation(entities)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(e) for e in page], limit, offset, total


# ---------------------------------------------------------------------------
# Recompute: Location physical_balance, equity_status (PRD §2.5, §3.1)
# ---------------------------------------------------------------------------
def active_policy():
    for p in db.pool_policies.values():
        if p["status"] == "ACTIVE":
            return p
    return None


def equity_warn_threshold():
    p = active_policy()
    if p is not None:
        return p["equity_warn_threshold"]
    return 200  # PoolPolicy default (PRD §3.1) when no active policy yet.


def recompute_physical_balance(location):
    """physical_balance = count of assets at this location whose condition is
    not LOST (PRD §2.5)."""
    loc_id = location["id"]
    count = 0
    for a in db.assets.values():
        if a["current_location_id"] == loc_id and a["condition"] != "LOST":
            count += 1
    location["physical_balance"] = count
    return count


def recompute_equity_status(location):
    """equity_status from equity_balance vs threshold (PRD §2.5):
       SHORT if equity_balance >= threshold; SURPLUS if < 0; else BALANCED."""
    eq = location["equity_balance"]
    if eq >= equity_warn_threshold():
        status = "SHORT"
    elif eq < 0:
        status = "SURPLUS"
    else:
        status = "BALANCED"
    location["equity_status"] = status
    return status


def recompute_location_derived(location):
    recompute_physical_balance(location)
    recompute_equity_status(location)


# ---------------------------------------------------------------------------
# Tiered daily rate (PRD §3.4)
# ---------------------------------------------------------------------------
TIER1_QTY = 10
TIER1_FACTOR = 90   # 0.90 expressed as hundredths to keep integer math exact
TIER2_QTY = 50
TIER2_FACTOR = 80   # 0.80
DAY_SECONDS = 86400


def tiered_daily_rate(n, base):
    """Effective floored per-asset daily rate for a count n (PRD §3.4).

    n >= 50 -> floor(base * 0.80); n >= 10 -> floor(base * 0.90); else base.
    Floored once per tier.
    """
    if n >= TIER2_QTY:
        return (base * TIER2_FACTOR) // 100
    if n >= TIER1_QTY:
        return (base * TIER1_FACTOR) // 100
    return base


def whole_days(start_dt, end_dt):
    """Whole elapsed days, floored, never < 0 (one day = 86400 s)."""
    delta = (end_dt - start_dt).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // DAY_SECONDS)


# ---------------------------------------------------------------------------
# Hire accrual / final charge (PRD §3.4)
# ---------------------------------------------------------------------------
def assets_still_on_hire(hire):
    """Assets in this hire's manifest still ON_HIRE on this hire right now."""
    out = []
    for aid in hire["asset_ids"]:
        a = db.assets.get(aid)
        if a is not None and a["condition"] == "ON_HIRE" and a["current_hire_id"] == hire["id"]:
            out.append(a)
    return out


def hire_accrued_charge(hire):
    """Provisional forward-looking accrual while OPEN (PRD §3.4).

    days = whole elapsed days from on_hire_at to current clock (floor, >=0)
    n    = count of assets still ON_HIRE on this hire (current count)
    rate = tiered_daily_rate(n, base)
    accrued = days * n * rate
    """
    from db import parse_dt
    if hire["lifecycle_status"] != "OPEN":
        return hire.get("accrued_charge_cents", 0)
    at = db.asset_types[hire["asset_type_id"]]
    base = at["base_daily_rate_cents"]
    on_hire_at = parse_dt(hire["on_hire_at"])
    days = whole_days(on_hire_at, db.clock)
    n = len(assets_still_on_hire(hire))
    rate = tiered_daily_rate(n, base)
    return days * n * rate


def recompute_hire_accrued(hire):
    """Recompute accrued_charge_cents on read while OPEN (PRD §3.4)."""
    if hire["lifecycle_status"] == "OPEN":
        hire["accrued_charge_cents"] = hire_accrued_charge(hire)
    return hire["accrued_charge_cents"]


def hire_final_charge(hire):
    """Chronological event-replay actual charge pinned at CLOSE (PRD §3.4).

    Half-open day interval [on_hire_at, off_hire_at). For each whole day D,
    active_n = assets in manifest not yet damaged as of day D; rate is the
    tiered rate for active_n; day charge = active_n * rate. Sum across days.
    A damaged asset stops accruing from its damage day onward (damage day
    excluded from its accrual).
    """
    from db import parse_dt
    at = db.asset_types[hire["asset_type_id"]]
    base = at["base_daily_rate_cents"]
    on_hire_at = parse_dt(hire["on_hire_at"])
    off_hire_at = parse_dt(hire["off_hire_at"])
    total_days = whole_days(on_hire_at, off_hire_at)
    if total_days <= 0:
        return 0

    # For each manifest asset, determine the whole-day index (relative to
    # on_hire_at) at which it stopped accruing because of damage. An asset that
    # was never damaged accrues for the whole interval.
    damage_day_index = {}  # aid -> day index from which it no longer accrues
    for aid in hire["asset_ids"]:
        dd = hire.get("_damage_at", {}).get(aid)
        if dd is None:
            damage_day_index[aid] = None  # never damaged on this hire
        else:
            dmg_dt = parse_dt(dd) if isinstance(dd, str) else dd
            # Damage day = whole-day index of the damage instant relative to
            # on_hire_at; asset stops accruing FROM that day (day excluded).
            idx = whole_days(on_hire_at, dmg_dt)
            damage_day_index[aid] = idx

    total = 0
    for day in range(total_days):
        active_n = 0
        for aid in hire["asset_ids"]:
            cut = damage_day_index[aid]
            if cut is None or day < cut:
                active_n += 1
        if active_n == 0:
            continue
        rate = tiered_daily_rate(active_n, base)
        total += active_n * rate
    return total


# ---------------------------------------------------------------------------
# Account outstanding charge (PRD §3.5)
# ---------------------------------------------------------------------------
def recompute_account_outstanding(account):
    """outstanding_charge_cents = sum(accrued of OPEN hires) +
       sum(total - paid of ISSUED invoices) (PRD §3.5)."""
    acc_id = account["id"]
    total = 0
    for h in db.hires.values():
        if h["account_id"] == acc_id and h["lifecycle_status"] == "OPEN":
            total += hire_accrued_charge(h)
    for inv in db.invoices.values():
        if inv["account_id"] == acc_id and inv["status"] == "ISSUED":
            total += inv["total_cents"] - inv["paid_cents"]
    account["outstanding_charge_cents"] = total
    return total
