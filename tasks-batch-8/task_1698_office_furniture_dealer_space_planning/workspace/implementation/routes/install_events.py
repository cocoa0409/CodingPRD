"""InstallEvent routes: scheduling with turnover-buffer crew exclusivity,
confirm/start/complete lifecycle, labor costing, reconfiguration asset moves."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE,
    ERR_CREW_NOT_ACTIVE,
    ERR_CREW_OVERLAP,
    ERR_ORDER_NOT_ACKNOWLEDGED,
    ERR_ORDER_BLOCKED,
    ERR_ASSET_NOT_MOVABLE,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import (
    get_or_404, new_entity, touch, dealership_of_order, recompute_install_posture,
)
from services.pricing import install_event_labor_cost, event_after_hours
from util import parse_date
from validate import body_dict, req_str, req_enum, req_int, opt_list, is_num

bp = Blueprint("install_events", __name__)

KINDS = {"NEW_INSTALL", "RECONFIGURATION"}


def _check_crew_overlap(crew_id, scheduled_date, start_minute, end_minute, buffer_minutes, exclude_id=None):
    """The new window, widened on each side by the turnover buffer, must not
    collide with any CONFIRMED or IN_PROGRESS event of the same crew/date."""
    widened_start = start_minute - buffer_minutes
    widened_end = end_minute + buffer_minutes
    for other in db["install_events"].values():
        if other["crew_id"] != crew_id:
            continue
        if other["scheduled_date"] != scheduled_date:
            continue
        if other["status"] not in ("CONFIRMED", "IN_PROGRESS"):
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if widened_start < other["end_minute"] and other["start_minute"] < widened_end:
            raise_error(ERR_CREW_OVERLAP,
                        f"crew {crew_id} has a conflicting event {other['id']} on {scheduled_date}")


def _validate_asset_moves_shape(asset_moves):
    for entry in asset_moves:
        if not isinstance(entry, dict):
            raise_error(ERR_INVALID_REQUEST, "each asset_moves entry must be an object")
        tag = entry.get("asset_tag_id")
        if not isinstance(tag, str) or not tag.strip():
            raise_error(ERR_INVALID_REQUEST, "asset_moves asset_tag_id must be a non-empty string")
        loc = entry.get("to_location")
        if not isinstance(loc, str) or not loc.strip():
            raise_error(ERR_INVALID_REQUEST, "asset_moves to_location must be a non-empty string")


@bp.route("/api/install-events", methods=["POST"])
def create_install_event():
    authorize(["ProjectManager"])
    body = body_dict()
    order_id = req_str(body, "order_id")
    crew_id = req_str(body, "crew_id")
    # priority 3: FK existence (including asset tags referenced in asset_moves)
    order = get_or_404("project_orders", order_id)
    crew = get_or_404("crews", crew_id)
    asset_moves = opt_list(body, "asset_moves")
    if asset_moves is not None:
        _validate_asset_moves_shape(asset_moves)
        for entry in asset_moves:
            get_or_404("asset_tags", entry["asset_tag_id"])
    # priority 5c: crew suspension blocks event creation
    if crew["status"] != "ACTIVE":
        raise_error(ERR_CREW_NOT_ACTIVE, f"crew {crew_id} is {crew['status']}")
    # priority 7d: order must be ACKNOWLEDGED or DELIVERED
    if order["status"] not in ("ACKNOWLEDGED", "DELIVERED"):
        raise_error(ERR_ORDER_NOT_ACKNOWLEDGED,
                    f"order is {order['status']}; install events require ACKNOWLEDGED or DELIVERED")
    # priority 8a: field shape
    kind = req_enum(body, "kind", KINDS)
    scheduled_date = req_str(body, "scheduled_date")
    if parse_date(scheduled_date) is None:
        raise_error(ERR_INVALID_REQUEST, "scheduled_date must be a YYYY-MM-DD date")
    start_minute = req_int(body, "start_minute", minv=0, maxv=1439)
    end_minute = req_int(body, "end_minute", minv=1, maxv=1440)
    labor_hours_estimated = body.get("labor_hours_estimated")
    if labor_hours_estimated is not None and (not is_num(labor_hours_estimated) or labor_hours_estimated < 0):
        raise_error(ERR_INVALID_REQUEST, "labor_hours_estimated must be a non-negative number")
    if asset_moves is not None and kind != "RECONFIGURATION":
        raise_error(ERR_INVALID_REQUEST, "asset_moves is supported for RECONFIGURATION events only")
    # priority 8b: window ordering (half-open interval: end strictly after start)
    if end_minute <= start_minute:
        raise_error(ERR_INVALID_DATE_RANGE, "end_minute must be strictly greater than start_minute")
    # priority 8d: crew overlap including the turnover buffer
    dealership = dealership_of_order(order)
    buffer_minutes = dealership["turnover_buffer_minutes"] if dealership else 0
    _check_crew_overlap(crew_id, scheduled_date, start_minute, end_minute, buffer_minutes)
    skeleton = {"start_minute": start_minute, "end_minute": end_minute}
    event = new_entity("install_events", {
        "order_id": order_id,
        "crew_id": crew_id,
        "kind": kind,
        "scheduled_date": scheduled_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "after_hours": event_after_hours(skeleton, dealership) if dealership else False,
        "labor_hours_estimated": labor_hours_estimated,
        "labor_hours_actual": None,
        "labor_cost_cents": None,
        "asset_moves": asset_moves,
        "status": "TENTATIVE",
    })
    recompute_install_posture(order)
    return success_object(public(event), status=201)


@bp.route("/api/install-events", methods=["GET"])
def list_install_events():
    authorize(ALL_ROLES)
    return list_response("install_events", ["order_id", "crew_id", "scheduled_date", "status"])


@bp.route("/api/install-events/<event_id>", methods=["GET"])
def get_install_event(event_id):
    authorize(ALL_ROLES)
    return get_response("install_events", event_id)


@bp.route("/api/install-events/<event_id>/confirm", methods=["POST"])
def confirm_install_event(event_id):
    authorize(["ProjectManager"])
    event = get_or_404("install_events", event_id)
    # priority 4: transition exists from TENTATIVE; order must still be ACK/DEL
    if event["status"] != "TENTATIVE":
        raise_error(ERR_INVALID_STATE, f"cannot confirm an event in status {event['status']}")
    order = get_or_404("project_orders", event["order_id"])
    if order["status"] not in ("ACKNOWLEDGED", "DELIVERED"):
        raise_error(ERR_INVALID_STATE,
                    f"cannot confirm an event while the order is {order['status']}")
    crew = get_or_404("crews", event["crew_id"])
    # priority 5c
    if crew["status"] != "ACTIVE":
        raise_error(ERR_CREW_NOT_ACTIVE, f"crew {event['crew_id']} is {crew['status']}")
    # priority 8d: overlap re-checked, excluding this event
    dealership = dealership_of_order(order)
    buffer_minutes = dealership["turnover_buffer_minutes"] if dealership else 0
    _check_crew_overlap(event["crew_id"], event["scheduled_date"], event["start_minute"],
                        event["end_minute"], buffer_minutes, exclude_id=event["id"])
    event["status"] = "CONFIRMED"
    touch(event)
    recompute_install_posture(order)
    return success_object(public(event))


@bp.route("/api/install-events/<event_id>/unconfirm", methods=["POST"])
def unconfirm_install_event(event_id):
    authorize(["ProjectManager"])
    event = get_or_404("install_events", event_id)
    if event["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, f"cannot unconfirm an event in status {event['status']}")
    event["status"] = "TENTATIVE"
    touch(event)
    order = db["project_orders"].get(event["order_id"])
    if order is not None:
        recompute_install_posture(order)
    return success_object(public(event))


@bp.route("/api/install-events/<event_id>/start", methods=["POST"])
def start_install_event(event_id):
    authorize(["ProjectManager"])
    event = get_or_404("install_events", event_id)
    if event["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, f"cannot start an event in status {event['status']}")
    order = get_or_404("project_orders", event["order_id"])
    # priority 5d: a BLOCKED install posture blocks event start
    if order["install_posture"] == "BLOCKED":
        raise_error(ERR_ORDER_BLOCKED, "the order's install posture is BLOCKED")
    event["status"] = "IN_PROGRESS"
    touch(event)
    recompute_install_posture(order)
    return success_object(public(event))


@bp.route("/api/install-events/<event_id>/complete", methods=["POST"])
def complete_install_event(event_id):
    authorize(["ProjectManager"])
    event = get_or_404("install_events", event_id)
    if event["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, f"cannot complete an event in status {event['status']}")
    body = body_dict()
    labor_hours_actual = body.get("labor_hours_actual")
    if not is_num(labor_hours_actual) or labor_hours_actual < 0:
        raise_error(ERR_INVALID_REQUEST, "labor_hours_actual is required and must be a non-negative number")
    order = get_or_404("project_orders", event["order_id"])
    # priority 8g: all referenced assets must be movable before any move applies
    moves = event.get("asset_moves") or []
    if event["kind"] == "RECONFIGURATION":
        for entry in moves:
            asset = db["asset_tags"].get(entry["asset_tag_id"])
            if asset is None or asset["status"] == "DISPOSED":
                raise_error(ERR_ASSET_NOT_MOVABLE,
                            f"asset {entry['asset_tag_id']} is DISPOSED and cannot be moved")
    # labor cost: rounded once per event at completion (PRD 2.5)
    contract = db["pricing_contracts"].get(order["contract_id"])
    dealership = dealership_of_order(order)
    event["labor_hours_actual"] = labor_hours_actual
    if contract is not None and dealership is not None:
        event["labor_cost_cents"] = install_event_labor_cost(event, order, contract, dealership)
    event["status"] = "COMPLETED"
    touch(event)
    # apply reconfiguration asset moves
    if event["kind"] == "RECONFIGURATION":
        for entry in moves:
            asset = db["asset_tags"][entry["asset_tag_id"]]
            asset["current_location"] = entry["to_location"]
            if entry["to_location"] == "STORAGE":
                if asset["status"] == "IN_SERVICE":
                    asset["status"] = "IN_STORAGE"
            else:
                if asset["status"] == "IN_STORAGE":
                    asset["status"] = "IN_SERVICE"
            touch(asset)
    recompute_install_posture(order)
    return success_object(public(event))


@bp.route("/api/install-events/<event_id>/cancel", methods=["POST"])
def cancel_install_event(event_id):
    authorize(["ProjectManager"])
    event = get_or_404("install_events", event_id)
    if event["status"] not in ("TENTATIVE", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE, f"cannot cancel an event in status {event['status']}")
    event["status"] = "CANCELLED"
    touch(event)
    order = db["project_orders"].get(event["order_id"])
    if order is not None:
        recompute_install_posture(order)
    return success_object(public(event))
