"""VCP verification routes."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles
from response import success_object, success_list
from services import core
from routes.onboarding import _paginate

bp = Blueprint("vcp", __name__)


@bp.post("/vfd/vcp-verifications")
def create_vcp():
    user_id, _ = require_roles("Veterinarian")
    body = util.get_json_body()
    vet_id = util.require_field(body, "vet_id")
    producer_id = util.require_field(body, "producer_id")
    expires_on = util.require_field(body, "expires_on")
    util.parse_iso(expires_on, "expires_on")
    vet = core.get_vet(vet_id)
    core.get_producer(producer_id)
    # entity-backed identity: X-User-ID must equal vet_id
    if user_id != vet_id:
        raise errors.forbidden("X-User-ID must equal vet_id")
    if vet["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_VET_INACTIVE,
                              "Veterinarian status is SUSPENDED or REVOKED", 409)
    vcp = util.new_entity({
        "vet_id": vet_id,
        "producer_id": producer_id,
        "verified_on": util.logical_now_iso(),
        "expires_on": expires_on,
        "status": "ACTIVE",
    })
    store.vcp_verifications[vcp["id"]] = vcp
    return success_object(vcp, 201)


@bp.get("/vfd/vcp-verifications/<vid>")
def get_vcp(vid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator")
    return success_object(core.get_vcp(vid))


@bp.get("/vfd/vcp-verifications")
def list_vcps():
    require_roles("Inspector", "Veterinarian", "FeedMillOperator")
    items = list(store.vcp_verifications.values())
    vet_id = request.args.get("vet_id")
    if vet_id is not None:
        items = [v for v in items if v.get("vet_id") == vet_id]
    producer_id = request.args.get("producer_id")
    if producer_id is not None:
        items = [v for v in items if v.get("producer_id") == producer_id]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v.get("status") == status]
    return _paginate(items)


@bp.post("/vfd/vcp-verifications/<vid>/revoke")
def revoke_vcp(vid):
    user_id, _ = require_roles("Veterinarian")
    vcp = core.get_vcp(vid)
    if user_id != vcp.get("vet_id"):
        raise errors.forbidden("X-User-ID must equal vcp.vet_id")
    if vcp["status"] != "ACTIVE":
        raise errors.invalid_state("VCPR must be ACTIVE to revoke")
    body = util.get_json_body()
    reason = body.get("revocation_reason")
    if reason is None:
        raise errors.invalid_request("revocation_reason is required")
    vcp["status"] = "REVOKED"
    vcp["revocation_reason"] = reason
    util.touch(vcp)
    core.expire_vfds_for_vcp(vcp["vet_id"], vcp["producer_id"])
    return success_object(vcp)
