"""Investigations and the bounded tracer loop (PRD §3.10)."""

from flask import Blueprint, request

from db import STORE, base_entity, pub, touch
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_TRACER_LIMIT_EXCEEDED,
    ApiError,
)
from listing import list_response
from middleware import ALL_INTERNAL, get_body, require_fk, require_roles, validate_body
from response import ok
from services import get_or_404, lazy_eval_wire

bp = Blueprint("investigations", __name__, url_prefix="/wire-ops")

_TYPES = {"TRACER", "NON_RECEIPT", "VALUE_DISPUTE"}


@bp.post("/investigations")
def create_investigation():
    uid, role = require_roles("WireInvestigator")
    data = get_body()
    require_fk(data, "wire_id", STORE.wires, "wire")
    validate_body(data, {
        "wire_id": ("str", True, None),
        "type": ("str", True, _TYPES),
        "note": ("str", True, None),
    })
    inv = base_entity()
    inv.update({
        "wire_id": data["wire_id"],
        "type": data["type"],
        "note": data["note"],
        "opened_by": uid,
        "status": "OPEN",
        "max_tracers": 3,
        "tracer_count": 0,
    })
    STORE.investigations[inv["id"]] = inv
    return ok(pub(inv), 201)


@bp.get("/investigations")
def list_investigations():
    require_roles(*ALL_INTERNAL)
    items = list(STORE.investigations.values())
    wire_id = request.args.get("wire_id")
    status = request.args.get("status")
    if wire_id is not None:
        items = [i for i in items if i["wire_id"] == wire_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items)


@bp.get("/investigations/<iid>")
def get_investigation(iid):
    require_roles(*ALL_INTERNAL)
    inv = get_or_404(STORE.investigations, iid, "investigation")
    return ok(pub(inv))


def _messages(iid):
    return [m for m in STORE.tracers.values() if m["investigation_id"] == iid]


@bp.post("/investigations/<iid>/tracers")
def dispatch_tracer(iid):
    uid, role = require_roles("WireInvestigator")
    inv = get_or_404(STORE.investigations, iid, "investigation")
    data = get_body()
    validate_body(data, {"body": ("str", True, None)})
    if inv["status"] != "OPEN":
        raise ApiError(*ERR_INVALID_STATE, "Tracers may be dispatched only while the investigation is OPEN.")
    if inv["tracer_count"] >= inv["max_tracers"]:
        raise ApiError(*ERR_TRACER_LIMIT_EXCEEDED, "Tracer dispatch cap (3) reached.")
    msg = base_entity()
    msg.update({
        "investigation_id": iid,
        "direction": "OUTBOUND",
        "body": data["body"],
        "sequence_no": len(_messages(iid)) + 1,
    })
    STORE.tracers[msg["id"]] = msg
    inv["tracer_count"] += 1
    inv["status"] = "AWAITING_RESPONSE"
    touch(inv)
    return ok(pub(msg), 201)


@bp.post("/investigations/<iid>/respond")
def respond_investigation(iid):
    uid, role = require_roles("WireInvestigator")
    inv = get_or_404(STORE.investigations, iid, "investigation")
    data = get_body()
    validate_body(data, {"body": ("str", True, None)})
    if inv["status"] != "AWAITING_RESPONSE":
        raise ApiError(*ERR_INVALID_STATE,
                       "A counterparty reply may be registered only while AWAITING_RESPONSE.")
    msg = base_entity()
    msg.update({
        "investigation_id": iid,
        "direction": "INBOUND",
        "body": data["body"],
        "sequence_no": len(_messages(iid)) + 1,
    })
    STORE.tracers[msg["id"]] = msg
    # INBOUND replies do not consume the tracer budget.
    inv["status"] = "OPEN"
    touch(inv)
    return ok(pub(msg))


@bp.post("/investigations/<iid>/resolve")
def resolve_investigation(iid):
    uid, role = require_roles("WireInvestigator")
    inv = get_or_404(STORE.investigations, iid, "investigation")
    data = get_body()
    if data:
        raise ApiError(*ERR_INVALID_REQUEST, "This endpoint does not accept a request body.")
    if inv["status"] != "OPEN":
        raise ApiError(*ERR_INVALID_STATE, "Only an OPEN investigation can be resolved.")
    inv["status"] = "RESOLVED"
    touch(inv)
    return ok(pub(inv))


@bp.post("/investigations/<iid>/close")
def close_investigation(iid):
    uid, role = require_roles("WireInvestigator")
    inv = get_or_404(STORE.investigations, iid, "investigation")
    data = get_body()
    if data:
        raise ApiError(*ERR_INVALID_REQUEST, "This endpoint does not accept a request body.")
    if inv["status"] not in ("OPEN", "AWAITING_RESPONSE"):
        raise ApiError(*ERR_INVALID_STATE,
                       "Only an OPEN or AWAITING_RESPONSE investigation can be closed.")
    inv["status"] = "CLOSED"
    touch(inv)
    return ok(pub(inv))


@bp.get("/investigations/<iid>/tracers")
def list_tracers(iid):
    require_roles(*ALL_INTERNAL)
    get_or_404(STORE.investigations, iid, "investigation")
    items = sorted(_messages(iid), key=lambda m: m["sequence_no"])
    return list_response(items, sort_key=lambda m: m["sequence_no"])
