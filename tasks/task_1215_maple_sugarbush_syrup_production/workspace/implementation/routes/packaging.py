"""PackagingRun endpoints."""

from decimal import Decimal

from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_int, as_str,
                  as_enum, d, round2, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_LOT_NOT_GRADED, ERR_GRADE_NOT_RETAIL_ELIGIBLE,
                    ERR_INSUFFICIENT_UNPACKAGED)
from services import core

bp = Blueprint("packaging", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}

RETAIL_TYPES = {"RETAIL_QUART", "RETAIL_PINT"}
RETAIL_GRADES = {"GOLDEN", "AMBER"}


def get_pr_or_404(pid):
    p = db.packaging_runs.get(pid)
    if not p:
        raise_err(ERR_NOT_FOUND, f"packaging run {pid} not found")
    return p


@bp.post("/sugarhouse/packaging-runs")
def create_packaging():
    caller = authenticate()
    require_role(caller, MGR)
    data = body_json()
    check_unknown_fields(data, {"syrup_lot_id", "container_type", "units_planned"})
    require_fields(data, ["syrup_lot_id", "container_type", "units_planned"])
    syrup_lot_id = as_str(data["syrup_lot_id"], "syrup_lot_id")
    container_type = as_enum(data["container_type"], "container_type",
                             set(core.CONTAINER_GALLONS.keys()))
    units_planned = as_int(data["units_planned"], "units_planned", minimum=1)

    lot = db.syrup_lots.get(syrup_lot_id)
    if not lot:
        raise_err(ERR_NOT_FOUND, f"syrup lot {syrup_lot_id} not found")
    if lot["status"] != "GRADED":
        raise_err(ERR_LOT_NOT_GRADED, f"lot is {lot['status']}, expected GRADED")
    if container_type in RETAIL_TYPES and lot["grade"] not in RETAIL_GRADES:
        raise_err(ERR_GRADE_NOT_RETAIL_ELIGIBLE,
                  f"retail packaging requires GOLDEN or AMBER, lot is {lot['grade']}")
    planned_volume = d(units_planned) * core.CONTAINER_GALLONS[container_type]
    if planned_volume > d(lot["unpackaged_gallons"]):
        raise_err(ERR_INSUFFICIENT_UNPACKAGED,
                  "planned volume exceeds lot's unpackaged_gallons")
    pr = core.new_packaging_run(syrup_lot_id, container_type, units_planned)
    db.packaging_runs[pr["id"]] = pr
    return success_object(core.ser_packaging_run(pr), status=201)


@bp.get("/sugarhouse/packaging-runs/<pid>")
def get_packaging(pid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    pr = get_pr_or_404(pid)
    return success_object(core.ser_packaging_run(pr))


@bp.get("/sugarhouse/packaging-runs")
def list_packaging():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    syrup_lot_id = request.args.get("syrup_lot_id")
    status = request.args.get("status")
    rows = list(db.packaging_runs.values())
    if syrup_lot_id is not None:
        rows = [r for r in rows if r["syrup_lot_id"] == syrup_lot_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_packaging_run(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/packaging-runs/<pid>/fill")
def fill_packaging(pid):
    caller = authenticate()
    require_role(caller, MGR)
    pr = get_pr_or_404(pid)
    if pr["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, f"packaging run is {pr['status']}, expected PLANNED")
    lot = db.syrup_lots.get(pr["syrup_lot_id"])
    if not lot:
        raise_err(ERR_NOT_FOUND, f"syrup lot {pr['syrup_lot_id']} not found")
    if lot["status"] != "GRADED":
        raise_err(ERR_LOT_NOT_GRADED, f"lot is {lot['status']}, expected GRADED")
    planned_volume = d(pr["units_planned"]) * core.CONTAINER_GALLONS[pr["container_type"]]
    if planned_volume > d(lot["unpackaged_gallons"]):
        raise_err(ERR_INSUFFICIENT_UNPACKAGED,
                  "planned volume exceeds lot's unpackaged_gallons")
    pr["units_filled"] = pr["units_planned"]
    pr["filled_gallons"] = round2(planned_volume)
    pr["status"] = "FILLED"
    core.bump(pr)
    lot["unpackaged_gallons"] = round2(d(lot["unpackaged_gallons"]) - planned_volume)
    core.touch(lot)
    if lot["unpackaged_gallons"] == Decimal("0"):
        lot["status"] = "EXHAUSTED"
        core.bump(lot)
    return success_object(core.ser_packaging_run(pr))


@bp.post("/sugarhouse/packaging-runs/<pid>/cancel")
def cancel_packaging(pid):
    caller = authenticate()
    require_role(caller, MGR)
    pr = get_pr_or_404(pid)
    if pr["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, f"packaging run is {pr['status']}, expected PLANNED")
    pr["status"] = "CANCELLED"
    core.bump(pr)
    return success_object(core.ser_packaging_run(pr))
