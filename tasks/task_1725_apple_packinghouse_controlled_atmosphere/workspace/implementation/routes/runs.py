"""Packing run endpoints: schedule, complete, cancel, void (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_COLOR_BELOW_SPEC,
    ERR_LINE_SCHEDULE_OVERLAP,
    ERR_LOT_INVALID_STATE,
    ERR_LOT_STORAGE_LIFE_EXCEEDED,
    ERR_POOL_INVALID_STATE,
    ERR_RUN_INVALID_STATE,
    ERR_RUN_WEIGHT_MISMATCH,
    ERR_SPEC_INVALID_STATE,
    ERR_WEIGHT_BALANCE_EXCEEDED,
    ERR_RUN_WINDOW_INVALID,
)
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import list_response, public, sorted_items
from services.core import new_record, touch
from services.domain import (
    get_or_create_settlement,
    recompute_attributed_cartons,
    recompute_lot_actual_packout,
    recompute_pool_totals,
)
from util import CLOCK, add_days, parse_dt, round_half_up
from validate import (
    check_body_fk, get_body, req_datetime, req_int, req_num, req_str,
    require_path_resource,
)

bp = Blueprint("packing_runs", __name__)


def _windows_overlap(s1, e1, s2, e2):
    """Half-open [start, end) intersection; back-to-back adjacency is allowed."""
    return parse_dt(s1) < parse_dt(e2) and parse_dt(s2) < parse_dt(e1)


@bp.post("/packing-runs")
def create_run():
    authorized(["Admin", "PackingSupervisor"])
    body = get_body()
    # Tier 4: body-supplied FK existence, in declared order (lot, spec, pool).
    lot = check_body_fk("lots", body.get("lot_id"), "lot_id")
    spec = check_body_fk("specs", body.get("spec_id"), "spec_id")
    pool = check_body_fk("pools", body.get("pool_id"), "pool_id")
    # Tier 5: shape.
    lot_id = req_str(body, "lot_id")
    spec_id = req_str(body, "spec_id")
    pool_id = req_str(body, "pool_id")
    line_code = req_str(body, "line_code")
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    input_weight_lbs = req_num(body, "input_weight_lbs", positive=True)
    if lot is None:
        lot = db["lots"][lot_id]
    if spec is None:
        spec = db["specs"][spec_id]
    if pool is None:
        pool = db["pools"][pool_id]
    # Tier 8 state gates, fixed order: lot, spec, pool.
    if lot["status"] != "RELEASED":
        raise_error(ERR_LOT_INVALID_STATE,
                    f"run creation requires a RELEASED lot, found {lot['status']}")
    if spec["status"] != "ACTIVE":
        raise_error(ERR_SPEC_INVALID_STATE,
                    f"run creation requires an ACTIVE spec, found {spec['status']}")
    if pool["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_POOL_INVALID_STATE,
                    f"run creation requires an OPEN or REOPENED pool, found {pool['status']}")
    # Tier 10 temporal: window, overlap, storage life.
    if parse_dt(scheduled_end) <= parse_dt(scheduled_start):
        raise_error(ERR_RUN_WINDOW_INVALID,
                    "scheduled_end must be strictly after scheduled_start")
    for other in db["packing_runs"].values():
        if other["status"] == "SCHEDULED" and other["line_code"] == line_code and \
                _windows_overlap(scheduled_start, scheduled_end,
                                 other["scheduled_start"], other["scheduled_end"]):
            raise_error(ERR_LINE_SCHEDULE_OVERLAP,
                        "window overlaps another SCHEDULED run on the same line_code")
    block = db["blocks"][lot["block_id"]]
    deadline = add_days(lot["received_at"], block["storage_life_days"])
    if CLOCK.now() > parse_dt(deadline):
        raise_error(ERR_LOT_STORAGE_LIFE_EXCEEDED,
                    "current logical clock is past lot.received_at + storage_life_days")
    # Tier 11 business constraints: weight balance, then color minimum.
    if input_weight_lbs > lot["weight_balance_lbs"]:
        raise_error(ERR_WEIGHT_BALANCE_EXCEEDED,
                    "input_weight_lbs exceeds the lot's weight_balance_lbs")
    if lot["avg_color_pct"] < spec["color_min_pct"]:
        raise_error(ERR_COLOR_BELOW_SPEC,
                    "lot.avg_color_pct is below the spec's color_min_pct")
    rec = new_record("packing_runs", {
        "lot_id": lot_id,
        "spec_id": spec_id,
        "pool_id": pool_id,
        "line_code": line_code,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "input_weight_lbs": input_weight_lbs,
        "cartons_produced": None,
        "packed_weight_lbs": None,
        "cull_weight_lbs": None,
        "juice_weight_lbs": None,
        "packout_pct": None,
        "status": "SCHEDULED",
    })
    return success_object(public(rec), status=201)


@bp.get("/packing-runs/<runId>")
def get_run(runId):
    authorized(list(ALL_ROLES))
    run = require_path_resource("packing_runs", runId)
    return success_object(public(run))


@bp.get("/packing-runs")
def list_runs():
    authorized(list(ALL_ROLES))
    items = sorted_items("packing_runs")
    f_lot = request.args.get("lot_id")
    f_spec = request.args.get("spec_id")
    f_pool = request.args.get("pool_id")
    f_status = request.args.get("status")
    if f_lot is not None:
        items = [r for r in items if r["lot_id"] == f_lot]
    if f_spec is not None:
        items = [r for r in items if r["spec_id"] == f_spec]
    if f_pool is not None:
        items = [r for r in items if r["pool_id"] == f_pool]
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    return list_response(items)


@bp.post("/packing-runs/<runId>/complete")
def complete_run(runId):
    authorized(["Admin", "PackingSupervisor"])
    run = require_path_resource("packing_runs", runId)
    body = get_body()
    cartons_produced = req_int(body, "cartons_produced", non_negative=True)
    packed = req_num(body, "packed_weight_lbs", non_negative=True)
    cull = req_num(body, "cull_weight_lbs", non_negative=True)
    juice = req_num(body, "juice_weight_lbs", non_negative=True)
    pool = db["pools"][run["pool_id"]]
    # Tier 8 state gates, fixed order: pool before run.
    if pool["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_POOL_INVALID_STATE,
                    f"completion requires an OPEN or REOPENED pool, found {pool['status']}")
    if run["status"] != "SCHEDULED":
        raise_error(ERR_RUN_INVALID_STATE,
                    f"completion requires a SCHEDULED run, found {run['status']}")
    # Tier 11: exact three-way weight split.
    if packed + cull + juice != run["input_weight_lbs"]:
        raise_error(ERR_RUN_WEIGHT_MISMATCH,
                    "packed + cull + juice must equal input_weight_lbs exactly")
    run["cartons_produced"] = cartons_produced
    run["packed_weight_lbs"] = packed
    run["cull_weight_lbs"] = cull
    run["juice_weight_lbs"] = juice
    total_out = packed + cull + juice
    run["packout_pct"] = round_half_up(Decimal("100") * packed / total_out, 1)
    run["status"] = "COMPLETED"
    touch(run)
    # Cascade hop 1 (run -> lot).
    lot = db["lots"][run["lot_id"]]
    lot["weight_balance_lbs"] = lot["weight_balance_lbs"] - run["input_weight_lbs"]
    recompute_lot_actual_packout(lot)
    if lot["weight_balance_lbs"] == 0 and lot["status"] == "RELEASED":
        lot["status"] = "PACKED"
    touch(lot)
    # Cascade hop 1 (run -> pool).
    pool["total_packed_cartons"] += cartons_produced
    recompute_pool_totals(pool)
    touch(pool)
    # Cascade hop 2 (pool -> settlement): auto-create ACCRUING if absent.
    settlement = get_or_create_settlement(lot["grower_id"], pool["id"])
    recompute_attributed_cartons(settlement)
    return success_object(public(run))


@bp.post("/packing-runs/<runId>/cancel")
def cancel_run(runId):
    authorized(["Admin", "PackingSupervisor"])
    run = require_path_resource("packing_runs", runId)
    get_body()
    if run["status"] != "SCHEDULED":
        raise_error(ERR_RUN_INVALID_STATE,
                    f"cancel requires a SCHEDULED run, found {run['status']}")
    run["status"] = "CANCELLED"
    touch(run)
    return success_object(public(run))


@bp.post("/packing-runs/<runId>/void")
def void_run(runId):
    authorized(["Admin", "PackingSupervisor"])
    run = require_path_resource("packing_runs", runId)
    get_body()
    pool = db["pools"][run["pool_id"]]
    # Tier 8 state gates, fixed order: pool before run.
    if pool["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_POOL_INVALID_STATE,
                    f"void requires an OPEN or REOPENED pool, found {pool['status']}")
    if run["status"] != "COMPLETED":
        raise_error(ERR_RUN_INVALID_STATE,
                    f"void requires a COMPLETED run, found {run['status']}")
    run["status"] = "VOIDED"
    run["packout_pct"] = None
    touch(run)
    # Compensation: credit the lot back, recompute, reopen a PACKED lot.
    lot = db["lots"][run["lot_id"]]
    lot["weight_balance_lbs"] = lot["weight_balance_lbs"] + run["input_weight_lbs"]
    recompute_lot_actual_packout(lot)
    if lot["status"] == "PACKED" and lot["weight_balance_lbs"] > 0:
        lot["status"] = "RELEASED"
    touch(lot)
    # Pool totals and estimated price.
    pool["total_packed_cartons"] -= run["cartons_produced"]
    recompute_pool_totals(pool)
    touch(pool)
    # Settlement attribution.
    settlement = get_or_create_settlement(lot["grower_id"], pool["id"])
    recompute_attributed_cartons(settlement)
    return success_object(public(run))
