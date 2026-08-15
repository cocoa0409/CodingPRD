"""Salt spray lot endpoints."""
from flask import Blueprint

from db import store
from errors import (
    ERR_INVALID_REQUEST,
    ERR_LOT_HOURS_INSUFFICIENT,
    ERR_LOT_NOT_RUNNING,
    ERR_NOT_FOUND,
    ERR_WORK_ORDER_NOT_AWAITING_LOT_TEST,
    raise_err,
)
from helpers import (
    body_json,
    check_integer,
    get_or_404,
    is_int,
    stamp_new,
    touch,
)
from middleware import require_roles
from response import success_object
from serializers import salt_spray_lot_view, lot_hours_run

bp = Blueprint("salt_spray", __name__)

MAX_REWORKS = 2


@bp.route("/salt-spray-lots", methods=["POST"])
def create_lot():
    user_id, role = require_roles({"LabChemist", "ShopManager"})
    data = body_json()
    work_order_id = data.get("work_order_id")
    if work_order_id is None or not isinstance(work_order_id, str):
        raise_err(ERR_INVALID_REQUEST, "work_order_id is required")
    # Tier 4: FK existence
    wo = store.work_orders.get(work_order_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "work order not found")
    sample_count = check_integer(data, "sample_count", required=True, gte=1)
    hours_required = check_integer(data, "hours_required", required=True, gte=1)

    # Tier 7: work order must be AWAITING_LOT_TEST
    if wo["status"] != "AWAITING_LOT_TEST":
        raise_err(ERR_WORK_ORDER_NOT_AWAITING_LOT_TEST, "salt-spray lot requires status AWAITING_LOT_TEST")

    if sample_count >= 10:
        allowed_failures = 2
    elif sample_count >= 5:
        allowed_failures = 1
    else:
        allowed_failures = 0

    lot = stamp_new({
        "work_order_id": wo["id"],
        "sample_count": sample_count,
        "hours_required": hours_required,
        "allowed_failures": allowed_failures,
        "panels_failed": None,
        "result": "PENDING",
    })
    store.salt_spray_lots[lot["id"]] = lot
    return success_object(salt_spray_lot_view(lot), status=201)


@bp.route("/salt-spray-lots/<lot_id>/evaluate", methods=["POST"])
def evaluate_lot(lot_id):
    user_id, role = require_roles({"LabChemist", "ShopManager"})
    lot = get_or_404(store.salt_spray_lots, lot_id)
    data = body_json()
    panels_failed = data.get("panels_failed")
    if panels_failed is None or not is_int(panels_failed) or panels_failed < 0:
        raise_err(ERR_INVALID_REQUEST, "panels_failed must be a non-negative integer")

    # Tier 7: lot must be PENDING
    if lot["result"] != "PENDING":
        raise_err(ERR_LOT_NOT_RUNNING, "evaluate requires lot result PENDING")

    # Tier 9: hours gate
    if lot_hours_run(lot) < lot["hours_required"]:
        raise_err(ERR_LOT_HOURS_INSUFFICIENT, "hours_run is less than hours_required")

    lot["panels_failed"] = panels_failed
    passed = panels_failed <= lot["allowed_failures"]
    lot["result"] = "PASSED" if passed else "FAILED"
    touch(lot)

    wo = store.work_orders.get(lot["work_order_id"])
    if wo is not None and wo["status"] == "AWAITING_LOT_TEST":
        if passed:
            wo["status"] = "COMPLETE"
        else:
            if wo["rework_count"] >= MAX_REWORKS:
                wo["status"] = "SCRAPPED"
            else:
                wo["status"] = "REJECTED"
                wo["pending_strip"] = True
                wo["last_defect_type"] = "LOT_CORROSION"
        touch(wo)

    return success_object(salt_spray_lot_view(lot))
