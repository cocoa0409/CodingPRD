"""DryingRun endpoints (PRD §3.5)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_BIN_NOT_FOUND, ERR_LOT_NOT_FOUND, ERR_INVALID_LOT_STATE,
    ERR_ACTIVE_HOLD_BLOCKS_OPERATION, ERR_LOT_ALREADY_IN_DRYING_RUN,
    ERR_BIN_CAPACITY_EXCEEDED, ERR_BIN_NOT_RECEIVE_READY, ERR_DRYING_RUN_NOT_PLANNED,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import D, q2, new_id, next_seq
from validate import get_body, req_str, req_str_list, opt_int, req_num

bp = Blueprint("drying_runs", __name__)


@bp.route("/mill/drying-runs", methods=["POST"])
def create_drying_run():
    authorized(["DryerOperator"])
    body = get_body()
    season_id = req_str(body, "season_id")
    lot_ids = req_str_list(body, "lot_ids")
    destination_bin_id = req_str(body, "destination_bin_id")
    fuel = opt_int(body, "fuel_cost_cents", default=0, non_negative=True)
    require_resource("seasons", season_id)
    b = db["bins"].get(destination_bin_id)
    if b is None or b["season_id"] != season_id:
        raise_error(ERR_BIN_NOT_FOUND, "destination bin not found in this season")
    lots = []
    for lid in lot_ids:
        lot = db["lots"].get(lid)
        if lot is None or lot["season_id"] != season_id:
            raise_error(ERR_LOT_NOT_FOUND, f"lot not found in this season: {lid}")
        lots.append(lot)
    # state: every lot must be GRADED
    for lot in lots:
        if lot["status"] != "GRADED":
            raise_error(ERR_INVALID_LOT_STATE,
                        f"drying-run lots must be GRADED; lot {lot['id']} is {lot['status']}")
    # holds: an ACTIVE hold on the destination bin refuses new drying plans
    if core.active_hold_on(season_id, "BIN", b["id"]):
        raise_error(ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
                    "an ACTIVE hold on the destination bin blocks drying plans")
    # constraints: each lot unclaimed by another non-terminal run
    for lot in lots:
        if lot.get("drying_run_id") is not None:
            raise_error(ERR_LOT_ALREADY_IN_DRYING_RUN,
                        f"lot {lot['id']} is already referenced by a non-terminal drying run")
    expected = q2(sum(D(lot["dry_weight_cwt"]) for lot in lots))
    # capacity: the reservation must fit
    if D(b["available_cwt"]) < expected:
        raise_error(ERR_BIN_CAPACITY_EXCEEDED,
                    "drying reservation exceeds bin available capacity")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "destination_bin_id": destination_bin_id,
        "lot_ids": lot_ids,
        "fuel_cost_cents": fuel,
        "expected_output_cwt": expected,
        "actual_output_cwt": None,
        "status": "PLANNED",
    }
    core.touch_new(rec)
    db["drying_runs"][rec["id"]] = rec
    b["reserved_cwt"] = q2(D(b["reserved_cwt"]) + expected)
    if b["variety_lock"] is None and lots:
        b["variety_lock"] = lots[0]["variety"]
    core.refresh_bin(b)
    core.bump(b)
    for lot in lots:
        lot["drying_run_id"] = rec["id"]
        core.bump(lot)
    return success_object(public(rec), 201)


@bp.route("/mill/drying-runs", methods=["GET"])
def list_drying_runs():
    return list_endpoint("drying_runs", ["season_id", "destination_bin_id", "status"])


@bp.route("/mill/drying-runs/<rid>", methods=["GET"])
def get_drying_run(rid):
    return get_endpoint("drying_runs", rid)


@bp.route("/mill/drying-runs/<rid>/complete", methods=["POST"])
def complete_drying_run(rid):
    authorized(["DryerOperator"])
    body = get_body()
    actual = req_num(body, "actual_output_cwt", non_negative=True)
    run = require_resource("drying_runs", rid)
    if run["status"] != "PLANNED":
        raise_error(ERR_DRYING_RUN_NOT_PLANNED,
                    f"complete requires PLANNED; run is {run['status']}")
    b = db["bins"][run["destination_bin_id"]]
    if b["status"] != "AVAILABLE":
        raise_error(ERR_BIN_NOT_RECEIVE_READY,
                    f"bin status {b['status']} cannot receive grain")
    if core.active_hold_on(run["season_id"], "BIN", b["id"]):
        raise_error(ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
                    "an ACTIVE hold on the destination bin blocks completion")
    actual_q = q2(actual)
    b["reserved_cwt"] = q2(D(b["reserved_cwt"]) - D(run["expected_output_cwt"]))
    b["stock_cwt"] = q2(D(b["stock_cwt"]) + actual_q)
    if b["variety_lock"] is None and run["lot_ids"]:
        first = db["lots"].get(run["lot_ids"][0])
        if first is not None:
            b["variety_lock"] = first["variety"]
    core.refresh_bin(b)
    core.bump(b)
    for lid in run["lot_ids"]:
        lot = db["lots"].get(lid)
        if lot is not None and lot["status"] == "GRADED":
            lot["status"] = "BINNED"
            lot["bin_id"] = b["id"]
            core.bump(lot)
    run["actual_output_cwt"] = actual_q
    run["status"] = "COMPLETED"
    core.bump(run)
    return success_object(public(run))


@bp.route("/mill/drying-runs/<rid>/cancel", methods=["POST"])
def cancel_drying_run(rid):
    authorized(["DryerOperator"])
    run = require_resource("drying_runs", rid)
    if run["status"] != "PLANNED":
        raise_error(ERR_DRYING_RUN_NOT_PLANNED,
                    f"cancel requires PLANNED; run is {run['status']}")
    core.cancel_drying_run(run)
    return success_object(public(run))
