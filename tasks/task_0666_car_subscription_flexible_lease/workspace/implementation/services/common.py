"""Shared helpers: body parsing/validation, FK resolution, fleet recompute, listing."""
from flask import request

import errors
from db import db, touch
from services import calc, serialize


def get_body():
    """Parse JSON body; missing/invalid -> empty dict (presence checks happen per field)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}")
    return body[name]


def require_int(body, name, min_value=None, max_value=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    if min_value is not None and val < min_value:
        raise errors.invalid_request(f"Field {name} must be >= {min_value}.")
    if max_value is not None and val > max_value:
        raise errors.invalid_request(f"Field {name} must be <= {max_value}.")
    return val


def optional_int(body, name, default, min_value=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    if min_value is not None and val < min_value:
        raise errors.invalid_request(f"Field {name} must be >= {min_value}.")
    return val


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field {name} must be a string.")
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field {name} must be one of {sorted(allowed)}.")
    return val


def resolve(collection, entity_id):
    """Existence check (priority 4, ERR_NOT_FOUND)."""
    rec = collection.get(entity_id)
    if rec is None:
        raise errors.not_found()
    return rec


# --- Fleet recompute (PRD §2.6) ---
def recompute_fleet(fleet_id):
    """Recompute a fleet's derived counters and bump it as a mutation (PRD §2.6:
    'a parent's reconciliation is itself a mutation of that parent')."""
    fleet = db.fleets.get(fleet_id)
    if fleet is None:
        return
    total, in_use = serialize._fleet_counts(fleet_id)
    fleet["total_vehicles"] = total
    fleet["in_use_count"] = in_use
    fleet["utilization_pct"] = calc.utilization_pct(in_use, total)
    touch(fleet)


# --- Listing / pagination / sorting ---
def paginate_sorted(records, limit, offset):
    """Sort by created_at asc (PRD §2.3), tie-broken by insertion seq for determinism."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def filter_equals(records, field, value):
    if value is None:
        return records
    return [r for r in records if r.get(field) == value]
