"""MillRun endpoints (PRD §3.6)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_BIN_NOT_FOUND, ERR_MILL_RUN_INVALID_STATE,
    ERR_BIN_NOT_RECEIVE_READY, ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
    ERR_MILL_INPUT_EXCEEDS_BIN_STOCK, ERR_INVENTORY_ADJUSTMENT_NEGATIVE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import D, q2, new_id, next_seq
from validate import get_body, req_str, req_num

bp = Blueprint("mill_runs", __name__)

EST_FIELDS = ["head", "broken", "brewers", "bran", "hull"]


@bp.route("/mill/mill-runs", methods=["POST"])
def create_mill_run():
    authorized(["MillSupervisor"])
    body = get_body()
    season_id = req_str(body, "season_id")
    input_bin_id = req_str(body, "input_bin_id")
    input_cwt = req_num(body, "input_cwt", positive=True)
    require_resource("seasons", season_id)
    b = db["bins"].get(input_bin_id)
    if b is None or b["season_id"] != season_id:
        raise_error(ERR_BIN_NOT_FOUND, "input bin not found in this season")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "input_bin_id": input_bin_id,
        "variety": b["variety_lock"],
        "input_cwt": q2(input_cwt),
        "est_head_cwt": None,
        "est_broken_cwt": None,
        "est_brewers_cwt": None,
        "est_bran_cwt": None,
        "est_hull_cwt": None,
        "est_loss_cwt": None,
        "act_head_cwt": None,
        "act_broken_cwt": None,
        "act_brewers_cwt": None,
        "act_bran_cwt": None,
        "act_hull_cwt": None,
        "act_loss_cwt": None,
        "status": "SCHEDULED",
    }
    core.touch_new(rec)
    db["mill_runs"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/mill/mill-runs", methods=["GET"])
def list_mill_runs():
    return list_endpoint("mill_runs", ["season_id", "input_bin_id", "status", "variety"])


@bp.route("/mill/mill-runs/<rid>", methods=["GET"])
def get_mill_run(rid):
    return get_endpoint("mill_runs", rid)


@bp.route("/mill/mill-runs/<rid>/start", methods=["POST"])
def start_mill_run(rid):
    authorized(["MillSupervisor"])
    run = require_resource("mill_runs", rid)
    if run["status"] != "SCHEDULED":
        raise_error(ERR_MILL_RUN_INVALID_STATE,
                    f"start requires SCHEDULED; run is {run['status']}")
    b = db["bins"][run["input_bin_id"]]
    if b["status"] != "AVAILABLE":
        raise_error(ERR_BIN_NOT_RECEIVE_READY,
                    f"bin status {b['status']} cannot release grain")
    if core.active_hold_on(run["season_id"], "BIN", b["id"]):
        raise_error(ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
                    "an ACTIVE hold on the input bin blocks the draw")
    if D(b["stock_cwt"]) < D(run["input_cwt"]):
        raise_error(ERR_MILL_INPUT_EXCEEDS_BIN_STOCK,
                    "mill input exceeds the bin's physical stock")
    b["stock_cwt"] = q2(D(b["stock_cwt"]) - D(run["input_cwt"]))
    core.refresh_bin(b)
    core.bump(b)
    run["status"] = "IN_PROCESS"
    core.bump(run)
    return success_object(public(run))


@bp.route("/mill/mill-runs/<rid>/complete", methods=["POST"])
def complete_mill_run(rid):
    authorized(["MillSupervisor"])
    run = require_resource("mill_runs", rid)
    if run["status"] != "IN_PROCESS":
        raise_error(ERR_MILL_RUN_INVALID_STATE,
                    f"complete requires IN_PROCESS; run is {run['status']}")
    variety = run["variety"]
    if variety not in core.VARIETIES:
        b = db["bins"].get(run["input_bin_id"])
        variety = (b or {}).get("variety_lock") or "LONG_GRAIN"
        run["variety"] = variety
    est = core.mill_estimates(D(run["input_cwt"]), variety)
    run.update(est)
    run["status"] = "COMPLETED"
    core.bump(run)
    return success_object(public(run))


@bp.route("/mill/mill-runs/<rid>/verify", methods=["POST"])
def verify_mill_run(rid):
    authorized(["MillSupervisor"])
    body = get_body()
    act = {}
    for f in EST_FIELDS:
        act[f] = q2(req_num(body, f"act_{f}_cwt", non_negative=True))
    run = require_resource("mill_runs", rid)
    if run["status"] != "COMPLETED":
        raise_error(ERR_MILL_RUN_INVALID_STATE,
                    f"verify requires COMPLETED; run is {run['status']}")
    act_loss = q2(D(run["input_cwt"]) - sum(act.values()))
    # Non-negativity guard: available(p) - est(p) + act(p) >= 0 for every product.
    inv = core.season_inventory(run["season_id"])
    for product, f in core.MILL_FIELD.items():
        after = D(inv[product]["available_cwt"]) - D(run[f"est_{f}_cwt"]) + act[f]
        if after < 0:
            raise_error(ERR_INVENTORY_ADJUSTMENT_NEGATIVE,
                        f"verify would drive {product} available inventory below zero")
    for f in EST_FIELDS:
        run[f"act_{f}_cwt"] = act[f]
    run["act_loss_cwt"] = act_loss
    run["status"] = "VERIFIED"
    core.bump(run)
    return success_object(public(run))


@bp.route("/mill/mill-runs/<rid>/void", methods=["POST"])
def void_mill_run(rid):
    authorized(["MillSupervisor"])
    run = require_resource("mill_runs", rid)
    if run["status"] != "COMPLETED":
        raise_error(ERR_MILL_RUN_INVALID_STATE,
                    f"void requires COMPLETED; run is {run['status']}")
    inv = core.season_inventory(run["season_id"])
    for product, f in core.MILL_FIELD.items():
        after = D(inv[product]["available_cwt"]) - D(run[f"est_{f}_cwt"])
        if after < 0:
            raise_error(ERR_INVENTORY_ADJUSTMENT_NEGATIVE,
                        f"void would drive {product} available inventory below zero")
    run["status"] = "VOIDED"
    core.bump(run)
    return success_object(public(run))
