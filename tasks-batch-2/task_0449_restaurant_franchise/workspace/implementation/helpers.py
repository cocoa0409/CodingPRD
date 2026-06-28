"""Shared request/body/pagination helpers and cross-entity recompute logic."""
from flask import request

import db
import errors

# Pagination defaults (SCAFFOLD §1.0 pagination_defaults / PRD §2.3)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def get_body():
    """Parse JSON body, tolerating an empty body for no-input endpoints."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, names):
    for n in names:
        if body.get(n) is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % n)


def parse_pagination():
    """Read limit/offset query params. Out-of-range -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ASC (stable on _seq), page, build pagination meta.

    Results always sorted by created_at ascending so the oldest is first
    (PRD §2.3). _seq is the stable tie-break for equal millisecond timestamps.
    """
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# --- Existence resolution (PRD §2.7) ---
def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return rec


def require_fk(collection, rid):
    """A body FK that names a non-existent resource -> ERR_NOT_FOUND (PRD §2.7)."""
    if rid is None or collection.get(rid) is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Referenced resource does not exist")
    return collection[rid]


# --- Integer field validation ---
def require_non_negative_int(body, name, required=True, default=None):
    if name not in body or body.get(name) is None:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if val < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be >= 0" % name)
    return val


# =====================================================================
# Cross-entity recompute / cascade helpers
# =====================================================================
def franchisee_units(franchisee_id):
    return [u for u in db.units.values() if u["franchisee_id"] == franchisee_id]


def recompute_lifetime_net_sales(unit):
    """Sum net_sales_cents over all ACCEPTED SalesReports for this unit
    (PRD §3.8)."""
    total = 0
    for sr in db.sales_reports.values():
        if sr["unit_id"] == unit["id"] and sr["status"] == "ACCEPTED":
            total += sr["net_sales_cents"]
    unit["lifetime_net_sales_cents"] = total


def recompute_open_compliance_strikes(franchisee):
    """Count of this franchisee's units currently compliance_status SUSPENDED
    (entity field description). Kept as a derived count for reconciliation."""
    franchisee["open_compliance_strikes"] = sum(
        1 for u in db.units.values()
        if u["franchisee_id"] == franchisee["id"] and u["compliance_status"] == "SUSPENDED"
    )


def recompute_development_schedule(franchisee_id):
    """Recompute opened_units (count of franchisee's OPEN units) for every
    schedule of the franchisee, then re-evaluate status: advance ON_TRACK/BEHIND
    to SATISFIED when opened_units >= required_units (PRD §3.4)."""
    opened = sum(1 for u in db.units.values()
                 if u["franchisee_id"] == franchisee_id
                 and u["operational_status"] == "OPEN")
    for sched in db.development_schedules.values():
        if sched["franchisee_id"] != franchisee_id:
            continue
        changed = False
        if sched["opened_units"] != opened:
            sched["opened_units"] = opened
            changed = True
        if (sched["status"] in ("ON_TRACK", "BEHIND")
                and opened >= sched["required_units"]
                and sched["status"] != "SATISFIED"):
            sched["status"] = "SATISFIED"
            changed = True
        if changed:
            db.touch(sched)
