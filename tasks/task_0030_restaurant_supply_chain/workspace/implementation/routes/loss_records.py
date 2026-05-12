"""Loss records: record / approve / reverse / resolve-investigation."""

from datetime import timedelta

from flask import Blueprint, g, request

import clock
import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("loss_records", __name__, url_prefix="/supply-chain/loss-records")


VALID_CAUSES = {"SPOILAGE", "DAMAGE", "THEFT", "PREPARATION"}
ABNORMAL_LOSS_THRESHOLD = 0.05
LOSS_WINDOW_HOURS = 168


def _ensure_owner(loss):
    if g.user_role == "StoreManager" and loss["store_id"] != g.user_id:
        errors.raise_error(errors.ERR_FORBIDDEN, "StoreManager may only act on their own losses.")


def _abnormal_check(store_id):
    """Return True if event-level loss rate at this store strictly exceeds threshold."""
    now = clock.now()
    window_start = now - timedelta(hours=LOSS_WINDOW_HOURS)

    losses = 0
    for lr in db.loss_records.values():
        if lr["store_id"] != store_id:
            continue
        if lr["created_at"] < window_start:
            continue
        if lr["status"] == "REVERSED":
            continue
        losses += lr["quantity_lost"]

    throughput = 0
    for o in db.store_orders.values():
        if o["store_id"] != store_id:
            continue
        if o["status"] != "DELIVERED":
            continue
        if o["updated_at"] < window_start:
            continue
        for ln in db.order_lines.values():
            if ln["store_order_id"] == o["id"]:
                throughput += ln["quantity"]

    rate = losses / max(throughput, 1)
    return rate > ABNORMAL_LOSS_THRESHOLD


@bp.route("", methods=["POST"])
@auth_required("StoreManager")
def record_loss():
    body = helpers.get_json_body()
    for f in ["inventory_batch_id", "quantity_lost", "cause"]:
        if f not in body:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Missing field: {f}")

    inv_id = body["inventory_batch_id"]
    qty_lost = body["quantity_lost"]
    cause = body["cause"]
    resp_id = body.get("responsibility_user_id")

    if cause not in VALID_CAUSES:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Invalid cause: {cause}")

    inv = db.inventory_batches.get(inv_id)
    if inv is None:
        errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, "InventoryBatch not found.")

    if g.user_role == "StoreManager" and inv["store_id"] != g.user_id:
        errors.raise_error(errors.ERR_FORBIDDEN,
                           "StoreManager may only record loss on their own store's inventory.")

    # Responsibility-attribution check.
    if cause == "SPOILAGE" and resp_id is not None:
        errors.raise_error(errors.ERR_RESPONSIBILITY_REQUIRED,
                           "responsibility_user_id must be null for SPOILAGE.")
    if cause in {"DAMAGE", "THEFT", "PREPARATION"} and not resp_id:
        errors.raise_error(errors.ERR_RESPONSIBILITY_REQUIRED,
                           "responsibility_user_id is required for DAMAGE/THEFT/PREPARATION.")

    if not isinstance(qty_lost, int) or qty_lost <= 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "quantity_lost must be a positive integer.")
    if qty_lost > inv["quantity_on_hand"]:
        errors.raise_error(errors.ERR_LOSS_EXCEEDS_ON_HAND,
                           "quantity_lost exceeds InventoryBatch.quantity_on_hand.")

    recipe = db.recipes[inv["recipe_id"]]
    financial_impact = qty_lost * recipe["unit_price_cents"]

    # Create the loss record.
    lid = db.new_id()
    common = helpers.common_create()
    loss = {
        "id": lid,
        "store_id": inv["store_id"],
        "inventory_batch_id": inv_id,
        "quantity_lost": qty_lost,
        "cause": cause,
        "responsibility_user_id": resp_id,
        "financial_impact_cents": financial_impact,
        "is_abnormal": False,
        "investigation_status": "NONE",
        "status": "RECORDED",
        **common,
    }
    db.loss_records[lid] = loss

    # Decrement inventory at recording time.
    inv["quantity_on_hand"] -= qty_lost
    helpers.bump(inv)

    # Abnormal-loss detection (after this record is in the window).
    if _abnormal_check(inv["store_id"]):
        loss["is_abnormal"] = True
        loss["investigation_status"] = "PENDING"

    audit.append(target_type="LossRecord", target_id=lid, action="RECORD_LOSS",
                 payload={"inventory_batch_id": inv_id,
                          "quantity_lost": qty_lost,
                          "cause": cause,
                          "responsibility_user_id": resp_id,
                          "financial_impact_cents": financial_impact,
                          "is_abnormal": loss["is_abnormal"]})
    audit.append(target_type="InventoryBatch", target_id=inv_id, action="ADJUST_STOCK",
                 payload={"delta": -qty_lost,
                          "reason": f"loss:{cause}",
                          "loss_record_id": lid,
                          "new_quantity_on_hand": inv["quantity_on_hand"]})
    return response.created(serializers.loss_record_dict(loss))


@bp.route("", methods=["GET"])
@auth_required("StoreManager", "FinanceController", "CentralKitchenPlanner")
def list_loss_records():
    limit, offset = helpers.parse_pagination()
    items = list(db.loss_records.values())
    store_id = request.args.get("store_id")
    cause = request.args.get("cause")
    is_abnormal = request.args.get("is_abnormal")
    inv_status = request.args.get("investigation_status")
    status_filter = request.args.get("status")

    if g.user_role == "StoreManager":
        items = [l for l in items if l["store_id"] == g.user_id]
    if store_id:
        items = [l for l in items if l["store_id"] == store_id]
    if cause:
        items = [l for l in items if l["cause"] == cause]
    if is_abnormal is not None:
        flag = is_abnormal.lower() == "true"
        items = [l for l in items if l["is_abnormal"] == flag]
    if inv_status:
        items = [l for l in items if l["investigation_status"] == inv_status]
    if status_filter:
        items = [l for l in items if l["status"] == status_filter]

    items.sort(key=lambda l: l["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.loss_record_dict(l) for l in page],
                            limit=limit, offset=offset, total_count=total)


@bp.route("/<lid>/approve", methods=["POST"])
@auth_required("FinanceController")
def approve(lid):
    loss = db.loss_records.get(lid)
    if loss is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"LossRecord {lid} not found.")
    body = helpers.get_json_body()
    if loss["status"] != "RECORDED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only RECORDED losses may be approved.")
    helpers.check_occ(loss, body.get("version"))

    if loss["is_abnormal"] and loss["investigation_status"] != "RESOLVED":
        errors.raise_error(errors.ERR_INVESTIGATION_PENDING,
                           "Abnormal loss requires investigation_status=RESOLVED.")

    loss["status"] = "APPROVED"
    helpers.bump(loss)
    audit.append(target_type="LossRecord", target_id=lid, action="APPROVE_LOSS",
                 payload={"approved_at": clock.iso_format(clock.now())},
                 external_systems=["FINANCE"])
    return response.ok(serializers.loss_record_dict(loss))


@bp.route("/<lid>/reverse", methods=["POST"])
@auth_required("FinanceController")
def reverse(lid):
    loss = db.loss_records.get(lid)
    if loss is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"LossRecord {lid} not found.")
    body = helpers.get_json_body()
    if loss["status"] != "RECORDED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only RECORDED losses may be reversed.")
    helpers.check_occ(loss, body.get("version"))

    inv = db.inventory_batches.get(loss["inventory_batch_id"])
    if inv is not None:
        inv["quantity_on_hand"] += loss["quantity_lost"]
        # If the batch was DEPLETED due to the loss, restore to ON_HAND.
        if inv["status"] == "DEPLETED" and inv["quantity_on_hand"] > 0:
            inv["status"] = "ON_HAND"
        helpers.bump(inv)
        audit.append(target_type="InventoryBatch", target_id=inv["id"], action="ADJUST_STOCK",
                     payload={"delta": loss["quantity_lost"],
                              "reason": "loss-reversal",
                              "loss_record_id": lid,
                              "new_quantity_on_hand": inv["quantity_on_hand"]})

    loss["status"] = "REVERSED"
    helpers.bump(loss)
    audit.append(target_type="LossRecord", target_id=lid, action="REVERSE_LOSS",
                 payload={"reversed_at": clock.iso_format(clock.now())},
                 external_systems=["FINANCE"])
    return response.ok(serializers.loss_record_dict(loss))


@bp.route("/<lid>/resolve-investigation", methods=["POST"])
@auth_required("FinanceController")
def resolve_investigation(lid):
    loss = db.loss_records.get(lid)
    if loss is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"LossRecord {lid} not found.")
    body = helpers.get_json_body()
    helpers.check_occ(loss, body.get("version"))
    if loss["investigation_status"] != "PENDING":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Only PENDING investigations may be resolved.")
    loss["investigation_status"] = "RESOLVED"
    helpers.bump(loss)
    audit.append(target_type="LossRecord", target_id=lid, action="RESOLVE_INVESTIGATION",
                 payload={"resolution_notes": body.get("resolution_notes")},
                 external_systems=["FINANCE"])
    return response.ok(serializers.loss_record_dict(loss))
