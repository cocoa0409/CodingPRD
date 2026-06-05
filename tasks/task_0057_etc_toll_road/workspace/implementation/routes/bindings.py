from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch, now_iso
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, parse_dt, paginate,
                  sorted_by_created)
from serialize import public, public_list

bp = Blueprint("bindings", __name__)


def _resolve_fk(body, key, store, label):
    """Existence check for a body FK. Missing -> validation (deferred), absent id raises 404."""
    val = body.get(key)
    if val is None or not isinstance(val, str):
        return None  # structural problem handled later
    obj = store.get(val)
    if obj is None:
        raise err(errors.ERR_NOT_FOUND, f"{label} not found")
    return obj


@bp.post("/etc/transponder-bindings")
def create_binding():
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder"})
    body = get_body()

    # Existence (priority 3), validated left-to-right: transponder_id, vehicle_id
    transponder = _resolve_fk(body, "transponder_id", db.transponders, "Transponder")
    vehicle = _resolve_fk(body, "vehicle_id", db.vehicles, "Vehicle")

    # Ownership (priority 4): the AccountHolder must own targeted transponder/vehicle
    if role == "AccountHolder":
        if transponder is not None and transponder["account_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of transponder")
        if vehicle is not None and vehicle["account_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of vehicle")

    # Structural for FKs missing entirely is deferred; but state/business rules need them.
    if transponder is None:
        require_str(body, "transponder_id")  # raises ERR_VALIDATION
    if vehicle is None:
        require_str(body, "vehicle_id")

    # State (priority 5): transponder must be UNBOUND
    if transponder["status"] != "UNBOUND":
        raise err(errors.ERR_INVALID_STATE, "Transponder is not UNBOUND")

    # Ownership match (priority 6)
    if vehicle["account_id"] != transponder["account_id"]:
        raise err(errors.ERR_OWNERSHIP_MISMATCH,
                  "Vehicle and transponder belong to different accounts")

    # Account active (priority 7)
    acc = db.accounts.get(transponder["account_id"])
    if acc is None or acc["status"] != "ACTIVE":
        raise err(errors.ERR_ACCOUNT_NOT_ACTIVE, "Owning account is not ACTIVE")

    # Parse interval (structural for these fields at priority 18, but we need them for
    # the overlap business rule at priority 9). Validate them now.
    effective_from = parse_dt(body, "effective_from")
    effective_to = parse_dt(body, "effective_to", required=False, default=None)

    # Binding overlap (priority 9): half-open intervals on same vehicle
    for b in db.transponder_bindings.values():
        if b["vehicle_id"] != vehicle["id"] or b["status"] != "ACTIVE":
            continue
        ef = parse_iso_field(b["effective_from"])
        et = parse_iso_field(b["effective_to"]) if b["effective_to"] else None
        if _overlaps(effective_from, effective_to, ef, et):
            raise err(errors.ERR_BINDING_OVERLAP,
                      "Binding interval overlaps an active binding on this vehicle")

    # OCC (priority 17)
    expected_version = require_int(body, "expected_vehicle_version")
    if expected_version != vehicle["version"]:
        raise err(errors.ERR_STALE_VERSION, "Vehicle version is stale")

    binding = {
        "transponder_id": transponder["id"],
        "vehicle_id": vehicle["id"],
        "effective_from": body["effective_from"],
        "effective_to": body.get("effective_to"),
        "status": "ACTIVE",
    }
    init_common(binding)
    db.transponder_bindings[binding["id"]] = binding

    transponder["status"] = "BOUND"
    touch(transponder)
    touch(vehicle)  # increments Vehicle.version by 1

    return success(public(binding), status=201)


@bp.get("/etc/transponder-bindings/<bid>")
def get_binding(bid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    b = db.transponder_bindings.get(bid)
    if b is None:
        raise err(errors.ERR_NOT_FOUND, "Binding not found")
    if role == "AccountHolder":
        veh = db.vehicles.get(b["vehicle_id"])
        if veh is None or veh["account_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this binding")
    return success(public(b))


@bp.get("/etc/transponder-bindings")
def list_bindings():
    _, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    items = list(db.transponder_bindings.values())
    tid = request.args.get("transponder_id")
    vid = request.args.get("vehicle_id")
    if tid is not None:
        items = [b for b in items if b["transponder_id"] == tid]
    if vid is not None:
        items = [b for b in items if b["vehicle_id"] == vid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


@bp.post("/etc/transponder-bindings/<bid>/end")
def end_binding(bid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder"})
    b = db.transponder_bindings.get(bid)
    if b is None:
        raise err(errors.ERR_NOT_FOUND, "Binding not found")
    if role == "AccountHolder":
        veh = db.vehicles.get(b["vehicle_id"])
        if veh is None or veh["account_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this binding")
    transponder = db.transponders.get(b["transponder_id"])
    if transponder is None or transponder["status"] != "BOUND":
        raise err(errors.ERR_INVALID_STATE, "Transponder is not BOUND")
    b["status"] = "ENDED"
    b["effective_to"] = now_iso()
    touch(b)
    transponder["status"] = "UNBOUND"
    touch(transponder)
    return success(public(b))


# --- helpers ---
def parse_iso_field(v):
    from util import parse_iso
    return parse_iso(v)


def _overlaps(a_from, a_to, b_from, b_to):
    """Half-open [from, to). Open-ended (None to) treated as +inf."""
    a_end = a_to if a_to is not None else None
    b_end = b_to if b_to is not None else None
    # overlap if a_from < b_end and b_from < a_end (with None = +inf)
    left = (a_end is None) or (b_from < a_end)
    right = (b_end is None) or (a_from < b_end)
    return left and right
