from flask import Blueprint, request

import store
import response
import serialize
from errors import ApiError
from helpers import endpoint, get_body, field, lookup, touch, paginate

bp = Blueprint("restock", __name__)


@bp.get("/v1/restock-tasks/<task_id>")
@endpoint(["StoreClerk", "InventoryManager"])
def get_task(task_id):
    return response.ok(serialize.restock_out(lookup("restock_tasks", task_id)))


@bp.get("/v1/restock-tasks")
@endpoint(["StoreClerk", "InventoryManager"])
def list_tasks():
    bin_id = request.args.get("bin_id")
    status = request.args.get("status")
    recs = list(store.DB["restock_tasks"].values())
    if bin_id is not None:
        recs = [t for t in recs if t["bin_id"] == bin_id]
    if status is not None:
        recs = [t for t in recs if t["status"] == status]
    page, limit, offset, total = paginate(recs)
    return response.listing([serialize.restock_out(t) for t in page], limit, offset, total)


@bp.post("/v1/restock-tasks/<task_id>/complete")
@endpoint(["InventoryManager"])
def complete_task(task_id):
    task = lookup("restock_tasks", task_id)
    body = get_body()
    restocked_g = field(body, "restocked_g", required=True, kind="int")
    if task["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "restock task must be OPEN")
    if restocked_g < 0:
        raise ApiError("ERR_VALIDATION", "restocked_g must be >= 0")

    if restocked_g == 0:
        # A complete with restocked_g == 0 cancels the task (no grams added).
        task["status"] = "CANCELLED"
        touch(task)
        return response.ok(serialize.restock_out(task))

    b = store.DB["bins"][task["bin_id"]]
    if b["on_hand_g"] + restocked_g > b["capacity_g"]:
        raise ApiError("ERR_INSUFFICIENT_STOCK", "restock would overfill the bin")
    b["on_hand_g"] += restocked_g
    if b["status"] == "LOW" and b["on_hand_g"] > b["reorder_threshold_g"]:
        b["status"] = "OPEN"
    touch(b)

    task["restocked_g"] = restocked_g
    task["status"] = "COMPLETED"
    task["_completed_at"] = store.now()
    touch(task)
    return response.ok(serialize.restock_out(task))
