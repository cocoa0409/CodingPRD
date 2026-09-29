"""Fee remittances and the strictly ordered reconciliation waterfall."""

from flask import Blueprint, request

from db import base_row, by_created_at, db, insert, touch
from errors import ApiError
from middleware import endpoint, require_owner
from response import object_response, paginate
from routes import lookup
from services import aggregates, constants as C
from validation import body, req_id, req_id_list, req_int

bp = Blueprint("fee_remittances", __name__)

READ_ROLES = ("LivestockOwner", "FeeAdministrator", "BoardAdmin")


@bp.post("/fee-remittances")
@endpoint("LivestockOwner")
def tender_remittance():
    payload = body()
    owner_id = req_id(payload, "owner_id")
    amount_cents = req_int(payload, "amount_cents", exclusive_minimum=0)
    covered_order_ids = req_id_list(payload, "covered_order_ids")

    lookup.owner(owner_id)
    covered = [lookup.order(order_id) for order_id in covered_order_ids]

    require_owner(owner_id)

    for order in covered:
        if order["hold_flag"]:
            raise ApiError("ERR_ORDER_HOLD_ACTIVE", "A covered order is under a theft hold.")

    row = base_row()
    row.update(
        {
            "owner_id": owner_id,
            "amount_cents": amount_cents,
            "covered_order_ids": list(covered_order_ids),
            "status": "SUBMITTED",
            "applied_cents": 0,
            "shortfall_cents": 0,
        }
    )
    insert(db.remittances, row)
    return object_response(row, 201)


@bp.get("/fee-remittances/<remittance_id>")
@endpoint(*READ_ROLES)
def read_remittance(remittance_id):
    return object_response(lookup.remittance(remittance_id))


@bp.get("/fee-remittances")
@endpoint(*READ_ROLES)
def list_remittances():
    rows = lookup.filtered(
        db.remittances,
        {
            "owner_id": request.args.get("owner_id"),
            "status": request.args.get("status"),
        },
    )
    return paginate(by_created_at(rows))


@bp.post("/fee-remittances/<remittance_id>/reconcile")
@endpoint("FeeAdministrator")
def reconcile_remittance(remittance_id):
    remittance = lookup.remittance(remittance_id)
    if remittance["status"] != "SUBMITTED":
        raise ApiError("ERR_REMITTANCE_INVALID_STATE", "The remittance is not awaiting reconciliation.")

    open_orders = [
        db.orders[order_id]
        for order_id in remittance["covered_order_ids"]
        if order_id in db.orders and db.orders[order_id]["fee_status"] in C.OPEN_FEE_STATUSES
    ]
    open_orders.sort(key=lambda order: (order["fee_due_on"], order["created_at"], order["_seq"]))
    covered_total_cents = sum(order["assessed_fee_cents"] for order in open_orders)

    if remittance["amount_cents"] > remittance["applied_cents"] + covered_total_cents:
        raise ApiError("ERR_REMITTANCE_AMOUNT_INVALID", "The tender exceeds the still-open covered total.")

    available_cents = remittance["amount_cents"] - remittance["applied_cents"]
    touched_owner_ids = []
    for order in open_orders:
        if available_cents >= order["assessed_fee_cents"]:
            order["fee_status"] = "REMITTED"
            order["remittance_id"] = remittance["id"]
            touch(order)
            available_cents -= order["assessed_fee_cents"]
            remittance["applied_cents"] += order["assessed_fee_cents"]
            if order["owner_id"] not in touched_owner_ids:
                touched_owner_ids.append(order["owner_id"])
        else:
            # The first order that cannot be fully covered stops the walk outright.
            break

    remaining_open_cents = sum(
        order["assessed_fee_cents"] for order in open_orders if order["fee_status"] in C.OPEN_FEE_STATUSES
    )
    remittance["shortfall_cents"] = max(remaining_open_cents - available_cents, 0)
    remittance["status"] = "RECONCILED" if remittance["shortfall_cents"] == 0 else "SHORT_PAID"
    touch(remittance)

    if remittance["owner_id"] not in touched_owner_ids:
        touched_owner_ids.append(remittance["owner_id"])
    for owner_id in touched_owner_ids:
        aggregates.recompute_owner_by_id(owner_id)

    return object_response(remittance)


@bp.post("/fee-remittances/<remittance_id>/top-up")
@endpoint("LivestockOwner")
def top_up_remittance(remittance_id):
    payload = body()
    additional_cents = req_int(payload, "additional_cents", exclusive_minimum=0)

    remittance = lookup.remittance(remittance_id)
    require_owner(remittance["owner_id"])

    if remittance["status"] != "SHORT_PAID":
        raise ApiError("ERR_REMITTANCE_INVALID_STATE", "Only a short-paid remittance may be topped up.")

    remittance["amount_cents"] += additional_cents
    remittance["status"] = "SUBMITTED"
    touch(remittance)
    return object_response(remittance)
