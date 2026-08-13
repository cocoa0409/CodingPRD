"""Shed keys: registry cap 4, strictest participation screen (PRD section 3.7)."""
from flask import Blueprint, request

import clock
import db
import services
from app_util import body
from errors import err, err_forbidden_role, err_invalid_request, err_not_found, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import pagination_args, parse_dt, req_str, require_field

bp = Blueprint("keys", __name__)

KEY_TARGETS = {"CHECKED_OUT", "RETURNED", "LOST", "RETIRED"}


@bp.post("/api/shed-keys")
def create_key():
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    data = body()
    key_code = req_str(data, "key_code")
    # uniqueness (tier 11)
    if any(k["key_code"] == key_code for k in db.keys.values()):
        raise err("ERR_KEY_CODE_TAKEN", "key_code already exists")
    # registry cap (tier 14): at most 4 non-RETIRED keys
    live = sum(1 for k in db.keys.values() if k["status"] != "RETIRED")
    if live >= services.KEY_REGISTRY_MAX:
        raise err("ERR_KEY_REGISTRY_FULL", "at most 4 non-RETIRED shed keys may exist")
    rec = services.create_record({
        "key_code": key_code,
        "current_holder_volunteer_id": None,
        "due_back_at": None,
        "status": "AVAILABLE",
    })
    db.keys[rec["id"]] = rec
    return ok(services.key_view(rec), status=201)


@bp.get("/api/shed-keys")
def list_keys():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.keys.values(),
        {"status": "status", "current_holder_volunteer_id": "current_holder_volunteer_id"},
        request.args, services.key_view,
    )
    total = len(items)
    return ok([services.key_view(k) for k in items[offset:offset + limit]],
              pagination=(limit, offset, total))


def _get_key(key_id):
    key = db.keys.get(key_id)
    if key is None:
        raise err_not_found("key")
    return key


@bp.get("/api/shed-keys/<keyId>")
def get_key(keyId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.key_view(_get_key(keyId)))


@bp.post("/api/shed-keys/<keyId>/transition")
def transition_key(keyId):
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin", "Coordinator"])
    key = _get_key(keyId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in KEY_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(KEY_TARGETS)}")
    if to_state == "RETIRED" and ctx.role != "GardenAdmin":
        raise err_forbidden_role()

    if to_state == "CHECKED_OUT":
        # body FK existence (tier 3)
        holder_id = require_field(data, "holder_volunteer_id")
        holder = db.volunteers.get(holder_id)
        if holder is None:
            raise err_not_found("volunteer")
        # shape (tier 5): due_back_at required and strictly after the clock
        due_raw = require_field(data, "due_back_at")
        due = parse_dt(due_raw, "due_back_at")
        if due <= clock.now():
            raise err_invalid_request("due_back_at must be strictly after the current time")
        # from-state (tier 6)
        if key["status"] != "AVAILABLE":
            raise err_state("KEY")
        # participation gates (tier 8) — strictest screen: standing must be GOOD
        if holder["orientation_status"] != "ORIENTED":
            raise err("ERR_ORIENTATION_REQUIRED", "holder orientation_status is not ORIENTED")
        if holder["waiver_status"] != "SIGNED":
            raise err("ERR_WAIVER_REQUIRED", "holder waiver_status is not SIGNED")
        if holder["standing"] != "GOOD":
            raise err("ERR_VOLUNTEER_NOT_IN_GOOD_STANDING",
                      "key checkout requires standing GOOD")
        # one key per volunteer (tier 14)
        if any(k["current_holder_volunteer_id"] == holder_id
               and k["status"] in {"CHECKED_OUT", "OVERDUE"} for k in db.keys.values()):
            raise err("ERR_KEY_LIMIT_EXCEEDED", "volunteer already holds a shed key")
        key["status"] = "CHECKED_OUT"
        key["current_holder_volunteer_id"] = holder_id
        key["due_back_at"] = due
        services.bump(key)

    elif to_state == "RETURNED":
        if key["status"] not in {"CHECKED_OUT", "OVERDUE"}:
            raise err_state("KEY")
        key["status"] = "AVAILABLE"
        key["current_holder_volunteer_id"] = None
        key["due_back_at"] = None
        services.bump(key)

    elif to_state == "LOST":
        if key["status"] not in {"CHECKED_OUT", "OVERDUE"}:
            raise err_state("KEY")
        holder = db.volunteers.get(key["current_holder_volunteer_id"])
        if holder is not None and holder["standing"] == "GOOD":
            holder["standing"] = "PROBATION"
            services.bump(holder)
        key["status"] = "LOST"
        key["current_holder_volunteer_id"] = None
        key["due_back_at"] = None
        services.bump(key)

    elif to_state == "RETIRED":
        if key["status"] != "AVAILABLE":
            raise err_state("KEY")
        key["status"] = "RETIRED"
        services.bump(key)

    return ok(services.key_view(key))
