"""Courier and marketplace delivery network registry."""
from flask import Blueprint

import db
import errors
import middleware as M
import response
import validation
from errors import fail
from routes import common
from services import constants as K
from services import serializers

bp = Blueprint("networks", __name__)


@bp.post("/courier-networks")
@M.endpoint(M.PLATFORM_ADMIN)
def create_courier_network():
    payload = validation.body()
    code = validation.req_str(payload, "code")
    name = validation.req_str(payload, "name")
    network_type = validation.req_enum(payload, "network_type", K.NETWORK_TYPES)
    priority_rank = validation.req_int(payload, "priority_rank", 1, 99)
    fee = validation.req_int(payload, "per_delivery_fee_cents", 0)
    sla = validation.req_int(payload, "handoff_sla_seconds", 60, 7200)
    buffer_seconds = validation.req_int(payload, "dispatch_buffer_seconds", 0, 3600)
    max_concurrent = validation.req_int(payload, "max_concurrent_assignments", 1, 20)
    is_active = validation.opt_bool(payload, "is_active", True)

    if any(n["code"] == code for n in db.courier_networks.values()):
        fail(errors.ERR_DUPLICATE_NETWORK_CODE)

    network = db.record()
    network.update({
        "code": code,
        "name": name,
        "network_type": network_type,
        "priority_rank": priority_rank,
        "per_delivery_fee_cents": fee,
        "handoff_sla_seconds": sla,
        "dispatch_buffer_seconds": buffer_seconds,
        "max_concurrent_assignments": max_concurrent,
        "is_active": is_active,
        "open_assignment_count": 0,
        "penalty_accrued_cents": 0,
    })
    db.courier_networks[network["id"]] = network
    return response.object_response(serializers.courier_network(network), 201)


@bp.get("/courier-networks/<network_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.COURIER_AGENT)
def read_courier_network(network_id):
    network = common.get_courier_network(network_id)
    M.require_network_scope(network_id)
    return response.object_response(serializers.courier_network(network))
