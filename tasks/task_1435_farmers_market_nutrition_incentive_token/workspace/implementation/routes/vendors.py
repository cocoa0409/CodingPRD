"""Vendor endpoints: register, read, list, approve, set-status."""

from flask import Blueprint, request

from db import STORE, stamp_new, touch
from errors import ApiError, ERR_INVALID_STATE
from middleware import ensure_valid_json, paginate, req_enum, req_str
from response import success_list, success_object
from routes.common import Pipeline, get_path_entity, ref_exists
from services.domain import serialize_vendor

bp = Blueprint("vendors", __name__)


@bp.route("/vendors", methods=["POST"])
def create_vendor():
    pipe = Pipeline(["ProgramAdmin"], is_write=True)
    body = pipe.body
    ref_exists("markets", body.get("market_id"))
    ensure_valid_json(body)
    market_id = req_str(body, "market_id")
    legal_name = req_str(body, "legal_name")
    stall_number = req_str(body, "stall_number")
    vendor = stamp_new({
        "market_id": market_id,
        "legal_name": legal_name,
        "stall_number": stall_number,
        "status": "PENDING",
    })
    STORE["vendors"][vendor["id"]] = vendor
    env, status = success_object(serialize_vendor(vendor), 201)
    pipe.commit(status, env.get_json())
    return env, status


@bp.route("/vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    Pipeline(["ProgramAdmin", "MarketManager", "Auditor", "Vendor"], is_write=False)
    vendor = get_path_entity("vendors", vid)
    return success_object(serialize_vendor(vendor))


@bp.route("/vendors", methods=["GET"])
def list_vendors():
    Pipeline(["ProgramAdmin", "MarketManager", "Auditor"], is_write=False)
    market_id = request.args.get("market_id")
    status_filter = request.args.get("status")
    items = list(STORE["vendors"].values())
    if market_id is not None:
        items = [v for v in items if v["market_id"] == market_id]
    if status_filter is not None:
        items = [v for v in items if v["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_vendor(v) for v in page], limit, offset, total)


@bp.route("/vendors/<vid>/approve", methods=["POST"])
def approve_vendor(vid):
    pipe = Pipeline(["ProgramAdmin"], is_write=True)
    vendor = get_path_entity("vendors", vid)
    if vendor["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Vendor in status {vendor['status']} cannot be approved")
    vendor["status"] = "ACTIVE"
    touch(vendor)
    env, status = success_object(serialize_vendor(vendor), 200)
    pipe.commit(status, env.get_json())
    return env, status


@bp.route("/vendors/<vid>/set-status", methods=["POST"])
def set_vendor_status(vid):
    pipe = Pipeline(["ProgramAdmin"], is_write=True)
    vendor = get_path_entity("vendors", vid)
    ensure_valid_json(pipe.body)
    to = req_enum(pipe.body, "to", {"ACTIVE", "SUSPENDED"})
    valid = (vendor["status"] == "ACTIVE" and to == "SUSPENDED") or (
        vendor["status"] == "SUSPENDED" and to == "ACTIVE"
    )
    if not valid:
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Vendor transition {vendor['status']} -> {to} is not permitted")
    vendor["status"] = to
    touch(vendor)
    env, status = success_object(serialize_vendor(vendor), 200)
    pipe.commit(status, env.get_json())
    return env, status
