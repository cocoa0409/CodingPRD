"""Shared helpers: payload validation, pagination, entity lookups, serializers."""
from flask import request

import db
from db import parse_iso
from errors import err_validation, err_not_found, err_ref_not_found


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10 min 1 max 100; offset default 0
# ---------------------------------------------------------------------------

def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise err_validation("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_validation("limit out of range (1..100)")
    if offset < 0:
        raise err_validation("offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (insertion order breaks ties), slice."""
    ordered = sorted(items, key=lambda e: (e.get("created_at") or "", e.get("_seq") or 0))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Payload helpers — all failures are ERR_VALIDATION (400)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_validation("request body must be a JSON object")
    return data


def require_field(payload, name):
    if name not in payload or payload[name] is None:
        raise err_validation(f"missing required field: {name}")
    return payload[name]


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


def require_int(payload, name, minimum=None, maximum=None, exclusive_min=False):
    v = require_field(payload, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"{name} must be an integer")
    _check_range(v, name, minimum, maximum, exclusive_min)
    return v


def optional_int(payload, name, default=None, minimum=None, maximum=None, exclusive_min=False):
    v = payload.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"{name} must be an integer")
    _check_range(v, name, minimum, maximum, exclusive_min)
    return v


def require_number(payload, name, minimum=None, maximum=None, exclusive_min=False):
    v = require_field(payload, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_validation(f"{name} must be a number")
    _check_range(v, name, minimum, maximum, exclusive_min)
    return v


def optional_number(payload, name, default=None, minimum=None, maximum=None, exclusive_min=False):
    v = payload.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_validation(f"{name} must be a number")
    _check_range(v, name, minimum, maximum, exclusive_min)
    return v


def _check_range(v, name, minimum, maximum, exclusive_min):
    if minimum is not None:
        if exclusive_min and not (v > minimum):
            raise err_validation(f"{name} must be > {minimum}")
        if not exclusive_min and not (v >= minimum):
            raise err_validation(f"{name} must be >= {minimum}")
    if maximum is not None and not (v <= maximum):
        raise err_validation(f"{name} must be <= {maximum}")


def require_enum(payload, name, allowed):
    v = require_field(payload, name)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"{name} must be one of {sorted(allowed)}")
    return v


def optional_enum(payload, name, allowed, default=None):
    v = payload.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"{name} must be one of {sorted(allowed)}")
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


def require_datetime(payload, name):
    v = require_field(payload, name)
    if not isinstance(v, str):
        raise err_validation(f"{name} must be an ISO8601 string")
    try:
        return parse_iso(v)
    except Exception:
        raise err_validation(f"{name} must be an ISO8601 string")


def optional_list(payload, name, default=None):
    v = payload.get(name)
    if v is None:
        return default
    if not isinstance(v, list):
        raise err_validation(f"{name} must be an array")
    return v


# ---------------------------------------------------------------------------
# Existence / reference lookups
# ---------------------------------------------------------------------------

def get_path(store, entity_id, msg="resource not found"):
    ent = store.get(entity_id) if entity_id is not None else None
    if ent is None:
        raise err_not_found(msg)
    return ent


def get_ref(store, entity_id, msg="referenced resource not found"):
    ent = store.get(entity_id) if entity_id is not None else None
    if ent is None:
        raise err_ref_not_found(msg)
    return ent


def require_ref(payload, store, name):
    """Required body reference: absent/None -> ERR_VALIDATION; dangling -> ERR_REFERENCE_NOT_FOUND."""
    v = payload.get(name)
    if v is None:
        raise err_validation(f"missing required field: {name}")
    ent = store.get(v)
    if ent is None:
        raise err_ref_not_found(f"{name} not found")
    return ent


def optional_ref(payload, store, name):
    """Optional body reference: absent -> None; dangling -> ERR_REFERENCE_NOT_FOUND."""
    v = payload.get(name)
    if v is None:
        return None
    ent = store.get(v)
    if ent is None:
        raise err_ref_not_found(f"{name} not found")
    return ent


def get_facility(fid):
    return get_ref(db.facilities, fid, "facility not found")


def get_facility_path(fid):
    return get_path(db.facilities, fid, "facility not found")


def get_schedule(sid):
    return get_path(db.rate_schedules, sid, "rate schedule not found")


def get_device(did):
    return get_path(db.access_devices, did, "access device not found")


def get_parker(pid):
    return get_path(db.parker_accounts, pid, "parker account not found")


def get_agreement(aid):
    return get_path(db.monthly_agreements, aid, "monthly agreement not found")


def get_credential(cid):
    return get_path(db.credentials, cid, "credential not found")


def get_session(sid):
    return get_path(db.parking_sessions, sid, "parking session not found")


def get_shift(sid):
    return get_path(db.shifts, sid, "shift not found")


def get_reconciliation(rid):
    return get_path(db.reconciliations, rid, "reconciliation not found")


def get_inspection(iid):
    return get_path(db.inspections, iid, "inspection not found")


def get_project(pid):
    return get_path(db.repair_projects, pid, "repair project not found")


def get_window(wid):
    return get_path(db.maintenance_windows, wid, "maintenance window not found")


def get_patrol(pid):
    return get_path(db.patrol_rounds, pid, "patrol round not found")


def get_incident(iid):
    return get_path(db.incidents, iid, "incident not found")


def get_charger(cid):
    return get_path(db.ev_chargers, cid, "EV charger not found")


def get_charging_session(sid):
    return get_path(db.charging_sessions, sid, "charging session not found")


def get_event(eid):
    return get_path(db.event_bookings, eid, "event booking not found")


# ---------------------------------------------------------------------------
# Facility derived-on-read figures (PRD 3.1 occupancy_pressure)
# ---------------------------------------------------------------------------

def facility_occupied(facility_id):
    return sum(1 for s in db.parking_sessions.values()
               if s["facility_id"] == facility_id and s["occupancy_state"] == "PARKED")


def facility_monthly_allocated(facility_id):
    return sum(1 for a in db.monthly_agreements.values()
               if a["facility_id"] == facility_id and a["agreement_status"] in ("ACTIVE", "SUSPENDED"))


def facility_view(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "total_spaces": f["total_spaces"],
        "monthly_capacity": f["monthly_capacity"],
        "event_pool_spaces": f["event_pool_spaces"],
        "levy_pct": f["levy_pct"],
        "posture": f["posture"],
        "closed_spaces": f["closed_spaces"],
        "occupied_spaces": facility_occupied(f["id"]),
        "monthly_allocated": facility_monthly_allocated(f["id"]),
        "capital_reserve_cents": f["capital_reserve_cents"],
        "deposit_liability_cents": f["deposit_liability_cents"],
        "cumulative_collected_cents": f["cumulative_collected_cents"],
        "last_close_date": f["last_close_date"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def public_view(ent):
    """Serialize any entity dict, dropping internal underscore-prefixed keys."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
