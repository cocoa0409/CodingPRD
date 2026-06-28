"""Bin endpoints (PRD §3.2)."""
from flask import Blueprint

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import get_bin, get_json_body, parse_pagination, paginate
from serializers import serialize_bin

bp = Blueprint("bins", __name__)

READ_ROLES = {"ReceivingClerk", "WavePlanner", "ClientUser", "BillingClerk"}


@bp.route("/bins", methods=["POST"])
def create_bin():
    _, role = get_auth()
    require_roles(role, {"ReceivingClerk"})
    body = get_json_body()

    location_code = body.get("location_code")
    if not isinstance(location_code, str) or location_code == "":
        raise err("ERR_INVALID_REQUEST", "location_code is required")

    bin_type = body.get("bin_type")
    if bin_type not in {"GENERAL", "PALLET"}:
        raise err("ERR_INVALID_REQUEST", "bin_type must be GENERAL or PALLET")

    capacity = body.get("capacity_cc")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
        raise err("ERR_INVALID_REQUEST", "capacity_cc must be a non-negative integer")

    # location_code globally unique (PRD §3.2).
    for b in store.bins.values():
        if b["location_code"] == location_code:
            raise err("ERR_INVALID_REQUEST", "location_code already exists")

    rec = stamp_create({
        "id": new_id(),
        "location_code": location_code,
        "bin_type": bin_type,
        "capacity_cc": capacity,
        "status": "OPEN",
    })
    store.bins[rec["id"]] = rec
    return success(serialize_bin(rec), status=201)


@bp.route("/bins", methods=["GET"])
def list_bins():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    page, meta = paginate(list(store.bins.values()), limit, offset)
    return success([serialize_bin(r) for r in page], pagination=meta)


@bp.route("/bins/<bin_id>", methods=["GET"])
def get_one_bin(bin_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_bin(bin_id)
    return success(serialize_bin(rec))


@bp.route("/bins/<bin_id>/block", methods=["POST"])
def block_bin(bin_id):
    _, role = get_auth()
    require_roles(role, {"ReceivingClerk"})
    rec = get_bin(bin_id)
    rec["status"] = "BLOCKED"
    touch(rec)
    return success(serialize_bin(rec))
