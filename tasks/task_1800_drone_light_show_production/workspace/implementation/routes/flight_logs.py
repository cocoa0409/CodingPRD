"""FlightLog endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at
from middleware import require_role, get_auth
from response import success_object, success_list
from services import calc
from services.show import serialize_flight_log, touch
from routes.incidents import create_incident_record

bp = Blueprint("flight_logs", __name__)


@bp.route("/api/flight-logs", methods=["POST"])
def create_flight_log():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["show_event_id", "drone_id", "battery_consumed_pct",
                        "max_altitude_reached_ft", "max_deviation_m"])
    require_role("FleetManager")
    show_id = body["show_event_id"]
    drone_id = body["drone_id"]
    if not isinstance(show_id, str):
        raise errors.validation("show_event_id must be a string")
    if not isinstance(drone_id, str):
        raise errors.validation("drone_id must be a string")
    consumed = V.req_int(body, "battery_consumed_pct")
    max_alt = V.req_number(body, "max_altitude_reached_ft")
    max_dev = V.req_number(body, "max_deviation_m")
    if not (0 <= consumed <= 100):
        raise errors.validation("battery_consumed_pct must be within [0, 100]")
    if max_alt < 0:
        raise errors.validation("max_altitude_reached_ft must be >= 0")
    if max_dev < 0:
        raise errors.validation("max_deviation_m must be >= 0")

    show = DB.show_events.get(show_id)
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")
    drone = DB.drones.get(drone_id)
    if drone is None:
        raise errors.not_found("ERR_DRONE_NOT_FOUND", "drone not found")

    # state: show EXECUTED and drone holds a FLOWN assignment for the show
    if show["lifecycle_status"] != "EXECUTED":
        raise errors.conflict("ERR_INVALID_STATE", "flight logs require an EXECUTED show")
    assignment = None
    for aid in DB.insertion_order["assignments"]:
        a = DB.assignments[aid]
        if a["show_event_id"] == show_id and a["drone_id"] == drone_id and a["status"] == "FLOWN":
            assignment = a
            break
    if assignment is None:
        raise errors.conflict("ERR_INVALID_STATE", "drone does not hold a FLOWN assignment for this show")

    flagged = max_dev > calc.DEVIATION_FLAG_M

    fid = new_id()
    ts = wall_created_at()
    log = {
        "id": fid, "show_event_id": show_id, "drone_id": drone_id,
        "battery_consumed_pct": consumed,
        "max_altitude_reached_ft": max_alt,
        "max_deviation_m": max_dev,
        "flag_status": "FLAGGED" if flagged else "RECEIVED",
        "created_at": ts,
    }
    DB.flight_logs[fid] = log
    DB.insertion_order["flight_logs"].append(fid)

    # reconciliation order (pinned):
    # 1. assignment FLOWN -> RECONCILED
    assignment["status"] = "RECONCILED"
    touch(assignment)
    # 2. drone RESERVED -> AVAILABLE (only when no other ASSIGNED slot remains)
    from services.show import drone_release_if_unassigned
    drone_release_if_unassigned(drone)
    # 3. charge decrement floored at 0
    drone["charge_pct"] = max(0, drone["charge_pct"] - consumed)
    # 4. cycle increment
    drone["battery_cycle_count"] = drone.get("battery_cycle_count", 0) + 1
    # 5. cycle limit -> IN_MAINTENANCE
    if drone["battery_cycle_count"] >= calc.CYCLE_LIMIT and drone["status"] != "RETIRED":
        drone["status"] = "IN_MAINTENANCE"
    touch(drone)
    # 6. deviation flag -> auto MINOR incident
    if flagged:
        create_incident_record(show_id, drone_id, "MINOR",
                               f"Auto-filed: max deviation {max_dev}m exceeded threshold",
                               "AUTO_DEVIATION", "SYSTEM")

    return success_object(serialize_flight_log(log), 201)


@bp.route("/api/flight-logs/<flightLogId>", methods=["GET"])
def get_flight_log(flightLogId):
    get_auth()
    log = DB.flight_logs.get(flightLogId)
    if log is None:
        raise errors.not_found("ERR_FLIGHT_LOG_NOT_FOUND", "flight log not found")
    return success_object(serialize_flight_log(log))


@bp.route("/api/flight-logs", methods=["GET"])
def list_flight_logs():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    show_id = V.opt_string(request.args, "show_event_id")
    drone_id = V.opt_string(request.args, "drone_id")
    flag = V.opt_string(request.args, "flag_status")
    items = [DB.flight_logs[i] for i in DB.insertion_order["flight_logs"]]
    if show_id is not None:
        items = [f for f in items if f["show_event_id"] == show_id]
    if drone_id is not None:
        items = [f for f in items if f["drone_id"] == drone_id]
    if flag is not None:
        items = [f for f in items if f["flag_status"] == flag]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_flight_log(f) for f in page], limit, offset, total)
