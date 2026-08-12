"""PropShipment and ContinuityRecord endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
import util
from services import cascade

bp = Blueprint("shipments", __name__)

SHIP_TARGETS = ["DISPATCHED", "DELIVERED", "STAGED", "RETURN_REQUESTED",
                "IN_RETURN", "RETURNED", "CANCELLED"]

# legal steps: from -> {to: requires_active_contract}
SHIP_TRANSITIONS = {
    "PENDING": {"DISPATCHED": True, "CANCELLED": False},
    "DISPATCHED": {"DELIVERED": False},
    "DELIVERED": {"STAGED": False, "RETURN_REQUESTED": False},
    "STAGED": {"RETURN_REQUESTED": False},
    "RETURN_REQUESTED": {"DISPATCHED": True, "IN_RETURN": False},
    "IN_RETURN": {"RETURNED": False},
}


def shipment_view(s):
    return {k: s[k] for k in ("id", "contract_id", "item_description", "quantity",
                              "status", "created_at", "updated_at", "version")}


def continuity_view(r):
    return {k: r[k] for k in ("id", "contract_id", "shipment_id",
                              "scene_timecode_seconds", "note", "status", "created_at")}


def _contract_or_404(cid):
    c = db.contracts.get(cid)
    if c is None:
        raise errors.not_found("Contract not found")
    return c


@bp.route("/contracts/<cid>/shipments", methods=["POST"])
def create_shipment(cid):
    middleware.require_roles("IntegrationManager")
    body = middleware.get_json_body()
    item = util.req_str(body, "item_description")
    qty = util.req_int(body, "quantity", minimum=1)
    c = _contract_or_404(cid)
    if c["status"] == "TERMINATED":
        raise errors.already_terminal("Contract is TERMINATED")
    if c["status"] not in ("PENDING_SIGNATURE", "ACTIVE"):
        raise errors.invalid_state("Contract is not PENDING_SIGNATURE or ACTIVE")
    ent = util.new_entity()
    ent.update({"contract_id": cid, "item_description": item, "quantity": qty,
                "status": "PENDING"})
    db.shipments[ent["id"]] = ent
    return response.success_object(shipment_view(ent), 201)


@bp.route("/contracts/<cid>/shipments", methods=["GET"])
def list_contract_shipments(cid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "ProductionRep")
    _contract_or_404(cid)
    limit, offset = util.pagination_params()
    items = [x for x in db.shipments.values() if x["contract_id"] == cid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([shipment_view(x) for x in page], limit, offset, total)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "ProductionRep")
    s = db.shipments.get(sid)
    if s is None:
        raise errors.not_found("Shipment not found")
    return response.success_object(shipment_view(s))


@bp.route("/shipments/<sid>/advance", methods=["POST"])
def advance_shipment(sid):
    middleware.require_roles("IntegrationManager")
    body = middleware.get_json_body()
    to = util.req_enum(body, "to", SHIP_TARGETS)
    s = db.shipments.get(sid)
    if s is None:
        raise errors.not_found("Shipment not found")
    if s["status"] in ("RETURNED", "CANCELLED"):
        raise errors.already_terminal("Shipment is terminal")
    allowed = SHIP_TRANSITIONS.get(s["status"], {})
    if to not in allowed:
        raise errors.invalid_state(
            "Shipment cannot advance from %s to %s" % (s["status"], to))
    contract = db.contracts.get(s["contract_id"])
    if allowed[to] and (contract is None or contract["status"] != "ACTIVE"):
        raise errors.invalid_state("This advance requires the contract to be ACTIVE")
    s["status"] = to
    util.touch(s)
    if to == "RETURN_REQUESTED":
        cascade.void_shipment_continuity(s["id"])
    return response.success_object(shipment_view(s))


@bp.route("/contracts/<cid>/continuity-records", methods=["POST"])
def create_continuity_record(cid):
    middleware.require_roles("ProductionRep")
    body = middleware.get_json_body()
    shipment_id = body.get("shipment_id")
    if not isinstance(shipment_id, str):
        raise errors.invalid_request("Field 'shipment_id' is required and must be a string")
    timecode = util.req_int(body, "scene_timecode_seconds", minimum=0)
    note = util.req_str(body, "note")
    c = _contract_or_404(cid)
    shipment = db.shipments.get(shipment_id)
    if shipment is None:
        raise errors.not_found("Shipment not found")
    if shipment["contract_id"] != c["id"]:
        raise errors.ApiError(errors.ERR_SHIPMENT_CONTRACT_MISMATCH, 422,
                              "Shipment belongs to a different contract")
    ent = {"id": db.new_id(), "created_at": util.now_iso(),
           "contract_id": cid, "shipment_id": shipment_id,
           "scene_timecode_seconds": timecode, "note": note, "status": "LOGGED"}
    db.continuity_records[ent["id"]] = ent
    return response.success_object(continuity_view(ent), 201)


@bp.route("/contracts/<cid>/continuity-records", methods=["GET"])
def list_contract_continuity(cid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "ProductionRep")
    _contract_or_404(cid)
    limit, offset = util.pagination_params()
    items = [x for x in db.continuity_records.values() if x["contract_id"] == cid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([continuity_view(x) for x in page], limit, offset, total)


@bp.route("/shipments/<sid>/continuity-records", methods=["GET"])
def list_shipment_continuity(sid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "ProductionRep")
    s = db.shipments.get(sid)
    if s is None:
        raise errors.not_found("Shipment not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.continuity_records.values() if x["shipment_id"] == sid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([continuity_view(x) for x in page], limit, offset, total)
