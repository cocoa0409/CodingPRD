"""PartCrossReference endpoints."""

from flask import Blueprint, request

import errors
from db import store, new_id, now_iso
from middleware import (
    authenticate, require_roles, json_body, need, as_str, as_int, as_bool,
    pagination_params, paginate,
)
from response import success, success_list

bp = Blueprint("xrefs", __name__)

READ_ROLES = ["DistributorAdmin", "RouteDriver", "WarehouseOperator"]


def serialize(x):
    # cross-references deliberately carry id and created_at only (PRD 2.5)
    return {
        "id": x["id"],
        "from_part_id": x["from_part_id"],
        "to_part_id": x["to_part_id"],
        "priority_rank": x["priority_rank"],
        "is_active": x["is_active"],
        "created_at": x["created_at"],
    }


@bp.post("/vmi/part-cross-references")
def create_xref():
    role = authenticate()
    body = json_body()
    from_part_id = as_str(need(body, "from_part_id"), "from_part_id")
    to_part_id = as_str(need(body, "to_part_id"), "to_part_id")
    priority_rank = as_int(need(body, "priority_rank"), "priority_rank")
    if priority_rank < 1:
        raise errors.invalid_request("priority_rank must be >= 1")
    is_active = True
    if "is_active" in body:
        is_active = as_bool(body["is_active"], "is_active")
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        # existence, left-to-right: from_part before to_part
        if from_part_id not in store.parts:
            raise errors.not_found("from_part_id does not reference an existing part")
        if to_part_id not in store.parts:
            raise errors.not_found("to_part_id does not reference an existing part")
        if any(
            x["from_part_id"] == from_part_id and x["to_part_id"] == to_part_id
            for x in store.xrefs.values()
        ):
            raise errors.duplicate("(from_part_id, to_part_id) pair already declared")
        if from_part_id == to_part_id:
            raise errors.no_substitute("cross-reference must not be self-referential")
        xref = {
            "id": new_id(),
            "from_part_id": from_part_id,
            "to_part_id": to_part_id,
            "priority_rank": priority_rank,
            "is_active": is_active,
            "created_at": now_iso(),
            "_seq": store.next_seq(),
        }
        store.xrefs[xref["id"]] = xref
        return success(serialize(xref), 201)


@bp.get("/vmi/part-cross-references/<xid>")
def get_xref(xid):
    role = authenticate()
    require_roles(role, READ_ROLES)
    xref = store.xrefs.get(xid)
    if xref is None:
        raise errors.not_found("cross-reference not found")
    return success(serialize(xref), 200)


@bp.get("/vmi/part-cross-references")
def list_xrefs():
    role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = pagination_params()
    from_part_id = request.args.get("from_part_id")
    to_part_id = request.args.get("to_part_id")
    items = sorted(store.xrefs.values(), key=lambda x: x["_seq"])
    if from_part_id is not None:
        items = [x for x in items if x["from_part_id"] == from_part_id]
    if to_part_id is not None:
        items = [x for x in items if x["to_part_id"] == to_part_id]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(x) for x in page], total, limit, offset)
