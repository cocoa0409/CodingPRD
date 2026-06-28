"""StopEvent endpoints (PRD §3.9).

Scheduled under a shipment (window-overlap guarded), read flat. Driver works a
stop SCHEDULED -> ARRIVED -> CLOSED; close computes detention + lumper fees and
rolls them into the shipment totals.
"""

from flask import Blueprint, request

from constants import STOP_KINDS, STOP_STATUSES
from db import store
from errors import err
from helpers import (
    get_shipment_or_404,
    get_stop_or_404,
    pagination_params,
    paginate,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response
from services import (
    detention_fee,
    lumper_fee,
    recompute_shipment_fee_totals,
    stop_window_collides,
)
from validators import as_enum, as_int, get_body, require

bp = Blueprint("stops", __name__)


@bp.route("/shipments/<sid>/stops", methods=["POST"])
def create_stop(sid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "PlatformAdmin"})
    shipment = get_shipment_or_404(sid)

    body = get_body(request)
    kind = as_enum(require(body, "kind"), "kind", STOP_KINDS)
    appointment_min = as_int(require(body, "appointment_min"), "appointment_min", minimum=0)

    pallets_handled = 0
    if body.get("pallets_handled") is not None:
        pallets_handled = as_int(body["pallets_handled"], "pallets_handled", minimum=0)
    compartments_touched = 1
    if body.get("compartments_touched") is not None:
        compartments_touched = as_int(
            body["compartments_touched"], "compartments_touched", minimum=1
        )

    # window-overlap gate (priority 14, ERR_STOP_WINDOW_OVERLAP)
    if stop_window_collides(appointment_min, sid):
        raise err(
            "ERR_STOP_WINDOW_OVERLAP",
            "Stop service window collides with an existing non-CLOSED stop",
        )

    rec = {
        "shipment_id": sid,
        "kind": kind,
        "appointment_min": appointment_min,
        "arrived_min": None,
        "departed_min": None,
        "pallets_handled": pallets_handled,
        "compartments_touched": compartments_touched,
        "status": "SCHEDULED",
        "detention_fee_cents": 0,
        "lumper_fee_cents": 0,
    }
    stamp_create(rec)
    store.stop_events[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/stops/<stop_id>", methods=["GET"])
def get_stop(stop_id):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_stop_or_404(stop_id)
    return object_response(serialize(rec), 200)


@bp.route("/stops", methods=["GET"])
def list_stops():
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()

    shipment_id = request.args.get("shipment_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if kind is not None and kind not in STOP_KINDS:
        raise err("ERR_INVALID_REQUEST", "Invalid kind filter")
    if status is not None and status not in STOP_STATUSES:
        raise err("ERR_INVALID_REQUEST", "Invalid status filter")

    records = list(store.stop_events.values())
    if shipment_id is not None:
        records = [r for r in records if r["shipment_id"] == shipment_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/shipments/<sid>/stops/<stop_id>/arrive", methods=["POST"])
def arrive_stop(sid, stop_id):
    _uid, role = authenticate()
    require_role(role, {"Driver"})
    # left-to-right path existence: shipment first, then stop
    shipment = get_shipment_or_404(sid)
    stop = get_stop_or_404(stop_id)
    if stop["shipment_id"] != sid:
        raise err("ERR_NOT_FOUND", "Stop does not belong to this shipment")

    body = get_body(request)
    arrived_min = as_int(require(body, "arrived_min"), "arrived_min")

    # state legality (priority 5)
    if stop["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Stop is not SCHEDULED")
    if shipment["status"] != "IN_TRANSIT":
        raise err("ERR_INVALID_STATE", "Shipment is not IN_TRANSIT")

    # interval validity (priority 13)
    if arrived_min < 0:
        raise err("ERR_INVALID_INTERVAL", "arrived_min must be >= 0")

    stop["arrived_min"] = arrived_min
    stop["status"] = "ARRIVED"
    touch(stop)
    return object_response(serialize(stop), 200)


@bp.route("/shipments/<sid>/stops/<stop_id>/close", methods=["POST"])
def close_stop(sid, stop_id):
    _uid, role = authenticate()
    require_role(role, {"Driver"})
    shipment = get_shipment_or_404(sid)
    stop = get_stop_or_404(stop_id)
    if stop["shipment_id"] != sid:
        raise err("ERR_NOT_FOUND", "Stop does not belong to this shipment")

    body = get_body(request)
    departed_min = as_int(require(body, "departed_min"), "departed_min")

    # state legality (priority 5)
    if stop["status"] != "ARRIVED":
        raise err("ERR_INVALID_STATE", "Stop is not ARRIVED")

    # interval validity (priority 13): departed_min >= arrived_min, non-negative
    if departed_min < 0:
        raise err("ERR_INVALID_INTERVAL", "departed_min must be >= 0")
    if departed_min < stop["arrived_min"]:
        raise err("ERR_INVALID_INTERVAL", "departed_min must be >= arrived_min")

    # optional refresh of fee inputs at close
    if body.get("pallets_handled") is not None:
        stop["pallets_handled"] = as_int(body["pallets_handled"], "pallets_handled", minimum=0)
    if body.get("compartments_touched") is not None:
        stop["compartments_touched"] = as_int(
            body["compartments_touched"], "compartments_touched", minimum=1
        )

    stop["departed_min"] = departed_min
    stop["detention_fee_cents"] = detention_fee(stop["arrived_min"], departed_min)
    stop["lumper_fee_cents"] = lumper_fee(stop["pallets_handled"], stop["compartments_touched"])
    stop["status"] = "CLOSED"
    touch(stop)

    # roll up onto shipment totals (mutates shipment per §2.11)
    recompute_shipment_fee_totals(shipment)
    return object_response(serialize(stop), 200)
