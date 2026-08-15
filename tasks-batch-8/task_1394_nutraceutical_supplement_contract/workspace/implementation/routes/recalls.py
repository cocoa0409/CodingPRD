"""Recall initiation/trace/close (PRD 3.8) and the logical clock (PRD 2.6)."""
from flask import Blueprint

from db import store, new_entity, touch, set_clock
from errors import (
    raise_error,
    ERR_LOT_STATE,
    ERR_BATCH_STATE,
    ERR_RECALL_STATE,
)
from middleware import require_roles
from response import ok
from services import recall_batch
from util import body, not_found, req_enum, req_str, sorted_by_created, parse_dt

bp = Blueprint("recalls", __name__)


@bp.post("/api/recalls")
@require_roles("QAManager")
def initiate_recall(user_id, role):
    data = body()
    scope_type = req_enum(data, "scope_type", ("MATERIAL_LOT", "BATCH"))
    scope_id = req_str(data, "scope_id")
    reason = req_str(data, "reason")

    affected = 0
    if scope_type == "MATERIAL_LOT":
        lot = store["material_lots"].get(scope_id)
        if lot is None:
            not_found("scope_id does not identify an existing material lot")
        if lot["status"] != "RELEASED":
            raise_error(ERR_LOT_STATE, "Lot-scope recall requires a RELEASED lot")
        lot["status"] = "RECALLED"
        touch(lot)
        # Every batch holding an ACTIVE consumption of the lot whose quality is
        # RELEASED transitions to RECALLED, in ascending creation order.
        targets = []
        for batch in store["batches"].values():
            if batch["quality_status"] != "RELEASED":
                continue
            has_lot = any(
                row["batch_id"] == batch["id"]
                and row["material_lot_id"] == scope_id
                and row["status"] == "ACTIVE"
                for row in store["batch_consumptions"].values()
            )
            if has_lot:
                targets.append(batch)
        for batch in sorted_by_created(targets):
            recall_batch(batch)
            affected += 1
    else:  # BATCH
        batch = store["batches"].get(scope_id)
        if batch is None:
            not_found("scope_id does not identify an existing batch")
        if batch["quality_status"] != "RELEASED":
            raise_error(ERR_BATCH_STATE, "Batch-scope recall requires a RELEASED batch")
        recall_batch(batch)
        affected = 1

    # The trace executes synchronously: INITIATED -> TRACED within the request.
    event = new_entity({
        "scope_type": scope_type,
        "scope_id": scope_id,
        "reason": reason,
        "affected_batch_count": affected,
        "status": "TRACED",
    })
    store["recall_events"][event["id"]] = event
    return ok(event, 201)


@bp.post("/api/recalls/<recall_id>/close")
@require_roles("QAManager")
def close_recall(user_id, role, recall_id):
    event = store["recall_events"].get(recall_id)
    if event is None:
        not_found()
    if event["status"] != "TRACED":
        raise_error(ERR_RECALL_STATE, "Only a TRACED recall may be closed")
    event["status"] = "CLOSED"
    touch(event)
    return ok(event)


# ---------------------------------------------------------------------------
# Test-driving logical clock (PRD 2.6).
# ---------------------------------------------------------------------------
@bp.post("/api/_clock/set_current_utc")
@require_roles("ProductionPlanner", "QAManager")
def set_current_utc(user_id, role):
    data = body()
    to_iso8601 = req_str(data, "to_iso8601")
    dt = parse_dt(to_iso8601, "to_iso8601")
    set_clock(dt)
    return ok({}, 200)
