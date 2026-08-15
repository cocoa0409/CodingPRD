"""RecallAction endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import (require_roles, get_json_body, require_string,
                        require_enum, require_number, parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import stamp_new, touch, serialize, serialize_list

bp = Blueprint("recall_actions", __name__)

RECALL_CLASSES = {"CLASS_I", "CLASS_II", "CLASS_III"}
# Truly terminal for further transitions: CLOSED and TERMINATED. COMPLETED still
# has the outgoing COMPLETED -> CLOSED transition, so it is not terminal here.
RECALL_TERMINAL = {"CLOSED", "TERMINATED"}
# Statuses considered "open" for the brand rollup: anything not CLOSED/TERMINATED.
# Per entity doc: "not CLOSED" -- but TERMINATED is a compensation unwind, so we
# follow the scaffold literally: open = status != CLOSED minus TERMINATED which no
# longer holds product. PRD 3.8: brand count increases on initiation and is
# recomputed on close/terminate.


@bp.route("/recall-actions", methods=["POST"])
def create_recall():
    require_roles("QAApprover")
    body = get_json_body()
    formula_id = require_string(body, "formula_id")
    formula = store.formulas.get(formula_id)
    if formula is None:
        raise errors.not_found("Formula not found")
    scope_batch_ids = body.get("scope_batch_ids")
    if scope_batch_ids is None:
        raise errors.invalid_request("scope_batch_ids is required")
    if not isinstance(scope_batch_ids, list):
        raise errors.invalid_request("scope_batch_ids must be an array")
    recall_class = require_enum(body, "recall_class", RECALL_CLASSES)
    reason = require_string(body, "reason")

    # Resolve scope
    if scope_batch_ids:
        in_scope_batches = []
        for bid in scope_batch_ids:
            if not isinstance(bid, str):
                raise errors.invalid_request("scope_batch_ids must contain strings")
            b = store.production_batches.get(bid)
            if b is None:
                raise errors.not_found(f"ProductionBatch {bid} not found")
            if b["formula_id"] != formula_id:
                raise errors.invalid_request(
                    "scope_batch_ids must belong to the recalled formula")
            in_scope_batches.append(b)
    else:
        # Empty array -> every non-terminal batch of the formula. For recall-scope
        # purposes, "non-terminal" means not already RECALLED and not REJECTED:
        # COMPLETED batches remain recallable per the cascade rule (COMPLETED or
        # ON_HOLD -> RECALLED).
        excluded = {"REJECTED", "RECALLED"}
        in_scope_batches = [b for b in store.production_batches.values()
                            if b["formula_id"] == formula_id and b["status"] not in excluded]

    # Cascade: in-scope batches in COMPLETED or ON_HOLD -> RECALLED
    moved_batches = []
    for b in in_scope_batches:
        if b["status"] in ("COMPLETED", "ON_HOLD"):
            b["status"] = "RECALLED"
            touch(b, status_changed=True)
            moved_batches.append(b)

    # Cascade: lots of in-scope batches in ACTIVE/QUARANTINED/RELEASED -> RECALLED
    in_scope_ids = {b["id"] for b in in_scope_batches}
    affected_lots = []
    for lot in store.batch_lot_codes.values():
        if lot["batch_id"] in in_scope_ids and lot["status"] in ("ACTIVE", "QUARANTINED", "RELEASED"):
            lot["status"] = "RECALLED"
            touch(lot, status_changed=True)
            affected_lots.append(lot)

    if not in_scope_batches and not affected_lots:
        raise errors.recall_scope_empty()

    recall = {
        "formula_id": formula_id,
        "scope_batch_ids": list(scope_batch_ids),
        "recall_class": recall_class,
        "reason": reason,
        "status": "INITIATED",
        "affected_lot_count": len(affected_lots),
        "effectiveness_pct": 0,
        "_moved_batch_ids": [b["id"] for b in moved_batches],
        "_moved_lot_ids": [l["id"] for l in affected_lots],
    }
    stamp_new(recall)
    store.recall_actions[recall["id"]] = recall

    # Upward rollups
    formula["open_recall_flag"] = True
    brand = store.brand_owners.get(formula["brand_owner_id"])
    if brand is not None:
        brand["open_recall_count"] = int(brand.get("open_recall_count", 0)) + 1

    return success_object(serialize(recall), 201)


def _get_recall(id):
    r = store.recall_actions.get(id)
    if r is None:
        raise errors.not_found("RecallAction not found")
    return r


def _check_recall_not_terminal(r):
    if r["status"] in RECALL_TERMINAL:
        raise errors.already_terminal("RecallAction is in a terminal state")


def _recompute_recall_rollups(recall):
    """Recompute Formula.open_recall_flag and BrandOwner.open_recall_count."""
    formula = store.formulas.get(recall["formula_id"])
    if formula is None:
        return
    open_recalls = [r for r in store.recall_actions.values()
                    if r["formula_id"] == formula["id"]
                    and r["status"] not in ("CLOSED", "TERMINATED")]
    formula["open_recall_flag"] = len(open_recalls) > 0
    brand = store.brand_owners.get(formula["brand_owner_id"])
    if brand is not None:
        # Count recalls across all of the brand's formulas that are not closed
        # (terminated recalls have been compensated, so they do not hold product).
        brand_formula_ids = {f["id"] for f in store.formulas.values()
                             if f["brand_owner_id"] == brand["id"]}
        count = sum(1 for r in store.recall_actions.values()
                    if r["formula_id"] in brand_formula_ids
                    and r["status"] not in ("CLOSED", "TERMINATED"))
        brand["open_recall_count"] = count


@bp.route("/recall-actions/<id>", methods=["GET"])
def get_recall(id):
    require_roles("PlatformAdmin", "QAApprover", "QualityAnalyst")
    recall = _get_recall(id)
    return success_object(serialize(recall), 200)


@bp.route("/formulas/<id>/recall-actions", methods=["GET"])
def list_recalls_for_formula(id):
    require_roles("PlatformAdmin", "QAApprover", "QualityAnalyst")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [r for r in store.recall_actions.values() if r["formula_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


@bp.route("/recall-actions/<id>/begin-effectiveness-check", methods=["POST"])
def begin_effectiveness_check(id):
    require_roles("QAApprover")
    recall = _get_recall(id)
    _check_recall_not_terminal(recall)
    if recall["status"] != "INITIATED":
        raise errors.invalid_state("Only INITIATED recalls can begin effectiveness check")
    if int(recall.get("affected_lot_count", 0)) <= 0:
        raise errors.recall_no_lots()
    recall["status"] = "EFFECTIVENESS_CHECK"
    touch(recall, status_changed=True)
    return success_object(serialize(recall), 200)


@bp.route("/recall-actions/<id>/record-effectiveness", methods=["POST"])
def record_effectiveness(id):
    require_roles("QAApprover")
    recall = _get_recall(id)
    _check_recall_not_terminal(recall)
    if recall["status"] != "EFFECTIVENESS_CHECK":
        raise errors.invalid_state("Only EFFECTIVENESS_CHECK recalls can record effectiveness")
    body = get_json_body()
    pct = require_number(body, "effectiveness_pct")
    if pct < 0 or pct > 100:
        raise errors.effectiveness_range()
    recall["effectiveness_pct"] = pct
    recall["status"] = "COMPLETED"
    touch(recall, status_changed=True)
    return success_object(serialize(recall), 200)


@bp.route("/recall-actions/<id>/close", methods=["POST"])
def close_recall(id):
    require_roles("QAApprover")
    recall = _get_recall(id)
    _check_recall_not_terminal(recall)
    if recall["status"] != "COMPLETED":
        raise errors.invalid_state("Only COMPLETED recalls can be closed")
    recall["status"] = "CLOSED"
    touch(recall, status_changed=True)
    _recompute_recall_rollups(recall)
    return success_object(serialize(recall), 200)


@bp.route("/recall-actions/<id>/terminate", methods=["POST"])
def terminate_recall(id):
    require_roles("QAApprover")
    recall = _get_recall(id)
    _check_recall_not_terminal(recall)
    if recall["status"] != "INITIATED":
        raise errors.invalid_state("Only INITIATED recalls can be terminated")
    # Compensating cascade: lots -> QUARANTINED, batches -> ON_HOLD
    for lot_id in recall.get("_moved_lot_ids", []):
        lot = store.batch_lot_codes.get(lot_id)
        if lot is not None and lot["status"] == "RECALLED":
            lot["status"] = "QUARANTINED"
            touch(lot, status_changed=True)
    for batch_id in recall.get("_moved_batch_ids", []):
        batch = store.production_batches.get(batch_id)
        if batch is not None and batch["status"] == "RECALLED":
            batch["status"] = "ON_HOLD"
            touch(batch, status_changed=True)
    recall["status"] = "TERMINATED"
    touch(recall, status_changed=True)
    _recompute_recall_rollups(recall)
    return success_object(serialize(recall), 200)
