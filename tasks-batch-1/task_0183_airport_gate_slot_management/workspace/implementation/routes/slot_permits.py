"""SlotPermit routes: request, confirm, redeem, forfeit, cancel."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success

bp = Blueprint("slot_permits", __name__)

READ_ROLES = {"OpsAdmin", "SlotCoordinator"}
MOVEMENT_TYPES = {"ARRIVAL", "DEPARTURE"}


@bp.route("/slot-permits", methods=["POST"])
def create_permit():
    _, role = authenticate()
    require_roles(role, {"SlotCoordinator"})
    body = helpers.get_body()

    # existence (priority 3): flight_id FK
    flight = None
    if body.get("flight_id") is not None:
        flight = db.flights.get(body["flight_id"])
        if flight is None:
            raise errors.not_found("Flight not found.")

    # well-formedness (priority 4)
    helpers.require_fields(body, ["flight_id", "movement_type", "slot_time_utc"])
    movement_type = body["movement_type"]
    helpers.check_enum(movement_type, MOVEMENT_TYPES, "movement_type")
    slot_dt, slot_raw = helpers.parse_dt(body["slot_time_utc"], "slot_time_utc")

    tolerance = 15
    if body.get("tolerance_minutes") is not None:
        tolerance = helpers.parse_int(body["tolerance_minutes"], "tolerance_minutes", minimum=0)

    rec = {
        "id": db.new_id(),
        "flight_id": flight["id"],
        "movement_type": movement_type,
        "slot_time_utc": slot_raw,
        "tolerance_minutes": tolerance,
        "status": "REQUESTED",
        "_slot_dt": slot_dt,
    }
    db.stamp_create(rec)
    db.slot_permits[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@bp.route("/slot-permits/<pid>", methods=["GET"])
def get_permit(pid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.slot_permits.get(pid)
    if rec is None:
        raise errors.not_found("Slot permit not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/slot-permits", methods=["GET"])
def list_permits():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    flight_id = request.args.get("flight_id")
    movement_type = request.args.get("movement_type")
    status = request.args.get("status")
    recs = list(db.slot_permits.values())
    if flight_id is not None:
        recs = [r for r in recs if r.get("flight_id") == flight_id]
    if movement_type is not None:
        recs = [r for r in recs if r.get("movement_type") == movement_type]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)


def _get_permit_or_404(pid):
    rec = db.slot_permits.get(pid)
    if rec is None:
        raise errors.not_found("Slot permit not found.")
    return rec


@bp.route("/slot-permits/<pid>/confirm", methods=["POST"])
def confirm(pid):
    _, role = authenticate()
    require_roles(role, {"SlotCoordinator"})
    permit = _get_permit_or_404(pid)
    # state from-check (priority 5)
    if permit["status"] != "REQUESTED":
        raise errors.invalid_state("Permit is not REQUESTED.")
    # slot uniqueness (priority 12): same movement_type + same slot minute with
    # CONFIRMED or USED elsewhere.
    minute_key = _minute_key(permit["_slot_dt"])
    for other in db.slot_permits.values():
        if other["id"] == permit["id"]:
            continue
        if other["movement_type"] != permit["movement_type"]:
            continue
        if other["status"] not in ("CONFIRMED", "USED"):
            continue
        if _minute_key(other["_slot_dt"]) == minute_key:
            raise errors.slot_double_booked()
    permit["status"] = "CONFIRMED"
    db.touch(permit)
    return success(helpers.serialize(permit), status=200)


def _minute_key(dt):
    # Truncate to whole-minute UTC instant.
    return int(dt.timestamp() // 60)


@bp.route("/slot-permits/<pid>/redeem", methods=["POST"])
def redeem(pid):
    _, role = authenticate()
    require_roles(role, {"SlotCoordinator"})
    permit = _get_permit_or_404(pid)
    # state from-check (priority 5)
    if permit["status"] != "CONFIRMED":
        raise errors.invalid_state("Permit is not CONFIRMED.")
    # slot compliance window (priority 14)
    now = db.clock.get("_epoch")
    if now is None:
        raise errors.slot_window_missed("Clock is not set; outside tolerance window.")
    slot_dt = permit["_slot_dt"]
    tol_sec = permit["tolerance_minutes"] * 60
    lo = slot_dt.timestamp() - tol_sec
    hi = slot_dt.timestamp() + tol_sec
    if not (lo <= now <= hi):
        raise errors.slot_window_missed()
    permit["status"] = "USED"
    db.touch(permit)
    return success(helpers.serialize(permit), status=200)


@bp.route("/slot-permits/<pid>/forfeit", methods=["POST"])
def forfeit(pid):
    _, role = authenticate()
    require_roles(role, {"SlotCoordinator"})
    permit = _get_permit_or_404(pid)
    if permit["status"] != "CONFIRMED":
        raise errors.invalid_state("Permit is not CONFIRMED.")
    permit["status"] = "FORFEITED"
    db.touch(permit)
    return success(helpers.serialize(permit), status=200)


@bp.route("/slot-permits/<pid>/cancel", methods=["POST"])
def cancel(pid):
    _, role = authenticate()
    require_roles(role, {"SlotCoordinator"})
    permit = _get_permit_or_404(pid)
    if permit["status"] not in ("REQUESTED", "CONFIRMED"):
        raise errors.invalid_state("Permit cannot be cancelled from its current state.")
    permit["status"] = "CANCELLED"
    db.touch(permit)
    return success(helpers.serialize(permit), status=200)
