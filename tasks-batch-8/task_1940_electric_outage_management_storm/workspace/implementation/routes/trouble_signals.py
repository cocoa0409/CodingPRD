"""TroubleSignal endpoints: ingest, get, list.

Restore pings: payload must carry outage_id, outage must be WORKING/RESTORED,
born CLUSTERED. Other types must not carry outage_id and are born UNCLUSTERED.
occurred_at must not lie after the logical now (ERR_SIGNAL_IN_FUTURE).
"""
from flask import Blueprint, request

from db import db, parse_iso
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_SIGNAL_IN_FUTURE, ERR_PING_OUTAGE_STATE,
)
from services.core import (
    get_body, req_string, req_enum, req_datetime, paginate, new_append,
    get_feeder, get_outage, get_signal, serialize_signal, sort_created_asc,
    SIGNAL_TYPES,
)

bp = Blueprint("trouble_signals", __name__)


@bp.route("/om/trouble-signals", methods=["POST"])
def ingest_signal():
    require_roles(["TelemetryGateway"])
    body = get_body()
    stype = req_enum(body, "signal_type", SIGNAL_TYPES)
    feeder_id = req_string(body, "feeder_id")
    get_feeder(feeder_id)
    occurred_at = req_datetime(body, "occurred_at")

    # occurred_at must not lie after the logical now.
    if occurred_at > db.now():
        raise_err(ERR_SIGNAL_IN_FUTURE, "Signal occurred_at is after the logical now")

    outage_id = body.get("outage_id")
    if stype == "METER_RESTORE_PING":
        if outage_id is None:
            raise_err(ERR_INVALID_REQUEST,
                      "METER_RESTORE_PING requires outage_id")
        if not isinstance(outage_id, str):
            raise_err(ERR_INVALID_REQUEST, "outage_id must be a string")
        outage = get_outage(outage_id)
        if outage["outage_status"] not in ("WORKING", "RESTORED"):
            raise_err(ERR_PING_OUTAGE_STATE,
                      "Restore ping outage must be WORKING or RESTORED")
        disposition = "CLUSTERED"
        linked_outage = outage_id
    else:
        if outage_id is not None:
            raise_err(ERR_INVALID_REQUEST,
                      "Non-ping signal types must not carry outage_id")
        disposition = "UNCLUSTERED"
        linked_outage = None

    s = new_append()
    s.update({
        "signal_type": stype,
        "feeder_id": feeder_id,
        "outage_id": linked_outage,
        "occurred_at": body["occurred_at"],
        "disposition": disposition,
    })
    db.trouble_signals[s["id"]] = s
    return success_object(serialize_signal(s), status=201)


@bp.route("/om/trouble-signals/<sid>", methods=["GET"])
def get_one(sid):
    require_roles(ALL_ROLES)
    s = get_signal(sid)
    return success_object(serialize_signal(s))


@bp.route("/om/trouble-signals", methods=["GET"])
def list_signals():
    require_roles(ALL_ROLES)
    items = list(db.trouble_signals.values())
    feeder_id = request.args.get("feeder_id")
    outage_id = request.args.get("outage_id")
    signal_type = request.args.get("signal_type")
    disposition = request.args.get("disposition")
    if feeder_id is not None:
        items = [s for s in items if s["feeder_id"] == feeder_id]
    if outage_id is not None:
        items = [s for s in items if s.get("outage_id") == outage_id]
    if signal_type is not None:
        items = [s for s in items if s["signal_type"] == signal_type]
    if disposition is not None:
        items = [s for s in items if s["disposition"] == disposition]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_signal(s) for s in page], limit, offset, total)
