"""LumberPackage list/get and GradeInspection record/list."""
from flask import Blueprint, request

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    INSPECTION_ACTIONS,
    STAMP_GRADES,
    get_package,
    ledger_stamp,
    order_packages,
    recompute_certified_if_complete,
    recompute_order_totals,
    ser_inspection,
    ser_package,
    touch,
)
from util import as_enum, body, pagination_args, required

bp = Blueprint("lumber_packages", __name__)


@bp.get("/api/lumber-packages")
def list_packages():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = list(DB["lumber_packages"].values())
    if "status" in request.args:
        v = request.args.get("status")
        items = [p for p in items if p["status"] == v]
    if "species" in request.args:
        v = request.args.get("species")
        items = [p for p in items if p["species"] == v]
    if "grade" in request.args:
        v = request.args.get("grade")
        items = [p for p in items if p["stamped_grade"] == v]
    if "sales_order_id" in request.args:
        v = request.args.get("sales_order_id")
        items = [p for p in items if p["sales_order_id"] == v]
    if "kiln_charge_id" in request.args:
        v = request.args.get("kiln_charge_id")
        items = [p for p in items if p["kiln_charge_id"] == v]
    if "sawing_run_id" in request.args:
        v = request.args.get("sawing_run_id")
        items = [p for p in items if p["sawing_run_id"] == v]
    items.sort(key=lambda p: p["_seq"])  # created_at ascending, insertion order
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_package(p) for p in page], total, limit, offset)


@bp.get("/api/lumber-packages/<pid>")
def get_one_package(pid):
    auth(ALL_ROLES)
    return ok(ser_package(get_package(pid)))


@bp.post("/api/lumber-packages/<pid>/grade-inspections")
def create_inspection(pid):
    auth(["Grader"])
    pkg = get_package(pid)
    data = body()
    inspector_grade = as_enum(
        required(data, "inspector_grade"), "inspector_grade", STAMP_GRADES
    )
    action = as_enum(required(data, "action"), "action", INSPECTION_ACTIONS)
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "note must be a string")

    if action == "STAMP":
        if pkg["status"] != "DRY":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "STAMP requires a DRY package"
            )
        pkg["stamped_grade"] = inspector_grade
        pkg["stamped_at"] = now_iso()
        pkg["status"] = "STAMPED"
        touch(pkg)
        # Certified-recovery trigger: recompute when this stamp completes the
        # run's stamped set (every package STAMPED/ALLOCATED/SHIPPED).
        run = DB["sawing_runs"].get(pkg["sawing_run_id"])
        if run is not None:
            recompute_certified_if_complete(run)
    else:  # RESTAMP
        if pkg["status"] not in ("STAMPED", "ALLOCATED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "RESTAMP requires a STAMPED or ALLOCATED package",
            )
        if pkg["status"] == "STAMPED":
            pkg["stamped_grade"] = inspector_grade
            pkg["stamped_at"] = now_iso()
            touch(pkg)
        else:  # ALLOCATED: outcome splits on the holding order's grade
            order = DB["sales_orders"].get(pkg["sales_order_id"])
            if order is not None and inspector_grade == order["grade"]:
                # Same grade: no release; the row is still appended.
                touch(pkg)
            else:
                # Release cascade: downfall -> back to STAMPED, order recomputes,
                # an order left with zero allocated packages falls back to PLACED.
                pkg["stamped_grade"] = inspector_grade
                pkg["stamped_at"] = now_iso()
                pkg["sales_order_id"] = None
                pkg["status"] = "STAMPED"
                touch(pkg)
                if order is not None:
                    recompute_order_totals(order)
                    if not order_packages(order) and order["status"] == "ALLOCATED":
                        order["status"] = "PLACED"
                    touch(order)

    insp = {
        "id": new_id(),
        "package_id": pkg["id"],
        "inspector_grade": inspector_grade,
        "action": action,
        "note": note,
    }
    ledger_stamp(insp)
    DB["grade_inspections"][insp["id"]] = insp
    return ok(ser_inspection(insp), 201)


@bp.get("/api/lumber-packages/<pid>/grade-inspections")
def list_inspections(pid):
    auth(ALL_ROLES)
    pkg = get_package(pid)
    limit, offset = pagination_args()
    items = [
        i for i in DB["grade_inspections"].values() if i["package_id"] == pkg["id"]
    ]
    items.sort(key=lambda i: i["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_inspection(i) for i in page], total, limit, offset)
