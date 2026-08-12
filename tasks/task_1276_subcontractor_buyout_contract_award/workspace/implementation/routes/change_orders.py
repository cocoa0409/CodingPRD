"""ChangeOrder endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import CO_READ_ROLES, auth
from response import ok, ok_list
from services import (
    authority_check,
    ensure_sub_not_terminal,
    get_change_order,
    get_subcontract,
    ser_change_order,
    sorted_created,
    stamp,
    touch,
)
from util import as_int, as_str, body, pagination_args, required

bp = Blueprint("change_orders", __name__)

APPROVER_ROLES = ["ProjectManager", "ProjectExecutive", "OperationsManager"]


@bp.post("/subcontracts/<sub_id>/change-orders")
def create_change_order(sub_id):
    user_id, role = auth(["BuyoutLead", "ProjectManager", "SupplierDiversity"])
    sub = get_subcontract(sub_id)
    data = body()
    description = as_str(required(data, "description"), "description")
    amount_cents = as_int(required(data, "amount_cents"), "amount_cents")
    initiating_role = data.get("initiating_role")
    if initiating_role is not None:
        as_str(initiating_role, "initiating_role")
    ensure_sub_not_terminal(sub)
    if sub["status"] != "EXECUTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not EXECUTED"
        )
    if sub["sov_status"] != "APPROVED":
        raise ApiError(
            "ERR_SOV_NOT_APPROVED",
            409,
            "Change-order creation requires an APPROVED schedule of values",
        )
    rec = {
        "id": new_id(),
        "subcontract_id": sub["id"],
        "description": description,
        "amount_cents": amount_cents,
        "initiating_role": initiating_role,
        "approval_roles_received": [],
        "created_by_user_id": user_id,
        "status": "DRAFT",
    }
    stamp(rec)
    DB["change_orders"][rec["id"]] = rec
    return ok(ser_change_order(rec), status=201)


@bp.get("/subcontracts/<sub_id>/change-orders")
def list_change_orders(sub_id):
    auth(CO_READ_ROLES)
    sub = get_subcontract(sub_id)
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = sorted_created(
        [c for c in DB["change_orders"].values() if c["subcontract_id"] == sub["id"]]
    )
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_change_order(c) for c in page], total, limit, offset)


@bp.get("/change-orders/<co_id>")
def get_one_change_order(co_id):
    auth(CO_READ_ROLES)
    return ok(ser_change_order(get_change_order(co_id)))


@bp.post("/change-orders/<co_id>/submit")
def submit_change_order(co_id):
    auth(["BuyoutLead"])
    co = get_change_order(co_id)
    if co["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ChangeOrder is not in DRAFT"
        )
    co["status"] = "PENDING_APPROVAL"
    touch(co)
    return ok(ser_change_order(co))


@bp.post("/change-orders/<co_id>/approve")
def approve_change_order(co_id):
    user_id, role = auth(APPROVER_ROLES)
    co = get_change_order(co_id)
    if co["status"] != "PENDING_APPROVAL":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ChangeOrder is not in PENDING_APPROVAL"
        )
    if user_id == co["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            409,
            "Change-order approver must differ from its creator",
        )
    sub = get_subcontract(co["subcontract_id"])
    authority_check(sub, co, role)
    co["status"] = "APPROVED"
    co["approval_roles_received"].append(role)
    touch(co)
    sub["cumulative_co_cents"] += co["amount_cents"]
    sub["contract_value_cents"] += co["amount_cents"]
    touch(sub)
    return ok(ser_change_order(co))


@bp.post("/change-orders/<co_id>/reject")
def reject_change_order(co_id):
    auth(APPROVER_ROLES)
    co = get_change_order(co_id)
    if co["status"] != "PENDING_APPROVAL":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ChangeOrder is not in PENDING_APPROVAL"
        )
    co["status"] = "REJECTED"
    touch(co)
    return ok(ser_change_order(co))


@bp.post("/change-orders/<co_id>/void")
def void_change_order(co_id):
    auth(["OperationsManager"])
    co = get_change_order(co_id)
    if co["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ChangeOrder is not in APPROVED"
        )
    co["status"] = "VOIDED"
    touch(co)
    sub = get_subcontract(co["subcontract_id"])
    sub["cumulative_co_cents"] -= co["amount_cents"]
    sub["contract_value_cents"] -= co["amount_cents"]
    touch(sub)
    return ok(ser_change_order(co))
