"""Baggage items: check, stage, load, mistag loop, deliver (PRD 3.6)."""

from flask import Blueprint, request

import db
import services
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_MANIFEST_DIRECTION,
    ERR_DUPLICATE_TAG, ERR_CUSTOMS_NOT_CLEARED, ERR_VESSEL_SCOPE,
)
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, check_shape, pagination_params, paginate, apply_filters

bp = Blueprint("baggage", __name__, url_prefix="/port-ops")


def _get_bag_or_404(bag_id):
    bag = db.get("baggage_items", bag_id)
    if bag is None:
        raise ApiError(ERR_NOT_FOUND, 404, "baggage item not found")
    return bag


@bp.route("/baggage-items", methods=["POST"])
def create_bag():
    authenticate({"TerminalOperator"})
    body = body_json()
    # Priority 3: body FK existence.
    entry = None
    if body.get("manifest_entry_id") is not None:
        entry = db.get("manifest_entries", body["manifest_entry_id"])
        if entry is None:
            raise ApiError(ERR_NOT_FOUND, 404, "manifest entry not found")
    check_shape(body, {
        "manifest_entry_id": {"type": "string", "required": True},
        "tag_code": {"type": "string", "required": True},
    })
    # Priority 8: the owning entry must be non-terminal for bag acceptance.
    if entry["status"] in ("NO_SHOW", "CANCELLED", "CARRIED_AWAY"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the owning manifest entry is terminal")
    # Priority 16: tag_code unique per port call.
    for other in services.bags_of_call(entry["port_call_id"]):
        if other["tag_code"] == body["tag_code"]:
            raise ApiError(ERR_DUPLICATE_TAG, 409,
                           "tag_code already exists on this port call")
    bag = db.new_entity("baggage_items", {
        "manifest_entry_id": entry["id"],
        "port_call_id": entry["port_call_id"],
        "tag_code": body["tag_code"],
        "status": "CHECKED",
    })
    return success_obj(db.public(bag), code=201)


@bp.route("/baggage-items", methods=["GET"])
def list_bags():
    user_id, role = authenticate(ANY)
    limit, offset = pagination_params()
    items = db.all_of("baggage_items")
    if role == "VesselAgent":
        for param in ("port_call_id", "manifest_entry_id"):
            ref = request.args.get(param)
            if ref is None:
                continue
            if param == "port_call_id":
                call = db.get("port_calls", ref)
            else:
                entry = db.get("manifest_entries", ref)
                call = db.get("port_calls", entry["port_call_id"]) if entry else None
            if call is not None and call["vessel_id"] != user_id:
                raise ApiError(ERR_VESSEL_SCOPE, 403,
                               "vessel agent may only read its own vessel's calls")
        items = [
            b for b in items
            if (db.get("port_calls", b["port_call_id"]) or {}).get("vessel_id") == user_id
        ]
    items = apply_filters(items, ["manifest_entry_id", "port_call_id", "status", "tag_code"])
    page, total, has_more = paginate([db.public(b) for b in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/baggage-items/<bag_id>", methods=["GET"])
def get_bag(bag_id):
    user_id, role = authenticate(ANY)
    bag = _get_bag_or_404(bag_id)
    if role == "VesselAgent":
        call = db.get("port_calls", bag["port_call_id"])
        if call is None or call["vessel_id"] != user_id:
            raise ApiError(ERR_VESSEL_SCOPE, 403,
                           "vessel agent may only read its own vessel's calls")
    return success_obj(db.public(bag))


@bp.route("/baggage-items/<bag_id>/stage", methods=["POST"])
def stage(bag_id):
    authenticate({"TerminalOperator"})
    bag = _get_bag_or_404(bag_id)
    entry = db.get("manifest_entries", bag["manifest_entry_id"])
    if bag["status"] == "CHECKED":
        if entry["status"] not in ("CHECKED_IN", "SCREENED", "EMBARKED", "DISEMBARKED", "CLEARED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "the owning entry's state does not allow staging")
    elif bag["status"] == "RECOVERED":
        pass  # Recovery loop re-enters the normal flow with no preconditions.
    else:
        raise ApiError(ERR_INVALID_STATE, 409, "stage requires status CHECKED or RECOVERED")
    bag["status"] = "STAGED"
    db.touch(bag)
    return success_obj(db.public(bag))


@bp.route("/baggage-items/<bag_id>/load", methods=["POST"])
def load(bag_id):
    authenticate({"TerminalOperator"})
    bag = _get_bag_or_404(bag_id)
    entry = db.get("manifest_entries", bag["manifest_entry_id"])
    # Priority 7: direction applicability.
    if entry["direction"] != "EMBARK":
        raise ApiError(ERR_MANIFEST_DIRECTION, 422, "load requires an EMBARK entry")
    if bag["status"] != "STAGED":
        raise ApiError(ERR_INVALID_STATE, 409, "load requires status STAGED")
    if entry["status"] != "EMBARKED":
        raise ApiError(ERR_INVALID_STATE, 409, "load requires the owning entry EMBARKED")
    call = db.get("port_calls", bag["port_call_id"])
    if call["status"] != "TURNAROUND":
        raise ApiError(ERR_INVALID_STATE, 409, "load requires the call to be TURNAROUND")
    bag["status"] = "LOADED"
    db.touch(bag)
    return success_obj(db.public(bag))


@bp.route("/baggage-items/<bag_id>/report-mistag", methods=["POST"])
def report_mistag(bag_id):
    authenticate({"TerminalOperator"})
    bag = _get_bag_or_404(bag_id)
    body = body_json()
    check_shape(body, {"note": {"type": "string", "required": False}})
    if bag["status"] not in ("CHECKED", "STAGED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "report-mistag requires status CHECKED or STAGED")
    bag["status"] = "MISTAGGED"
    db.touch(bag)
    return success_obj(db.public(bag))


@bp.route("/baggage-items/<bag_id>/recover", methods=["POST"])
def recover(bag_id):
    authenticate({"TerminalOperator"})
    bag = _get_bag_or_404(bag_id)
    if bag["status"] != "MISTAGGED":
        raise ApiError(ERR_INVALID_STATE, 409, "recover requires status MISTAGGED")
    bag["status"] = "RECOVERED"
    db.touch(bag)
    return success_obj(db.public(bag))


@bp.route("/baggage-items/<bag_id>/deliver", methods=["POST"])
def deliver(bag_id):
    authenticate({"TerminalOperator"})
    bag = _get_bag_or_404(bag_id)
    entry = db.get("manifest_entries", bag["manifest_entry_id"])
    # Priority 7: direction applicability.
    if entry["direction"] != "DEBARK":
        raise ApiError(ERR_MANIFEST_DIRECTION, 422, "deliver requires a DEBARK entry")
    if bag["status"] != "STAGED":
        raise ApiError(ERR_INVALID_STATE, 409, "deliver requires status STAGED")
    # Priority 21: customs coordination.
    if entry["status"] != "CLEARED":
        raise ApiError(ERR_CUSTOMS_NOT_CLEARED, 409,
                       "deliver requires the owning entry CLEARED by customs")
    bag["status"] = "DELIVERED"
    db.touch(bag)
    return success_obj(db.public(bag))
