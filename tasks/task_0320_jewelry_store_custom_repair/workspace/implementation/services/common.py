"""Shared validation / OCC / serialization / ledger helpers."""
from datetime import datetime, timedelta, timezone

from flask import request

import db
from errors import ApiError


# ---------------------------------------------------------------- body parsing
def get_body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return body


# ---------------------------------------------------------------- field validation
def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: %s" % field)
    return val


def require_int(body, field, minimum=None, maximum=None, gt=None, ge=None):
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid integer field: %s" % field)
    if gt is not None and not (val > gt):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be > %s" % (field, gt))
    if ge is not None and not (val >= ge):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, ge))
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s below minimum %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s above maximum %s" % (field, maximum))
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def optional_number(body, field, default=None, ge=None, gt=None, minimum=None, maximum=None):
    """A number (int or float) that may be omitted."""
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number" % field)
    if gt is not None and not (val > gt):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be > %s" % (field, gt))
    if ge is not None and not (val >= ge):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, ge))
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s below minimum %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s above maximum %s" % (field, maximum))
    return val


def require_number(body, field, ge=None, gt=None):
    if field not in body or body.get(field) is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing field: %s" % field)
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number" % field)
    if gt is not None and not (val > gt):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be > %s" % (field, gt))
    if ge is not None and not (val >= ge):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, ge))
    return val


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return val


def require_datetime(body, field):
    raw = body.get(field)
    if not isinstance(raw, str) or raw == "":
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid datetime field: %s" % field)
    parse_dt(raw, field)
    return raw


def parse_dt(raw, field="timestamp"):
    """Parse an ISO 8601 UTC instant into an aware datetime for comparison."""
    if not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field)
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- FK resolution
def resolve_fk(collection, fk_id):
    """Resolve a body foreign key -> record, or ERR_FK_NOT_FOUND (PRD §2.5)."""
    if fk_id not in collection:
        raise ApiError("ERR_FK_NOT_FOUND", "Referenced resource does not exist")
    return collection[fk_id]


def resolve_path(collection, rid):
    """Resolve a path-referenced id -> record, or ERR_NOT_FOUND (PRD §2.5)."""
    if rid not in collection:
        raise ApiError("ERR_NOT_FOUND", "Resource not found")
    return collection[rid]


# ---------------------------------------------------------------- OCC
def require_own_version(rec, body):
    """expected_version present + matches the record's own version (PRD §2.7).

    Missing -> ERR_VERSION_REQUIRED (422); mismatch -> ERR_STALE_VERSION (412).
    """
    if "expected_version" not in body or body.get("expected_version") is None:
        raise ApiError("ERR_VERSION_REQUIRED", "expected_version is required")
    ev = body.get("expected_version")
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise ApiError("ERR_VERSION_REQUIRED", "expected_version must be an integer")
    if ev != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_version does not match current version")


def require_item_version(item, body):
    """expected_inventory_item_version present + matches the item's version (PRD §2.7)."""
    if "expected_inventory_item_version" not in body or body.get("expected_inventory_item_version") is None:
        raise ApiError("ERR_VERSION_REQUIRED", "expected_inventory_item_version is required")
    ev = body.get("expected_inventory_item_version")
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise ApiError("ERR_VERSION_REQUIRED", "expected_inventory_item_version must be an integer")
    if ev != item["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_inventory_item_version is stale")


# ---------------------------------------------------------------- store credit ledger
def post_ledger_entry(customer_id, direction, amount_cents, reason):
    """Append an immutable CreditLedgerEntry and recompute the customer balance."""
    rec = db.new_record(common_fields=False)
    rec["customer_id"] = customer_id
    rec["direction"] = direction
    rec["amount_cents"] = amount_cents
    rec["reason"] = reason
    db.credit_ledger[rec["id"]] = rec
    recompute_store_credit(customer_id)
    return rec


def recompute_store_credit(customer_id):
    """store_credit_balance = sum(CREDIT) - sum(DEBIT), exact, no rounding (PRD §2.9)."""
    total = 0
    for entry in db.credit_ledger.values():
        if entry["customer_id"] != customer_id:
            continue
        if entry["direction"] == "CREDIT":
            total += entry["amount_cents"]
        elif entry["direction"] == "DEBIT":
            total -= entry["amount_cents"]
    cust = db.customers.get(customer_id)
    if cust is not None:
        cust["store_credit_balance_cents"] = total
    return total


# ---------------------------------------------------------------- scheduling overlap
def bench_conflict(bench_id, new_start_raw, new_end_raw, exclude_ticket_id):
    """Half-open [start, end) overlap on the same bench (PRD §2.10)."""
    ns = parse_dt(new_start_raw)
    ne = parse_dt(new_end_raw)
    for t in db.repair_tickets.values():
        if t["id"] == exclude_ticket_id:
            continue
        if t.get("bench_id") != bench_id:
            continue
        if t.get("scheduled_start") is None or t.get("scheduled_end") is None:
            continue
        if t["status"] in ("PICKED_UP", "CANCELLED"):
            continue
        ts = parse_dt(t["scheduled_start"])
        te = parse_dt(t["scheduled_end"])
        if ns < te and ts < ne:
            return True
    return False


def appraisal_slot_conflict(appraiser_name, new_start_raw, new_end_raw):
    """Closed interval + 30-minute buffer for the same appraiser (PRD §2.10)."""
    buffer = timedelta(minutes=30)
    ns = parse_dt(new_start_raw)
    ne = parse_dt(new_end_raw)
    for a in db.appraisals.values():
        if a["appraiser_name"] != appraiser_name:
            continue
        if a["status"] not in ("DRAFT", "FINALIZED"):
            continue
        es = parse_dt(a["appointment_start"])
        ee = parse_dt(a["appointment_end"])
        if ns <= ee + buffer and es - buffer <= ne:
            return True
    return False
