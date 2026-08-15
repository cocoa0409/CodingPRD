"""Shared helpers: pagination, validation primitives, entity lookups."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from flask import request

import db
from db import _parse_iso
from errors import err_validation, err_not_found


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    """Parse limit/offset query params per scaffold defaults (limit 10, min 1, max 100, offset 0)."""
    try:
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise err_validation("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_validation("limit out of range")
    if offset < 0:
        raise err_validation("offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending, slice, return (page, total)."""
    ordered = sorted(items, key=lambda e: (e.get("created_at") or "", e.get("id") or ""))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def body():
    return request.get_json(silent=True) or {}


def require_field(payload, name):
    if name not in payload or payload[name] is None:
        raise err_validation(f"missing required field: {name}")
    return payload[name]


def optional_field(payload, name, default=None):
    v = payload.get(name)
    return v if v is not None else default


def require_int(payload, name):
    v = require_field(payload, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"{name} must be an integer")
    return v


def optional_int(payload, name, default=None):
    v = payload.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"{name} must be an integer")
    return v


def require_number(payload, name):
    v = require_field(payload, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_validation(f"{name} must be a number")
    return v


def optional_number(payload, name, default=None):
    v = payload.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_validation(f"{name} must be a number")
    return v


def require_string(payload, name):
    v = require_field(payload, name)
    if not isinstance(v, str) or not v:
        raise err_validation(f"{name} must be a non-empty string")
    return v


def optional_string(payload, name, default=None):
    v = payload.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err_validation(f"{name} must be a string")
    return v


def require_bool(payload, name):
    v = require_field(payload, name)
    if not isinstance(v, bool):
        raise err_validation(f"{name} must be a boolean")
    return v


def optional_bool(payload, name, default=None):
    v = payload.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err_validation(f"{name} must be a boolean")
    return v


def require_enum(payload, name, allowed):
    v = require_string(payload, name)
    if v not in allowed:
        raise err_validation(f"{name} must be one of {sorted(allowed)}")
    return v


def optional_enum(payload, name, allowed, default=None):
    v = payload.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"{name} must be one of {sorted(allowed)}")
    return v


def parse_datetime_field(payload, name, required=True):
    v = payload.get(name)
    if v is None:
        if required:
            raise err_validation(f"missing required field: {name}")
        return None
    if not isinstance(v, str):
        raise err_validation(f"{name} must be ISO8601 string")
    try:
        return db._parse_iso(v)
    except Exception:
        raise err_validation(f"{name} must be ISO8601 string")


# ---------------------------------------------------------------------------
# Entity lookups
# ---------------------------------------------------------------------------

def get_or_404(store, entity_id, msg="not found"):
    ent = store.get(entity_id)
    if ent is None:
        raise err_not_found(msg)
    return ent


def get_substation(sid):
    return get_or_404(db.substations, sid, "substation not found")


def get_policy(pid):
    return get_or_404(db.asset_class_policies, pid, "asset class policy not found")


def get_asset(aid):
    return get_or_404(db.assets, aid, "asset not found")


def get_outage_window(wid):
    return get_or_404(db.outage_windows, wid, "outage window not found")


def get_switching_step(sid):
    return get_or_404(db.switching_steps, sid, "switching step not found")


def get_test_event(tid):
    return get_or_404(db.test_events, tid, "test event not found")


def get_defect(did):
    return get_or_404(db.defects, did, "defect not found")


def get_work_order(wid):
    return get_or_404(db.work_orders, wid, "work order not found")


def get_spare_unit(suid):
    return get_or_404(db.spare_units, suid, "spare unit not found")


def get_spare_reservation(srid):
    return get_or_404(db.spare_reservations, srid, "spare reservation not found")


def get_relay_setting(rsid):
    return get_or_404(db.relay_settings, rsid, "relay setting not found")


def get_technician(tid):
    return get_or_404(db.technicians, tid, "technician not found")


def get_certification(cid):
    return get_or_404(db.technician_certifications, cid, "certification not found")


def get_environmental_inspection(eid):
    return get_or_404(db.environmental_inspections, eid, "environmental inspection not found")


def get_policy_for_class(asset_class):
    """Find the AssetClassPolicy for a given asset_class, or None."""
    for p in db.asset_class_policies.values():
        if p["asset_class"] == asset_class:
            return p
    return None


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def round2(value):
    """Round a numeric value to 2 decimal places, round-half-up. Returns float."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dec(value):
    """Convert to Decimal safely."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Half-open interval overlap
# ---------------------------------------------------------------------------

def intervals_overlap(a_start, a_end, b_start, b_end):
    """Check whether two half-open intervals [a_start,a_end) and [b_start,b_end) overlap."""
    return a_start < b_end and b_start < a_end
