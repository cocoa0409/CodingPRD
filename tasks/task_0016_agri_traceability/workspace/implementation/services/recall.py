"""RecallOrder service: initiation, notification, disposal, completion, cancellation."""

from decimal import Decimal, ROUND_HALF_UP

from flask import g

from common import (
    get_json_body,
    paginate,
    parse_iso_datetime,
    parse_pagination,
    require_field,
    round_kg,
    sort_by_created_at,
    stamp_create,
    stamp_create_immutable,
    stamp_update,
)
from db import db
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RECALL_ALREADY_ACTIVE,
    ERR_RECALL_HAS_DISPOSALS,
    ERR_RECALL_OVER_DISPOSED,
    ERR_RECALL_RESIDUAL_NONZERO,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
    raise_error,
)
from services.audit import record_audit
from services.planting_batch import get_batch_or_404, recompute_posture
from services.qr import revoke_qrs_for_batch


VALID_CLASSES = {"CLASS_I", "CLASS_II", "CLASS_III"}
VALID_REASONS = {"INSPECTION_FAIL", "COLD_CHAIN_BREACH",
                 "PROHIBITED_SUBSTANCE", "CONSUMER_COMPLAINT"}


def _serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "planting_batch_id": r["planting_batch_id"],
        "recall_class": r["recall_class"],
        "reason_code": r["reason_code"],
        "scope_distributor_ids": list(r["scope_distributor_ids"]),
        "status": r["status"],
        "initiated_by_user_id": r["initiated_by_user_id"],
        "total_quantity_recalled_kg": float(round_kg(r.get("total_quantity_recalled_kg", 0))),
        "total_quantity_disposed_kg": float(round_kg(r.get("total_quantity_disposed_kg", 0))),
        "disposal_records": list(r.get("disposal_records", [])),
    }


def get_recall_or_404(rid):
    r = db.recall_orders.get(rid)
    if r is None:
        raise_error(ERR_NOT_FOUND, f"recall order {rid} not found")
    return r


def _compute_scope_distributor_ids(batch_id):
    distributor_ids = set(db.distributors.keys())
    scope = []
    seen = set()
    for leg in db.logistics_legs.values():
        if leg["planting_batch_id"] != batch_id:
            continue
        if leg["to_party_id"] in distributor_ids and leg["to_party_id"] not in seen:
            seen.add(leg["to_party_id"])
            scope.append(leg["to_party_id"])
    return scope


def _compute_total_recalled_kg(batch_id, recall_created_at):
    total = Decimal("0")
    for hr in db.harvest_records.values():
        if hr["planting_batch_id"] != batch_id:
            continue
        if hr["created_at"] <= recall_created_at:
            total += Decimal(str(hr["quantity_kg"]))
    return total


def _do_recall_initiate(batch, recall_class, reason_code, initiated_by, allow_states):
    """Shared core for manual + auto recall initiation."""
    if batch.get("recall_status") == "ACTIVE_RECALL":
        raise_error(ERR_RECALL_ALREADY_ACTIVE, "batch already has active recall")
    if batch["status"] not in allow_states:
        raise_error(ERR_INVALID_STATE,
                    f"recall not permitted on batch in {batch['status']}")

    before_batch_status = batch["status"]
    recall = {
        "id": db.new_id(),
        "planting_batch_id": batch["id"],
        "recall_class": recall_class,
        "reason_code": reason_code,
        "scope_distributor_ids": _compute_scope_distributor_ids(batch["id"]),
        "status": "INITIATED",
        "initiated_by_user_id": initiated_by,
        "total_quantity_recalled_kg": 0.0,
        "total_quantity_disposed_kg": 0.0,
        "disposal_records": [],
    }
    stamp_create(recall)
    # snapshot total_quantity_recalled_kg using recall.created_at
    total = _compute_total_recalled_kg(batch["id"], recall["created_at"])
    recall["total_quantity_recalled_kg"] = float(total)
    db.recall_orders[recall["id"]] = recall

    # Cascade
    batch["recall_status"] = "ACTIVE_RECALL"
    batch["status"] = "RECALLED"
    stamp_update(batch)

    revoke_qrs_for_batch(batch["id"], value=True)

    for leg in db.logistics_legs.values():
        if leg["planting_batch_id"] == batch["id"] and leg["status"] in {"PLANNED", "IN_TRANSIT"}:
            before_leg = leg["status"]
            leg["status"] = "ABNORMAL"
            stamp_update(leg)
            record_audit(
                "LogisticsLeg", leg["id"], "STATE_TRANSITION", "ABNORMAL",
                before_state=before_leg,
                change_summary={"trigger": "recall_cascade"},
            )

    record_audit(
        "RecallOrder", recall["id"], "RECALL_INITIATE", "INITIATED",
        before_state=None,
        change_summary={"reason_code": reason_code,
                        "before_state": before_batch_status},
    )
    record_audit(
        "PlantingBatch", batch["id"], "STATE_TRANSITION", "RECALLED",
        before_state=before_batch_status,
        change_summary={"trigger": "recall_initiate", "before_state": before_batch_status},
    )
    return recall


def initiate_recall():
    body = get_json_body()
    planting_batch_id = require_field(body, "planting_batch_id", str)
    recall_class = require_field(body, "recall_class", str)
    reason_code = require_field(body, "reason_code", str)
    if recall_class not in VALID_CLASSES:
        raise_error(ERR_VALIDATION, "recall_class invalid")
    if reason_code not in VALID_REASONS:
        raise_error(ERR_VALIDATION, "reason_code invalid")

    with db.lock:
        batch = db.planting_batches.get(planting_batch_id)
        if batch is None:
            raise_error(ERR_NOT_FOUND, "planting batch not found")
        recall = _do_recall_initiate(
            batch, recall_class, reason_code,
            initiated_by=g.user_id,
            allow_states={"INSPECTED_PASS", "IN_TRANSIT", "DELIVERED"},
        )
    return _serialize(recall)


def _auto_initiate_recall(batch, reason_code):
    """Internal helper: auto-emit recall on cold-chain breach."""
    return _do_recall_initiate(
        batch,
        recall_class="CLASS_II",
        reason_code=reason_code,
        initiated_by="system",
        allow_states={"INSPECTED_PASS", "IN_TRANSIT", "DELIVERED"},
    )


def notify_recall(recall_id):
    body = get_json_body()
    with db.lock:
        recall = get_recall_or_404(recall_id)
        if "version" in body and body["version"] is not None:
            if body["version"] != recall["version"]:
                raise_error(ERR_VERSION_CONFLICT, "version mismatch")
        if recall["status"] != "INITIATED":
            raise_error(ERR_INVALID_STATE, f"cannot notify recall in {recall['status']}")
        # Emit notification events
        for did in recall["scope_distributor_ids"]:
            d = db.distributors.get(did)
            if d is None:
                continue
            db.notifications.append({
                "recall_order_id": recall["id"],
                "distributor_id": did,
                "endpoint": d["notification_endpoint"],
            })
        before = recall["status"]
        recall["status"] = "NOTIFIED"
        stamp_update(recall)
        record_audit(
            "RecallOrder", recall["id"], "RECALL_NOTIFY", "NOTIFIED",
            before_state=before,
            change_summary={"distributor_count": len(recall["scope_distributor_ids"])},
        )
    return _serialize(recall)


def record_disposal(recall_id):
    body = get_json_body()
    distributor_id = require_field(body, "distributor_id", str)
    disposed_kg = body.get("disposed_kg")
    if disposed_kg is None:
        raise_error(ERR_VALIDATION, "missing required field disposed_kg")
    try:
        disposed_kg_f = float(disposed_kg)
    except Exception:
        raise_error(ERR_VALIDATION, "disposed_kg must be numeric")
    disposed_at = require_field(body, "disposed_at", str)
    parse_iso_datetime(disposed_at, "disposed_at")

    # Distributor-supplied id must equal acting X-User-ID
    if g.user_role == "Distributor" and distributor_id != g.user_id:
        raise_error(ERR_FORBIDDEN, "distributor_id must match X-User-ID")
    if disposed_kg_f <= 0:
        raise_error(ERR_VALIDATION, "disposed_kg must be > 0")

    with db.lock:
        recall = get_recall_or_404(recall_id)
        if recall["status"] not in {"NOTIFIED", "IN_PROGRESS"}:
            raise_error(ERR_INVALID_STATE, f"cannot record disposal in {recall['status']}")

        # Per scaffold: round each disposed_kg to 2dp before summing.
        rounded_new = Decimal(str(disposed_kg_f)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Compute current cumulative from existing disposal records in chronological order
        existing = list(recall.get("disposal_records", []))
        existing.sort(key=lambda d: (d["disposed_at"], d["created_at"]))
        cumulative = Decimal("0")
        for d in existing:
            cumulative += Decimal(str(d["disposed_kg"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        total_recalled = Decimal(str(recall["total_quantity_recalled_kg"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if cumulative + rounded_new > total_recalled:
            raise_error(ERR_RECALL_OVER_DISPOSED,
                        "cumulative disposed_kg would exceed total_quantity_recalled_kg")

        entry = {
            "id": db.new_id(),
            "distributor_id": distributor_id,
            "disposed_kg": float(rounded_new),
            "disposed_at": disposed_at,
        }
        stamp_create_immutable(entry)
        recall["disposal_records"].append(entry)
        # Recompute total_quantity_disposed_kg by walking chronological order.
        all_records = sorted(recall["disposal_records"],
                             key=lambda d: (d["disposed_at"], d["created_at"]))
        total_disp = Decimal("0")
        for d in all_records:
            total_disp += Decimal(str(d["disposed_kg"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        recall["total_quantity_disposed_kg"] = float(total_disp)
        before = recall["status"]
        if recall["status"] == "NOTIFIED":
            recall["status"] = "IN_PROGRESS"
        stamp_update(recall)

        record_audit(
            "RecallOrder", recall["id"], "RECALL_DISPOSE", recall["status"],
            before_state=before,
            change_summary={"disposed_kg": float(rounded_new),
                            "distributor_id": distributor_id,
                            "cumulative": float(total_disp)},
        )
    return _serialize(recall)


def complete_recall(recall_id):
    body = get_json_body()
    with db.lock:
        recall = get_recall_or_404(recall_id)
        if "version" in body and body["version"] is not None:
            if body["version"] != recall["version"]:
                raise_error(ERR_VERSION_CONFLICT, "version mismatch")
        if recall["status"] != "IN_PROGRESS":
            raise_error(ERR_INVALID_STATE, f"cannot complete recall in {recall['status']}")
        total_recalled = Decimal(str(recall["total_quantity_recalled_kg"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        total_disp = Decimal(str(recall["total_quantity_disposed_kg"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if total_disp != total_recalled:
            raise_error(ERR_RECALL_RESIDUAL_NONZERO,
                        "total_quantity_disposed_kg must equal total_quantity_recalled_kg")
        before_recall = recall["status"]
        recall["status"] = "COMPLETED"
        stamp_update(recall)

        batch = db.planting_batches.get(recall["planting_batch_id"])
        if batch is not None:
            before_batch = batch["status"]
            batch["status"] = "DISPOSED"
            batch["recall_status"] = "COMPLETED"
            stamp_update(batch)
            record_audit(
                "PlantingBatch", batch["id"], "STATE_TRANSITION", "DISPOSED",
                before_state=before_batch,
                change_summary={"trigger": "recall_complete"},
            )
        record_audit(
            "RecallOrder", recall["id"], "RECALL_COMPLETE", "COMPLETED",
            before_state=before_recall,
            change_summary={},
        )
    return _serialize(recall)


def cancel_recall(recall_id):
    body = get_json_body()
    with db.lock:
        recall = get_recall_or_404(recall_id)
        if "version" in body and body["version"] is not None:
            if body["version"] != recall["version"]:
                raise_error(ERR_VERSION_CONFLICT, "version mismatch")
        if recall["status"] != "INITIATED":
            # If there are disposals, ERR_RECALL_HAS_DISPOSALS takes precedence
            if recall.get("disposal_records"):
                raise_error(ERR_RECALL_HAS_DISPOSALS, "recall has disposal records")
            raise_error(ERR_INVALID_STATE, f"cannot cancel recall in {recall['status']}")
        if recall.get("disposal_records"):
            raise_error(ERR_RECALL_HAS_DISPOSALS, "recall has disposal records")

        before = recall["status"]
        recall["status"] = "CANCELLED"
        stamp_update(recall)

        # Revert batch to its prior status (recovered from audit log change_summary)
        batch = db.planting_batches.get(recall["planting_batch_id"])
        if batch is not None:
            prior_status = None
            for log in db.audit_logs:
                if (log["entity_type"] == "RecallOrder"
                        and log["entity_id"] == recall["id"]
                        and log["action"] == "RECALL_INITIATE"):
                    prior_status = log["change_summary"].get("before_state")
                    break
            if prior_status is None:
                prior_status = "INSPECTED_PASS"
            before_batch = batch["status"]
            batch["status"] = prior_status
            batch["recall_status"] = "NONE"
            recompute_posture(batch)
            stamp_update(batch)
            record_audit(
                "PlantingBatch", batch["id"], "STATE_TRANSITION", prior_status,
                before_state=before_batch,
                change_summary={"trigger": "recall_cancel"},
            )

            # Un-revoke QRs
            revoke_qrs_for_batch(batch["id"], value=False)

        record_audit(
            "RecallOrder", recall["id"], "UPDATE", "CANCELLED",
            before_state=before,
            change_summary={"trigger": "cancel"},
        )
    return _serialize(recall)


def get_recall(recall_id):
    return _serialize(get_recall_or_404(recall_id))
