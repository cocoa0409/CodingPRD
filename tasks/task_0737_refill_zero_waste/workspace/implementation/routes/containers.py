from flask import Blueprint, request

import store
import response
import serialize
import services
from errors import ApiError
from helpers import (endpoint, get_body, field, lookup, require_fk, stamp_new,
                     touch, paginate, owner_check)

bp = Blueprint("containers", __name__)

DEPOSIT_BY_TYPE = {"GLASS_500": 150, "GLASS_1000": 250, "BYO": 0}


@bp.post("/v1/containers")
@endpoint(["Member", "StoreClerk"])
def create_container():
    body = get_body()
    ctype = field(body, "container_type", required=True, kind="str",
                  enum={"GLASS_500", "GLASS_1000", "BYO"})
    declared_tare_g = field(body, "declared_tare_g", required=True, kind="int")
    member_id = field(body, "member_id", kind="str", default=None)
    if member_id is not None:
        require_fk("members", member_id)
        owner_check(member_id)
    rec = {
        "member_id": member_id,
        "container_type": ctype,
        "declared_tare_g": declared_tare_g,
        "measured_tare_g": None,
        "deposit_cents": DEPOSIT_BY_TYPE[ctype],
        "allergen_hold": "NONE",
        "status": "AVAILABLE",
    }
    stamp_new(rec)
    store.DB["containers"][rec["id"]] = rec
    return response.created(serialize.container_out(rec))


@bp.get("/v1/containers/<container_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_container(container_id):
    return response.ok(serialize.container_out(lookup("containers", container_id)))


@bp.get("/v1/containers")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def list_containers():
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    recs = list(store.DB["containers"].values())
    if member_id is not None:
        recs = [c for c in recs if c["member_id"] == member_id]
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    page, limit, offset, total = paginate(recs)
    return response.listing([serialize.container_out(c) for c in page], limit, offset, total)


@bp.post("/v1/containers/<container_id>/issue")
@endpoint(["StoreClerk"])
def issue_container(container_id):
    c = lookup("containers", container_id)
    body = get_body()
    member_id = field(body, "member_id", required=True, kind="str")
    require_fk("members", member_id)
    if c["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_CONTAINER_STATE", "container must be AVAILABLE to issue")
    c["member_id"] = member_id
    c["status"] = "ISSUED"
    touch(c)
    return response.ok(serialize.container_out(c))


@bp.post("/v1/containers/<container_id>/return")
@endpoint(["Member", "StoreClerk"])
def return_container(container_id):
    c = lookup("containers", container_id)
    owner_check(c["member_id"])
    if c["status"] != "IN_USE":
        raise ApiError("ERR_INVALID_CONTAINER_STATE", "container must be IN_USE to return")
    c["status"] = "RETURNED"
    touch(c)
    services.append_ledger(
        c["member_id"], "DEPOSIT_REFUND",
        wallet_delta=c["deposit_cents"], liability_delta=-c["deposit_cents"],
        source_kind="CONTAINER", source_id=c["id"], memo="in-store container return",
    )
    return response.ok(serialize.container_out(c))


@bp.post("/v1/containers/<container_id>/inspect")
@endpoint(["StoreClerk", "InventoryManager"])
def inspect_container(container_id):
    c = lookup("containers", container_id)
    body = get_body()
    result = field(body, "result", required=True, kind="str",
                   enum={"CLEAN", "RESIDUE", "RETIRE"})
    status = c["status"]
    if status not in ("RETURNED", "QUARANTINED"):
        raise ApiError("ERR_INVALID_CONTAINER_STATE",
                       "container must be RETURNED or QUARANTINED to inspect")
    if status == "RETURNED":
        if result == "CLEAN":
            c["allergen_hold"] = "NONE"
            c["measured_tare_g"] = None
            c["member_id"] = None
            c["status"] = "AVAILABLE"
        elif result == "RESIDUE":
            c["status"] = "QUARANTINED"
        else:  # RETIRE not defined from RETURNED
            raise ApiError("ERR_INVALID_CONTAINER_STATE",
                           "RETIRE is not a valid result for a RETURNED container")
    else:  # QUARANTINED
        if result == "CLEAN":
            c["allergen_hold"] = "NONE"
            c["status"] = "AVAILABLE"
        elif result == "RETIRE":
            c["status"] = "RETIRED"
        else:  # RESIDUE not defined from QUARANTINED
            raise ApiError("ERR_INVALID_CONTAINER_STATE",
                           "RESIDUE is not a valid result for a QUARANTINED container")
    touch(c)
    return response.ok(serialize.container_out(c))
