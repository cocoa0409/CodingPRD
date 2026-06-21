"""EntryWindow fetch + state-machine endpoints (PRD §3.1, §3.8)."""
from flask import Blueprint

import errors
from db import db, new_id, add_common_fields, touch
from errors import ApiError
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.common import get_json_body, optional_bool
from services.lookup import get_park, get_entry_window, get_guest
from services.windows import recompute_open_window_count

bp = Blueprint("windows", __name__)


@bp.route("/entry-windows/<wid>", methods=["GET"])
def get_window(wid):
    _, role = authenticate()
    require_role(role, {"ParkManager", "GateAgent", "Guest"})
    rec = get_entry_window(wid)
    return success(serialize.entry_window(rec))


@bp.route("/entry-windows/<wid>/restrict", methods=["POST"])
def restrict_window(wid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    win = get_entry_window(wid)
    if win["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "restrict requires window status OPEN")
    win["status"] = "RESTRICTED"
    touch(win)
    park = db.parks[win["park_id"]]
    recompute_open_window_count(park)
    return success(serialize.entry_window(win))


@bp.route("/entry-windows/<wid>/reopen", methods=["POST"])
def reopen_window(wid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    win = get_entry_window(wid)
    if win["status"] != "RESTRICTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "reopen requires window status RESTRICTED")
    win["status"] = "OPEN"
    touch(win)
    park = db.parks[win["park_id"]]
    recompute_open_window_count(park)
    return success(serialize.entry_window(win))


@bp.route("/entry-windows/<wid>/close", methods=["POST"])
def close_window(wid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    win = get_entry_window(wid)
    body = get_json_body()
    force = optional_bool(body, "force", False)
    if win["status"] not in {"OPEN", "RESTRICTED"}:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "close requires window status OPEN or RESTRICTED")
    if not force and not (win["admitted_count"] == 0 and win["reserved_count"] == 0):
        # PRD §3.1: closing permitted only when counts are both zero unless force.
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "close requires zero reserved/admitted counts unless force set")
    was_open = win["status"] == "OPEN"
    win["status"] = "CLOSED"
    touch(win)
    if was_open:
        park = db.parks[win["park_id"]]
        recompute_open_window_count(park)
    return success(serialize.entry_window(win))


@bp.route("/entry-windows/<wid>/rain-out", methods=["POST"])
def rain_out_window(wid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    win = get_entry_window(wid)
    park = db.parks[win["park_id"]]

    # Precondition: Park.weather_status == RAINED_OUT (SCAFFOLD state machine).
    if park["weather_status"] != "RAINED_OUT":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "rain-out requires park weather_status RAINED_OUT")
    if win["status"] not in {"OPEN", "RESTRICTED"}:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "rain-out requires window status OPEN or RESTRICTED")

    was_open = win["status"] == "OPEN"

    # Cascade 1: admissions on this window in CONFIRMED or FROZEN -> RAINED_OUT.
    for adm in db.admissions.values():
        if adm["entry_window_id"] == win["id"] and adm["status"] in {"CONFIRMED", "FROZEN"}:
            adm["status"] = "RAINED_OUT"
            touch(adm)
            if adm["guest_id"]:
                _issue_rain_check(park, adm["guest_id"], "ADMISSION", adm["id"])

    # Cascade 2: cabana rentals on this window in CONFIRMED or HELD -> RAINED_OUT.
    for cr in db.cabana_rentals.values():
        if cr["entry_window_id"] == win["id"] and cr["status"] in {"CONFIRMED", "HELD"}:
            cr["status"] = "RAINED_OUT"
            touch(cr)
            order = db.orders.get(cr["order_id"])
            guest_id = order["guest_id"] if order else None
            _issue_rain_check(park, guest_id, "CABANA_RENTAL", cr["id"])

    win["reserved_count"] = 0
    win["status"] = "RAINED_OUT"
    touch(win)
    if was_open:
        recompute_open_window_count(park)
    return success(serialize.entry_window(win))


def _issue_rain_check(park, guest_id, source_kind, source_ref_id):
    rec = {
        "id": new_id(),
        "park_id": park["id"],
        "guest_id": guest_id,
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
        "value_cents": park["rain_check_value_cents"],
        "status": "ISSUED",
    }
    add_common_fields(rec)
    db.rain_checks[rec["id"]] = rec
    return rec
