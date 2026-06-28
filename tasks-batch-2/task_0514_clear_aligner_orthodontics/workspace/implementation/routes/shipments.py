"""Shipment endpoints (PRD §3.8). Window overlap rules per §1.4."""
from datetime import timedelta

from flask import Blueprint, request

from clock import parse_iso8601
from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize, touch
from response import object_response, array_response
from services.calculations import EXPRESS_BUFFER_HOURS
from services.listing import paginate
from services.store import get_shipment, get_step, fk_step, shipments_for_step
from validation import get_body, require_str, require_enum, parse_pagination

bp = Blueprint("shipments", __name__)

CARRIERS = {"GROUND", "EXPRESS"}


def _parse_window(body, field):
    raw = body.get(field)
    if raw is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    if not isinstance(raw, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string." % field)
    dt = parse_iso8601(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 instant." % field)
    return raw, dt


def _active_windows(step_id, carrier_code):
    """Return (start_dt, end_dt) for non-CANCELLED shipments of this step with
    the given carrier."""
    out = []
    for s in shipments_for_step(step_id):
        if s["status"] == "CANCELLED":
            continue
        if s["carrier_code"] != carrier_code:
            continue
        out.append((parse_iso8601(s["window_start"]), parse_iso8601(s["window_end"])))
    return out


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    _, role = get_auth()
    require_roles(role, {"ManufacturingOps"})
    body = get_body()
    step_id = require_str(body, "step_id")
    carrier_code = require_enum(body, "carrier_code", CARRIERS)
    ws_raw, ws = _parse_window(body, "window_start")
    we_raw, we = _parse_window(body, "window_end")

    # FK existence
    step = fk_step(step_id)

    # state: the referenced step must be MANUFACTURED to book
    if step["status"] != "MANUFACTURED":
        raise err("ERR_INVALID_STATE", "Step must be MANUFACTURED to book a shipment.")

    # priority 16: window_start strictly before window_end
    if not (ws < we):
        raise err("ERR_WINDOW_INVERTED", "window_start must be before window_end.")

    if carrier_code == "GROUND":
        # priority 14: half-open [start, end) intervals; touching allowed
        for (ostart, oend) in _active_windows(step_id, "GROUND"):
            if ws < oend and ostart < we:
                raise err("ERR_GROUND_WINDOW_OVERLAP",
                          "GROUND window overlaps another GROUND window.")
    else:  # EXPRESS
        # priority 15: closed [start, end] intervals; touching collides; plus a
        # >= 24h buffer between express windows on the same step.
        buffer_delta = timedelta(hours=EXPRESS_BUFFER_HOURS)
        for (ostart, oend) in _active_windows(step_id, "EXPRESS"):
            # closed-interval overlap (touching endpoints collide)
            if ws <= oend and ostart <= we:
                raise err("ERR_EXPRESS_WINDOW_OVERLAP",
                          "EXPRESS window overlaps another EXPRESS window.")
            # buffer: a new window whose start is < 24h after a prior window's
            # end is rejected; symmetric check on both orderings.
            if ws >= oend and (ws - oend) < buffer_delta:
                raise err("ERR_EXPRESS_WINDOW_OVERLAP",
                          "EXPRESS window violates the 24h buffer.")
            if ostart >= we and (ostart - we) < buffer_delta:
                raise err("ERR_EXPRESS_WINDOW_OVERLAP",
                          "EXPRESS window violates the 24h buffer.")

    rec = base_record(common_fields=True)
    rec.update({
        "step_id": step_id,
        "carrier_code": carrier_code,
        "window_start": ws_raw,
        "window_end": we_raw,
        "status": "BOOKED",
    })
    db.shipments[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/shipments/<sid>", methods=["GET"])
def fetch_shipment(sid):
    _, role = get_auth()
    require_roles(role, {"Patient", "ManufacturingOps", "BillingAdmin"})
    rec = get_shipment(sid)
    return object_response(serialize(rec), status=200)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    _, role = get_auth()
    require_roles(role, {"Patient", "ManufacturingOps", "BillingAdmin"})
    limit, offset = parse_pagination()
    step_id = request.args.get("step_id")
    status = request.args.get("status")
    records = list(db.shipments.values())
    if step_id is not None:
        records = [s for s in records if s["step_id"] == step_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/shipments/<sid>/dispatch", methods=["POST"])
def dispatch(sid):
    _, role = get_auth()
    require_roles(role, {"ManufacturingOps"})
    rec = get_shipment(sid)
    if rec["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Shipment must be BOOKED to dispatch.")
    step = get_step(rec["step_id"])
    if step["status"] != "MANUFACTURED":
        raise err("ERR_INVALID_STATE", "Referenced step must be MANUFACTURED.")
    rec["status"] = "IN_TRANSIT"
    touch(rec)
    # cross-aggregate: step MANUFACTURED -> SHIPPED. record which shipment shipped it.
    step["status"] = "SHIPPED"
    step["_shipped_by"] = rec["id"]
    touch(step)
    return object_response(serialize(rec), status=200)


@bp.route("/shipments/<sid>/mark-delivered", methods=["POST"])
def mark_delivered(sid):
    _, role = get_auth()
    require_roles(role, {"ManufacturingOps"})
    rec = get_shipment(sid)
    if rec["status"] != "IN_TRANSIT":
        raise err("ERR_INVALID_STATE", "Shipment must be IN_TRANSIT to deliver.")
    rec["status"] = "DELIVERED"
    touch(rec)
    return object_response(serialize(rec), status=200)


@bp.route("/shipments/<sid>/cancel", methods=["POST"])
def cancel(sid):
    _, role = get_auth()
    require_roles(role, {"ManufacturingOps"})
    rec = get_shipment(sid)
    if rec["status"] not in ("BOOKED", "IN_TRANSIT"):
        raise err("ERR_INVALID_STATE", "Shipment must be BOOKED or IN_TRANSIT to cancel.")
    rec["status"] = "CANCELLED"
    touch(rec)
    # revert the step if it was shipped solely by this shipment
    step = db.aligner_steps.get(rec["step_id"])
    if (step is not None and step["status"] == "SHIPPED"
            and step.get("_shipped_by") == rec["id"]):
        step["status"] = "MANUFACTURED"
        step["_shipped_by"] = None
        touch(step)
    return object_response(serialize(rec), status=200)
