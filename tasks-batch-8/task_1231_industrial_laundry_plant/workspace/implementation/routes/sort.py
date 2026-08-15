"""SortBatch and SortItem endpoints."""

from flask import Blueprint

import db
import services
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_EMPTY_SORT_BATCH,
    ERR_BATCH_HAS_WASH_LOADS,
    ERR_STOP_NOT_PICKED_UP,
)
from response import success, list_response
from util import (
    FLOOR_READ,
    authenticate,
    require_roles,
    body_json,
    field,
    path_get,
    ref_get,
    filter_eq,
    round2,
    D,
)

bp = Blueprint("sort", __name__)

OPERATOR = {"PlantOperator"}
DISPOSITIONS = ("ACCEPTED", "REJECTED")
REJECT_REASONS = ("STAIN", "TEAR", "CONTAMINATION")


def _recompute_counters(batch):
    items = [i for i in db.sort_items.values() if i["batch_id"] == batch["id"]]
    batch["total_sorted_pieces"] = sum(i["pieces"] for i in items)
    batch["accepted_pieces"] = sum(i["pieces"] for i in items if i["disposition"] == "ACCEPTED")
    batch["rejected_pieces"] = sum(i["pieces"] for i in items if i["disposition"] == "REJECTED")


def _batch_has_wash_loads(batch):
    return any(w["batch_id"] == batch["id"] for w in db.wash_loads.values())


@bp.route("/sort-batches", methods=["POST"])
def create_sort_batch():
    data = body_json()
    stop_id = field(data, "stop_id", "s")
    auth = authenticate()
    require_roles(auth, OPERATOR)
    stop = ref_get(db.stops, stop_id)
    route = db.routes.get(stop["route_id"])
    batch = db.new_entity()
    batch.update(
        {
            "plant_id": route["plant_id"] if route else None,
            "stop_id": stop["id"],
            "total_sorted_pieces": 0,
            "accepted_pieces": 0,
            "rejected_pieces": 0,
            "reject_rate_pct": 0,
            "alert_raised": False,
            "status": "OPEN",
        }
    )
    db.sort_batches[batch["id"]] = batch
    return success(batch, 201)


@bp.route("/sort-batches/<bid>", methods=["GET"])
def get_sort_batch(bid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    return success(path_get(db.sort_batches, bid))


@bp.route("/plants/<pid>/sort-batches", methods=["GET"])
def list_plant_sort_batches(pid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    plant = path_get(db.plants, pid)
    items = [b for b in db.sorted_all(db.sort_batches) if b["plant_id"] == plant["id"]]
    items = filter_eq(items, "status", "status")
    return list_response(items)


@bp.route("/stops/<sid>/sort-batches", methods=["GET"])
def list_stop_sort_batches(sid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    stop = path_get(db.stops, sid)
    items = [b for b in db.sorted_all(db.sort_batches) if b["stop_id"] == stop["id"]]
    return list_response(items)


@bp.route("/sort-batches/<bid>/items", methods=["GET"])
def list_sort_items(bid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    batch = path_get(db.sort_batches, bid)
    items = [i for i in db.sorted_all(db.sort_items) if i["batch_id"] == batch["id"]]
    return list_response(items)


@bp.route("/sort-batches/<bid>/items", methods=["POST"])
def create_sort_item(bid):
    data = body_json()
    category_id = field(data, "category_id", "s")
    pieces = field(data, "pieces", "i", minv=1)
    disposition = field(data, "disposition", "s", choices=DISPOSITIONS)
    if disposition == "REJECTED":
        reject_reason = field(data, "reject_reason", "s", choices=REJECT_REASONS)
    else:
        if data.get("reject_reason") is not None:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "reject_reason is forbidden when disposition is ACCEPTED"
            )
        reject_reason = None
    auth = authenticate()
    require_roles(auth, OPERATOR)
    batch = path_get(db.sort_batches, bid)
    cat = ref_get(db.categories, category_id)
    if batch["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Sort batch is not OPEN")
    item = db.new_entity()
    item.update(
        {
            "batch_id": batch["id"],
            "category_id": cat["id"],
            "pieces": pieces,
            "disposition": disposition,
            "reject_reason": reject_reason,
        }
    )
    db.sort_items[item["id"]] = item
    _recompute_counters(batch)
    db.touch(batch)
    return success(item, 201)


@bp.route("/sort-batches/<bid>/lock", methods=["POST"])
def lock_sort_batch(bid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    batch = path_get(db.sort_batches, bid)
    if batch["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Sort batch is not OPEN")
    if batch["total_sorted_pieces"] < 1:
        raise ApiError(ERR_EMPTY_SORT_BATCH, 422, "Lock requires at least one sorted piece")
    stop = services.stop_of_batch(batch)
    if not stop or stop["status"] not in ("PICKED_UP", "DELIVERED", "DISPUTED"):
        raise ApiError(ERR_STOP_NOT_PICKED_UP, 409, "Stop must be PICKED_UP or later")
    total = batch["total_sorted_pieces"]
    if total == 0:
        rate = D(0)
    else:
        rate = round2(D(batch["rejected_pieces"]) * D(100) / D(total))
    batch["reject_rate_pct"] = float(rate)
    plant = db.plants.get(batch["plant_id"])
    batch["alert_raised"] = bool(plant) and rate >= D(plant["reject_rate_alert_pct"])
    batch["status"] = "LOCKED"
    db.touch(batch)
    return success(batch)


@bp.route("/sort-batches/<bid>/unlock", methods=["POST"])
def unlock_sort_batch(bid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    batch = path_get(db.sort_batches, bid)
    if batch["status"] != "LOCKED":
        raise ApiError(ERR_INVALID_STATE, 409, "Sort batch is not LOCKED")
    if _batch_has_wash_loads(batch):
        raise ApiError(ERR_BATCH_HAS_WASH_LOADS, 409, "A wash load references this batch")
    batch["status"] = "OPEN"
    batch["alert_raised"] = False
    batch["reject_rate_pct"] = 0
    db.touch(batch)
    return success(batch)


@bp.route("/sort-batches/<bid>/post", methods=["POST"])
def post_sort_batch(bid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    batch = path_get(db.sort_batches, bid)
    if batch["status"] != "LOCKED":
        raise ApiError(ERR_INVALID_STATE, 409, "Sort batch is not LOCKED")
    stop = services.stop_of_batch(batch)
    # Cascade: every RECEIVED cart of the stop moves to SORTED.
    if stop:
        for cart in db.carts.values():
            if cart["stop_id"] == stop["id"] and cart["status"] == "RECEIVED":
                cart["status"] = "SORTED"
                db.touch(cart)
    # Decrement on-site par counters by accepted pieces per category.
    accepted_by_cat = {}
    for item in db.sort_items.values():
        if item["batch_id"] == batch["id"] and item["disposition"] == "ACCEPTED":
            accepted_by_cat[item["category_id"]] = accepted_by_cat.get(item["category_id"], 0) + item["pieces"]
    if stop:
        for cat_id, pieces in accepted_by_cat.items():
            par = next(
                (
                    p
                    for p in db.par_levels.values()
                    if p["customer_id"] == stop["customer_id"] and p["category_id"] == cat_id
                ),
                None,
            )
            if par is not None:
                par["current_on_site_pieces"] -= pieces
                db.touch(par)
    batch["status"] = "POSTED"
    db.touch(batch)
    return success(batch)


@bp.route("/sort-batches/<bid>/void", methods=["POST"])
def void_sort_batch(bid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    batch = path_get(db.sort_batches, bid)
    if batch["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Sort batch is not OPEN")
    if _batch_has_wash_loads(batch):
        raise ApiError(ERR_BATCH_HAS_WASH_LOADS, 409, "A wash load references this batch")
    doomed = [k for k, v in db.sort_items.items() if v["batch_id"] == batch["id"]]
    for k in doomed:
        del db.sort_items[k]
    batch["total_sorted_pieces"] = 0
    batch["accepted_pieces"] = 0
    batch["rejected_pieces"] = 0
    batch["reject_rate_pct"] = 0
    batch["alert_raised"] = False
    batch["status"] = "VOIDED"
    db.touch(batch)
    return success(batch)


@bp.route("/sort-items", methods=["GET"])
def list_sort_items_global():
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    items = db.sorted_all(db.sort_items)
    items = filter_eq(items, "batch_id", "batch_id")
    items = filter_eq(items, "category_id", "category_id")
    return list_response(items)
