"""Cut-and-wrap run resources: draft, reconcile (waste policing), void
(PRD 3.8)."""

from flask import request

from calc import D, WASTE_TOLERANCE_PCT, cut_wrap_figures
from db import STORES, new_record, touch
from errors import ApiError, invalid_state
from helpers import auth, body, f_int, f_num, f_str, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp
from services import rederive_order_status

bp = make_bp("cut_wrap_runs")

GET_ROLES = ("PlantAdmin", "CutWrapOperator", "ComplianceOfficer", "SalesPlanner")


@bp.post("/plant/cut-wrap-runs")
def create_run():
    auth("CutWrapOperator")
    b = body()
    allocation_order_id = f_str(b, "allocation_order_id")
    wheels_in = f_int(b, "wheels_in", positive=True)
    finished_case_weight_kg = f_num(b, "finished_case_weight_kg", non_negative=True)
    trim_waste_kg = f_num(b, "trim_waste_kg", non_negative=True)
    order = get_or_404("allocation_orders", allocation_order_id, "allocation order")
    batch = STORES["cheese_batches"].get(order["cheese_batch_id"])
    variety = batch["variety"] if batch else None
    input_exact, gap_exact, input_stored, gap_stored = cut_wrap_figures(
        variety, wheels_in, finished_case_weight_kg, trim_waste_kg
    )
    rec = new_record()
    rec.update(
        plant_id=order["plant_id"],
        allocation_order_id=order["id"],
        wheels_in=wheels_in,
        finished_case_weight_kg=finished_case_weight_kg,
        trim_waste_kg=trim_waste_kg,
        input_weight_kg=input_stored,
        reconciliation_gap_kg=gap_stored,
        status="DRAFT",
        # Exact figures retained for reconcile-time boundary comparisons
        # (tolerance is computed from the exact, unrounded input weight).
        _input_exact=input_exact,
        _gap_exact=gap_exact,
    )
    STORES["cut_wrap_runs"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/plant/cut-wrap-runs/<cutWrapRunId>")
def get_run(cutWrapRunId):
    auth(*GET_ROLES)
    rec = get_or_404("cut_wrap_runs", cutWrapRunId, "cut-wrap run")
    return success(serialize(rec))


@bp.get("/plant/cut-wrap-runs")
def list_runs():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "cut_wrap_runs",
        [
            ("plant_id", request.args.get("plant_id")),
            ("allocation_order_id", request.args.get("allocation_order_id")),
            ("status", request.args.get("status")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.post("/plant/cut-wrap-runs/<cutWrapRunId>/reconcile")
def reconcile_run(cutWrapRunId):
    auth("CutWrapOperator")
    body(required=False)
    rec = get_or_404("cut_wrap_runs", cutWrapRunId, "cut-wrap run")
    if rec["status"] != "DRAFT":
        invalid_state("Cut-wrap run is not DRAFT")
    order = STORES["allocation_orders"].get(rec["allocation_order_id"])
    if order is None or order["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        invalid_state("Allocation order is not OPEN or PARTIALLY_FILLED")
    batch = STORES["cheese_batches"].get(order["cheese_batch_id"])
    # Rung 8: batch must be RELEASED.
    if batch is None or batch["release_decision"] != "RELEASED":
        raise ApiError("ERR_BATCH_NOT_RELEASED", 409, "Batch is not RELEASED")
    # Rung 12 in the ladder's listed order (PRD 2.9 / 3.8 defers to it):
    # waste-negative, waste-tolerance, then order over-fill.
    gap_exact = rec["_gap_exact"]
    input_exact = rec["_input_exact"]
    if gap_exact < 0:
        raise ApiError(
            "ERR_WASTE_NEGATIVE", 422, "reconciliation_gap_kg is negative"
        )
    if gap_exact > WASTE_TOLERANCE_PCT * input_exact:
        raise ApiError(
            "ERR_WASTE_TOLERANCE",
            422,
            "reconciliation_gap_kg exceeds 2% of input_weight_kg",
        )
    if order["wheels_cut"] + rec["wheels_in"] > order["wheels_requested"]:
        raise ApiError(
            "ERR_ORDER_OVERFILL", 422, "Reconcile would over-fill the order"
        )
    # --- effects ---
    rec["status"] = "RECONCILED"
    touch(rec)
    order["wheels_cut"] += rec["wheels_in"]
    rederive_order_status(order)
    touch(order)
    if order["status"] == "FILLED":
        # Cross-entity bubble-up: the batch moves RELEASED -> ALLOCATED.
        batch["status"] = "ALLOCATED"
        touch(batch)
    return success(serialize(rec))


@bp.post("/plant/cut-wrap-runs/<cutWrapRunId>/void")
def void_run(cutWrapRunId):
    auth("CutWrapOperator")
    body(required=False)
    rec = get_or_404("cut_wrap_runs", cutWrapRunId, "cut-wrap run")
    if rec["status"] != "DRAFT":
        invalid_state("Cut-wrap run is not DRAFT")
    rec["status"] = "VOIDED"
    touch(rec)
    return success(serialize(rec))
