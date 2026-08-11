"""Shared validation, serialization, pagination, and derived-counter helpers."""

from flask import request

import db
import errors


# ---------- request body / field validation (priority 3) ----------

def get_body():
    if not request.is_json:
        raise errors.err(errors.ERR_INVALID_REQUEST, "request body must be JSON")
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "malformed JSON")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"invalid field: {field}")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    return v


def opt_int(body, field, default=None):
    v = body.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"invalid integer field: {field}")
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if v is None or v not in values:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, values, default=None):
    v = body.get(field, default)
    if v is not None and v not in values:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"invalid enum field: {field}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"missing or invalid datetime field: {field}")
    try:
        return db.parse_iso(v)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"invalid datetime field: {field}")


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"missing or invalid array field: {field}")
    return v


# ---------- existence (priority 4) ----------

def must_exist(table, entity_id, label="resource"):
    rec = table.get(entity_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, f"{label} not found: {entity_id}")
    return rec


# ---------- pagination ----------

def paginate(items):
    items = sorted(items, key=lambda r: r["created_at"])
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "invalid limit/offset")
    if limit < 1 or limit > 100:
        raise errors.err(errors.ERR_INVALID_REQUEST, "limit out of range")
    if offset < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "offset out of range")
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


# ---------- derived counters (PRD §2.8) ----------

def recompute_property_counters(prop_id):
    p = db.store.properties.get(prop_id)
    if not p:
        return
    units = [u for u in db.store.units.values() if u["property_id"] == prop_id]
    p["units_total"] = len(units)
    p["units_available_count"] = sum(1 for u in units if u["status"] == "AVAILABLE")
    p["units_reserved_count"] = sum(1 for u in units if u["status"] == "RESERVED")
    p["units_leased_count"] = sum(1 for u in units if u["status"] == "LEASED")
    p["units_out_of_service_count"] = sum(1 for u in units if u["status"] == "OUT_OF_SERVICE")


def recompute_campaign_counters(campaign_id):
    c = db.store.campaigns.get(campaign_id)
    if not c:
        return
    apps = [a for a in db.store.applications.values() if a["campaign_id"] == campaign_id]
    c["applications_received_count"] = sum(
        1 for a in apps if a["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "VERIFIED")
    )
    entries = [e for e in db.store.waitlist_entries.values() if e["campaign_id"] == campaign_id]
    c["waitlist_active_count"] = sum(1 for e in entries if e["status"] in ("RANKED", "OFFERED"))
    c["entries_leased_count"] = sum(1 for e in entries if e["status"] == "LEASED")


def recompute_verified_preference_categories(application_id):
    app = db.store.applications.get(application_id)
    if not app:
        return
    cats = [
        cl["category"]
        for cl in db.store.preference_claims.values()
        if cl["application_id"] == application_id and cl["status"] == "VERIFIED"
    ]
    # stable order
    order = {"LOCAL_RESIDENT": 0, "VETERAN": 1, "ACCESSIBILITY": 2}
    app["verified_preference_categories"] = sorted(set(cats), key=lambda c: order.get(c, 99))
