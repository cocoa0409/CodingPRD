"""Park CRUD + state transitions."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_PARK_ADMIN,
    ROLE_PARK_RANGER,
    ROLE_SYSTEM_OPERATOR,
    ROLE_VISITOR,
    require_auth,
)
from ..envelope import parse_pagination, success_array, success_object
from ..errors import APIError
from ..serializers import serialize_park
from ..services.common import stamp_create, stamp_update
from ..store import get_store
from ..util import new_id
from ..validators import (
    get_json_body,
    optional_int,
    require_int,
    require_string,
    validate_park_code,
)
from ._helpers import lookup_park

bp = Blueprint("parks", __name__)


def _validate_window_minutes(value: int) -> None:
    if value <= 0 or 1440 % value != 0:
        raise APIError(
            "ERR_VALIDATION", "timed_entry_window_minutes must evenly divide 1440", 422
        )


@bp.post("/parks")
@require_auth([ROLE_PARK_ADMIN])
def create_park():
    body = get_json_body()
    name = require_string(body, "name", min_len=1, max_len=120)
    code = validate_park_code(require_string(body, "code", min_len=2, max_len=10))
    timezone = require_string(body, "timezone", min_len=1, max_len=100)
    daily_cap = require_int(body, "timed_entry_daily_capacity", min_val=0)
    window_minutes = optional_int(body, "timed_entry_window_minutes", default=60, min_val=1)
    _validate_window_minutes(window_minutes)
    store = get_store()
    with store.lock:
        if name.lower() in store.park_names:
            raise APIError("ERR_VALIDATION", "park name not unique", 422)
        if code in store.park_codes:
            raise APIError("ERR_VALIDATION", "park code not unique", 422)
        park = {
            "id": new_id(),
            "name": name,
            "code": code,
            "timezone": timezone,
            "timed_entry_daily_capacity": daily_cap,
            "timed_entry_window_minutes": window_minutes,
            "status": "OPEN",
        }
        stamp_create(park)
        store.parks[park["id"]] = park
        store.park_names[name.lower()] = park["id"]
        store.park_codes[code] = park["id"]
    return jsonify(success_object(serialize_park(park))), 201


@bp.get("/parks")
@require_auth([ROLE_PARK_ADMIN, ROLE_VISITOR, ROLE_PARK_RANGER, ROLE_SYSTEM_OPERATOR])
def list_parks():
    limit, offset = parse_pagination()
    store = get_store()
    items = sorted(store.parks.values(), key=lambda p: p["created_at"])
    total = len(items)
    page = [serialize_park(p) for p in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


@bp.get("/parks/<park_id>")
@require_auth([ROLE_PARK_ADMIN, ROLE_VISITOR, ROLE_PARK_RANGER, ROLE_SYSTEM_OPERATOR])
def get_park(park_id: str):
    park = lookup_park(park_id)
    return jsonify(success_object(serialize_park(park))), 200


@bp.patch("/parks/<park_id>")
@require_auth([ROLE_PARK_ADMIN])
def update_park(park_id: str):
    park = lookup_park(park_id)
    body = get_json_body()
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or body["version"] != park["version"]:
            raise APIError("ERR_VERSION_CONFLICT", "Stale version", 409)
    store = get_store()
    with store.lock:
        if "name" in body and body["name"] is not None:
            new_name = require_string(body, "name", min_len=1, max_len=120)
            if new_name.lower() != park["name"].lower():
                if new_name.lower() in store.park_names:
                    raise APIError("ERR_VALIDATION", "park name not unique", 422)
                store.park_names.pop(park["name"].lower(), None)
                park["name"] = new_name
                store.park_names[new_name.lower()] = park["id"]
            else:
                park["name"] = new_name
        if "timed_entry_daily_capacity" in body and body["timed_entry_daily_capacity"] is not None:
            cap = require_int(body, "timed_entry_daily_capacity", min_val=0)
            park["timed_entry_daily_capacity"] = cap
        if "timed_entry_window_minutes" in body and body["timed_entry_window_minutes"] is not None:
            wm = require_int(body, "timed_entry_window_minutes", min_val=1)
            _validate_window_minutes(wm)
            park["timed_entry_window_minutes"] = wm
        stamp_update(park)
    return jsonify(success_object(serialize_park(park))), 200


def _transition_park(park_id: str, allowed_from: set, to_status: str):
    park = lookup_park(park_id)
    if park["status"] not in allowed_from:
        raise APIError("ERR_INVALID_STATE", f"Park in status {park['status']}", 409)
    store = get_store()
    with store.lock:
        park["status"] = to_status
        stamp_update(park)
    return park


@bp.post("/parks/<park_id>/restrict")
@require_auth([ROLE_PARK_ADMIN])
def restrict_park(park_id: str):
    park = _transition_park(park_id, {"OPEN"}, "RESTRICTED")
    return jsonify(success_object(serialize_park(park))), 200


@bp.post("/parks/<park_id>/freeze")
@require_auth([ROLE_PARK_ADMIN])
def freeze_park(park_id: str):
    park = _transition_park(park_id, {"OPEN", "RESTRICTED"}, "FROZEN")
    return jsonify(success_object(serialize_park(park))), 200


@bp.post("/parks/<park_id>/reopen")
@require_auth([ROLE_PARK_ADMIN])
def reopen_park(park_id: str):
    park = _transition_park(park_id, {"RESTRICTED", "FROZEN"}, "OPEN")
    return jsonify(success_object(serialize_park(park))), 200
