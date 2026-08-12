"""Shared request-shape validators, pagination, pricing, limits, sweeps."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import err
from util import clock_date, parse_date, parse_datetime, touch, new_record

MISSING = object()

ADMIN_FEE_BPS = 250
FIT_TEST_VALIDITY_DAYS = 365
OVERDUE_GRACE_DAYS = 30


# ---------------------------------------------------------------------------
# Request body / shape validation (priority 0 -> ERR_VALIDATION_FAILED 400)
# ---------------------------------------------------------------------------

def body():
    """Parse the JSON request body; absent body -> {}. Non-object -> 400."""
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data()
        if raw and raw.strip():
            err("ERR_VALIDATION_FAILED", "request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION_FAILED", "request body must be a JSON object")
    return data


def field(b, name):
    v = b.get(name, MISSING)
    if v is MISSING or v is None:
        err("ERR_VALIDATION_FAILED", "missing required field: %s" % name)
    return v


def req_str(b, name):
    v = field(b, name)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION_FAILED", "field %s must be a non-empty string" % name)
    return v


def opt_str(b, name):
    v = b.get(name, MISSING)
    if v is MISSING or v is None:
        return None
    if not isinstance(v, str):
        err("ERR_VALIDATION_FAILED", "field %s must be a string" % name)
    return v


def req_int(b, name, minimum=None, maximum=None):
    v = field(b, name)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION_FAILED", "field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION_FAILED", "field %s out of range" % name)
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION_FAILED", "field %s out of range" % name)
    return v


def opt_int(b, name, minimum=None, maximum=None):
    v = b.get(name, MISSING)
    if v is MISSING or v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION_FAILED", "field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION_FAILED", "field %s out of range" % name)
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION_FAILED", "field %s out of range" % name)
    return v


def opt_bool(b, name):
    v = b.get(name, MISSING)
    if v is MISSING or v is None:
        return None
    if not isinstance(v, bool):
        err("ERR_VALIDATION_FAILED", "field %s must be a boolean" % name)
    return v


def req_enum(b, name, values):
    v = field(b, name)
    if not isinstance(v, str) or v not in values:
        err("ERR_VALIDATION_FAILED", "field %s must be one of %s" % (name, values))
    return v


def req_date(b, name):
    v = field(b, name)
    if not isinstance(v, str):
        err("ERR_VALIDATION_FAILED", "field %s must be a date string" % name)
    try:
        parse_date(v)
    except Exception:
        err("ERR_VALIDATION_FAILED", "field %s is not a valid ISO date" % name)
    return v


def req_datetime(b, name):
    v = field(b, name)
    if not isinstance(v, str):
        err("ERR_VALIDATION_FAILED", "field %s must be a datetime string" % name)
    try:
        parse_datetime(v)
    except Exception:
        err("ERR_VALIDATION_FAILED", "field %s is not a valid ISO datetime" % name)
    return v


def req_version_token(b, name):
    """OCC token: accept int or digit-string (test harness interpolates as string)."""
    v = field(b, name)
    if isinstance(v, bool):
        err("ERR_VALIDATION_FAILED", "field %s must be an integer" % name)
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.lstrip("-").isdigit():
        return int(v)
    err("ERR_VALIDATION_FAILED", "field %s must be an integer" % name)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit", MISSING)
    raw_offset = request.args.get("offset", MISSING)
    if raw_limit is MISSING:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_VALIDATION_FAILED", "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION_FAILED", "limit out of range [1, 100]")
    if raw_offset is MISSING:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_VALIDATION_FAILED", "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION_FAILED", "offset must be >= 0")
    return limit, offset


def paged(records, limit, offset):
    """Sort by creation ascending (insertion order) and slice."""
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    return ordered[offset:offset + limit], len(ordered)


def qparam(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ---------------------------------------------------------------------------
# Domain lookups
# ---------------------------------------------------------------------------

def get_or_404(store, rid, error_id):
    rec = store.get(rid)
    if rec is None:
        err(error_id, "resource not found: %s" % rid)
    return rec


def find_policy(job_role_id, item_id):
    for p in db.issuance_policies.values():
        if p["job_role_id"] == job_role_id and p["item_id"] == item_id:
            return p
    return None


def covering_override(employee_id, item_id):
    """The unique ACTIVE override whose closed window covers the current date."""
    today = clock_date()
    for o in db.overrides.values():
        if (o["employee_id"] == employee_id and o["item_id"] == item_id
                and o["status"] == "ACTIVE"
                and parse_date(o["valid_from"]) <= today <= parse_date(o["valid_until"])):
            return o
    return None


def latest_fit_test(employee, item_id):
    entries = [e for e in employee["fit_tests"] if e["item_id"] == item_id]
    if not entries:
        return None
    return max(entries, key=lambda e: (parse_date(e["tested_on"]), e.get("_seq", 0)))


def rolling_usage(employee_id, item_id, window_days):
    """SUM qty over POSTED lines with 0 <= age <= window_days * 24h (inclusive)."""
    now = db.clock
    span = timedelta(days=window_days)
    total = 0
    for t in db.issuances.values():
        if (t["employee_id"] == employee_id and t["item_id"] == item_id
                and t["status"] == "POSTED"):
            age = now - t["vended_at"]
            if timedelta(0) <= age <= span:
                total += t["qty"]
    return total


def month_cumulative(cost_center_id, item_id, vend_date):
    """POSTED qty for (cost center, item) in the vend's calendar month."""
    total = 0
    for t in db.issuances.values():
        if (t["cost_center_id"] == cost_center_id and t["item_id"] == item_id
                and t["status"] == "POSTED"):
            vd = t["vended_at"].date()
            if (vd.year, vd.month) == (vend_date.year, vend_date.month):
                total += t["qty"]
    return total


def resolve_price(item, vend_date, cumulative_before):
    """contract_price_resolution: tiered selection with pinned tie-breaks."""
    rows = [p for p in db.contract_prices.values()
            if p["item_id"] == item["id"]
            and parse_date(p["effective_from"]) <= vend_date <= parse_date(p["effective_to"])]
    candidates = [p for p in rows if p["min_period_qty"] <= cumulative_before]
    if candidates:
        # largest min_period_qty; tie -> latest effective_from, then earliest created
        pick = min(candidates,
                   key=lambda p: (-p["min_period_qty"],
                                  -parse_date(p["effective_from"]).toordinal(),
                                  p["_seq"]))
        return pick["unit_price_cents"]
    if rows:
        pick = min(rows,
                   key=lambda p: (p["min_period_qty"],
                                  -parse_date(p["effective_from"]).toordinal(),
                                  p["_seq"]))
        return pick["unit_price_cents"]
    return item["base_list_price_cents"]


def open_orders_qty(slot_id):
    return sum(o["qty"] for o in db.restock_orders.values()
               if o["slot_id"] == slot_id and o["status"] in ("SUGGESTED", "PICKED"))


def has_open_order(slot_id):
    return any(o["slot_id"] == slot_id and o["status"] in ("SUGGESTED", "PICKED")
               for o in db.restock_orders.values())


def create_restock_order(machine_id, slot, qty, source):
    suggested = max(0, slot["par_level"] - slot["on_hand_qty"] - open_orders_qty(slot["id"]))
    rec = new_record({
        "machine_id": machine_id,
        "slot_id": slot["id"],
        "item_id": slot["item_id"],
        "qty": qty,
        "suggested_qty": suggested,
        "source": source,
        "status": "SUGGESTED",
    })
    db.restock_orders[rec["id"]] = rec
    return rec


def par_trigger(slot):
    """restock_par_trigger: fire on on_hand <= par, non-serialized, no open order."""
    item = db.items.get(slot["item_id"])
    if item is None or item["serialized_tracking"]:
        return
    if slot["on_hand_qty"] <= slot["par_level"] and not has_open_order(slot["id"]):
        create_restock_order(slot["machine_id"], slot,
                             slot["capacity"] - slot["on_hand_qty"], "AUTO_PAR")


# ---------------------------------------------------------------------------
# Clock sweeps (POST /_clock/set_current_utc)
# ---------------------------------------------------------------------------

def run_sweeps():
    today = clock_date()
    # override expiry: ACTIVE and today > valid_until -> EXPIRED
    for o in db.overrides.values():
        if o["status"] == "ACTIVE" and today > parse_date(o["valid_until"]):
            o["status"] = "EXPIRED"
            touch(o)
    # inspection due / overdue quarantine (sequential within one sweep pass)
    for u in db.units.values():
        if (u["status"] == "ISSUED" and u.get("next_inspection_due_on")
                and today > parse_date(u["next_inspection_due_on"])):
            u["status"] = "INSPECTION_DUE"
            touch(u)
        if (u["status"] == "INSPECTION_DUE" and u.get("next_inspection_due_on")
                and today > parse_date(u["next_inspection_due_on"]) + timedelta(days=OVERDUE_GRACE_DAYS)):
            u["status"] = "QUARANTINED"  # no inspection_log entry on this path
            touch(u)
    # fit-test expiry: VALID and today > expires_on -> EXPIRED (expiry day inclusive)
    for e in db.employees.values():
        changed = False
        for ft in e["fit_tests"]:
            if ft["status"] == "VALID" and today > parse_date(ft["expires_on"]):
                ft["status"] = "EXPIRED"
                changed = True
        if changed:
            touch(e)
