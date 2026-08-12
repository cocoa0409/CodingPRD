"""Color match endpoints: measurement entry, approve/reject verdicts."""
import uuid

from flask import Blueprint, request

from .domain import MAX_REWORK, RETENTION_MONTHS, formula_of, ser_color_match
from .errors import invalid_state, not_found, unprocessable
from .store import now, store
from .util import D, add_months, auth, body, list_response, new_record, success, touch, v_num, v_str

bp = Blueprint("color_matches", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")


@bp.post("/coatings/color-matches")
def create_color_match():
    user_id, _role = auth(("LabTechnician", "QCInspector"))
    b = body()
    batch_id = v_str(b, "batch_id")
    measured_delta_e = v_num(b, "measured_delta_e", minv=0)
    batch = store.batches.get(batch_id)
    if batch is None:
        raise not_found()
    if batch["status"] != "QC_PENDING":
        raise invalid_state("Batch is not QC_PENDING")
    formula = formula_of(batch)
    rec = new_record()
    rec.update({
        "batch_id": batch_id,
        "cycle_index": batch["rework_count"],
        "measured_delta_e": measured_delta_e,
        "threshold_delta_e": formula["target_delta_e"],
        "measured_by_user_id": user_id,
        "status": "PENDING",
        "decided_by_user_id": None,
        "decided_at": None,
        "retain_sample_id": None,
        "retain_until": None,
        "retain_purged_at": None,
    })
    store.color_matches[rec["id"]] = rec
    return success(ser_color_match(rec), 201)


@bp.get("/coatings/color-matches/<mid>")
def get_color_match(mid):
    auth(ALL)
    rec = store.color_matches.get(mid)
    if rec is None:
        raise not_found()
    return success(ser_color_match(rec), 200)


@bp.get("/coatings/color-matches")
def list_color_matches():
    auth(ALL)
    recs = list(store.color_matches.values())
    bid = request.args.get("batch_id")
    if bid is not None:
        recs = [m for m in recs if m["batch_id"] == bid]
    return list_response(recs, ser_color_match)


def _verdict_preconditions(mid, user_id):
    rec = store.color_matches.get(mid)
    if rec is None:
        raise not_found()
    if rec["status"] != "PENDING":
        raise invalid_state("Color match is not PENDING")
    batch = store.batches.get(rec["batch_id"])
    if batch is None:
        raise not_found()
    if batch["status"] != "QC_PENDING":
        raise invalid_state("Batch is not QC_PENDING")
    if rec["cycle_index"] != batch["rework_count"]:
        raise invalid_state("Measurement belongs to a stale cycle")
    return rec, batch


@bp.post("/coatings/color-matches/<mid>/approve")
def approve_color_match(mid):
    user_id, _role = auth(("QCInspector",))
    rec, batch = _verdict_preconditions(mid, user_id)
    if D(rec["measured_delta_e"]) > D(rec["threshold_delta_e"]):
        raise unprocessable("ERR_DELTA_E_EXCEEDED", "measured_delta_e exceeds the pinned threshold")
    if user_id == rec["measured_by_user_id"]:
        raise unprocessable("ERR_SEGREGATION_OF_DUTY", "Approver must differ from the measuring operator")
    decided = now()
    rec["status"] = "APPROVED"
    rec["decided_by_user_id"] = user_id
    rec["decided_at"] = decided
    rec["retain_sample_id"] = str(uuid.uuid4())
    rec["retain_until"] = add_months(decided, RETENTION_MONTHS[batch["product_category"]])
    touch(rec)
    batch["status"] = "QC_APPROVED"
    touch(batch)
    return success(ser_color_match(rec), 200)


@bp.post("/coatings/color-matches/<mid>/reject")
def reject_color_match(mid):
    user_id, _role = auth(("QCInspector",))
    rec, batch = _verdict_preconditions(mid, user_id)
    if user_id == rec["measured_by_user_id"]:
        raise unprocessable("ERR_SEGREGATION_OF_DUTY", "Rejecter must differ from the measuring operator")
    rec["status"] = "REJECTED"
    rec["decided_by_user_id"] = user_id
    rec["decided_at"] = now()
    touch(rec)
    if batch["rework_count"] < MAX_REWORK:
        batch["rework_count"] += 1
        batch["status"] = "REWORK"
    else:
        batch["status"] = "DISPOSAL_PENDING"
    touch(batch)
    order = store.orders.get(batch["order_id"]) if batch.get("order_id") else None
    if order is not None and order["status"] == "IN_PRODUCTION":
        order["status"] = "BLOCKED"
        touch(order)
    return success(ser_color_match(rec), 200)
