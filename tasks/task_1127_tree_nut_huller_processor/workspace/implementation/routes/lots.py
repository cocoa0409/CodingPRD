"""Field lots, routing/disposition, and laboratory tests (PRD §3.2, §3.4)."""
from flask import Blueprint, request

import db
import response
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_GROWER_NOT_FOUND, ERR_LOT_NOT_FOUND,
    ERR_NOT_FOUND, ERR_AFLATOXIN_UNRESOLVED, ERR_DRYING_REQUIRED,
    ERR_ALREADY_TERMINAL,
)
from middleware import authenticate, require_roles, forbid_unless, body
from validate import (
    req_string, req_number, req_enum, opt_enum_filter, check_range, check_state,
    LOT_STATUSES, LOT_TERMINAL, TEST_TYPES, SIZE_SPECS,
)
from services import calc, cascade
from services.serialize import lot_out, lab_test_out

bp = Blueprint("lots", __name__)

LOT_READ_ROLES = ["PlantAdmin", "IntakeOperator", "LabTechnician", "PlantOperator", "Grower"]
LAB_READ_ROLES = ["PlantAdmin", "LabTechnician", "IntakeOperator", "PlantOperator"]


def _get_lot_or_404(rid):
    lot = db.store.lots.get(rid)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found: %s" % rid)
    return lot


# ------------------------------------------------------------------- lots

@bp.route("/lots", methods=["POST"])
def create_lot():
    auth = authenticate()
    require_roles(auth, ["IntakeOperator"])
    b = body()
    grower_id = b.get("grower_id")
    if grower_id is not None and grower_id not in db.store.growers:
        raise ApiError(ERR_GROWER_NOT_FOUND, 404, "Grower not found: %s" % grower_id)
    grower_id = req_string(b, "grower_id")
    variety = req_string(b, "variety")
    gross = check_range(req_number(b, "gross_weight_lbs"), "gross_weight_lbs", gt=0)
    rec = db.stamp({
        "id": db.new_id(),
        "grower_id": grower_id,
        "variety": variety,
        "gross_weight_lbs": calc.round2(gross),
        "status": "RECEIVED",
        "intake_moisture_pct": None,
        "intake_kernel_pct": None,
        "intake_fm_pct": None,
        "aflatoxin_ppb": None,
        "edible_kernel_pct": None,
        "size_spec": None,
        "post_dry_moisture_pct": None,
        "provisional_kernel_lbs": None,
        "graded_kernel_weight_lbs": None,
    })
    db.store.lots[rec["id"]] = rec
    return response.ok(lot_out(rec), 201)


@bp.route("/lots", methods=["GET"])
def list_lots():
    auth = authenticate()
    require_roles(auth, LOT_READ_ROLES)
    status = opt_enum_filter(request.args, "status", LOT_STATUSES)
    grower_id = request.args.get("grower_id")
    items = list(db.store.lots.values())
    if auth.is_grower:
        items = [l for l in items if l["grower_id"] == auth.user_id]
    elif grower_id is not None:
        items = [l for l in items if l["grower_id"] == grower_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return response.paginate(items, lot_out)


@bp.route("/lots/<rid>", methods=["GET"])
def get_lot(rid):
    auth = authenticate()
    require_roles(auth, LOT_READ_ROLES)
    lot = _get_lot_or_404(rid)
    if auth.is_grower:
        forbid_unless(lot["grower_id"] == auth.user_id)
    return response.ok(lot_out(lot))


@bp.route("/lots/<rid>/route", methods=["POST"])
def route_lot(rid):
    auth = authenticate()
    require_roles(auth, ["IntakeOperator"])
    lot = _get_lot_or_404(rid)
    b = body()
    route = req_enum(b, "route", ("IN_SHELL", "KERNEL"))
    # state gate (6)
    check_state(lot, ("GRADED",), LOT_TERMINAL, "FieldLot")
    # safety gate (7): latest AFLATOXIN test must exist with PASS verdict
    latest = calc.latest_test(lot["id"], "AFLATOXIN")
    if latest is None or latest["aflatoxin_verdict"] != "PASS":
        raise ApiError(ERR_AFLATOXIN_UNRESOLVED, 422,
                       "Routing requires a recorded AFLATOXIN test with verdict PASS")
    # physical gate (9): drying prerequisite for moist lots
    if lot["intake_moisture_pct"] is not None and \
            calc.D(lot["intake_moisture_pct"]) > calc.MOISTURE_STD_PCT:
        dried = any(x["lot_id"] == lot["id"] and x["status"] == "COMPLETED"
                    for x in db.store.batches.values())
        if not dried:
            raise ApiError(ERR_DRYING_REQUIRED, 422,
                           "Lot requires drying before routing (intake moisture above standard)")
    lot["status"] = "ROUTED_IN_SHELL" if route == "IN_SHELL" else "ROUTED_KERNEL"
    db.touch(lot)
    return response.ok(lot_out(lot))


@bp.route("/lots/<rid>/resample", methods=["POST"])
def resample_lot(rid):
    auth = authenticate()
    require_roles(auth, ["IntakeOperator"])
    lot = _get_lot_or_404(rid)
    check_state(lot, ("REJECTED",), LOT_TERMINAL, "FieldLot")
    lot["status"] = "SAMPLED"
    lot["aflatoxin_ppb"] = None
    db.touch(lot)
    return response.ok(lot_out(lot))


@bp.route("/lots/<rid>/dispose", methods=["POST"])
def dispose_lot(rid):
    auth = authenticate()
    require_roles(auth, ["IntakeOperator"])
    lot = _get_lot_or_404(rid)
    check_state(lot, ("REJECTED",), LOT_TERMINAL, "FieldLot")
    lot["status"] = "DISPOSED"
    db.touch(lot)
    cascade.dispose_cascade(lot)
    return response.ok(lot_out(lot))


# --------------------------------------------------------------- lab tests

_MEASURE_FIELDS = ("moisture_pct", "kernel_pct", "foreign_material_pct",
                   "aflatoxin_ppb", "edible_kernel_pct", "size_spec")


def _forbid(body, fields):
    for f in fields:
        if f in body and body[f] is not None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Field %s is forbidden for this test_type" % f)


@bp.route("/lab-tests", methods=["POST"])
def create_lab_test():
    auth = authenticate()
    require_roles(auth, ["LabTechnician"])
    b = body()
    lot_id = b.get("lot_id")
    if lot_id is not None and lot_id not in db.store.lots:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found: %s" % lot_id)
    # shape (5)
    lot_id = req_string(b, "lot_id")
    lot = db.store.lots[lot_id]
    test_type = req_enum(b, "test_type", TEST_TYPES)
    rec = {
        "id": db.new_id(),
        "lot_id": lot_id,
        "test_type": test_type,
        "moisture_pct": None,
        "kernel_pct": None,
        "foreign_material_pct": None,
        "aflatoxin_ppb": None,
        "edible_kernel_pct": None,
        "size_spec": None,
        "aflatoxin_verdict": None,
    }
    if test_type == "MOISTURE_KERNEL":
        _forbid(b, ("aflatoxin_ppb", "edible_kernel_pct", "size_spec"))
        rec["moisture_pct"] = check_range(req_number(b, "moisture_pct"), "moisture_pct", gt=0, lt=100)
        rec["kernel_pct"] = check_range(req_number(b, "kernel_pct"), "kernel_pct", gt=0, le=1)
        rec["foreign_material_pct"] = check_range(req_number(b, "foreign_material_pct"),
                                                  "foreign_material_pct", ge=0, lt=1)
    elif test_type == "AFLATOXIN":
        _forbid(b, ("moisture_pct", "kernel_pct", "foreign_material_pct",
                    "edible_kernel_pct", "size_spec"))
        rec["aflatoxin_ppb"] = check_range(req_number(b, "aflatoxin_ppb"), "aflatoxin_ppb", ge=0)
        rec["aflatoxin_verdict"] = calc.aflatoxin_verdict(rec["aflatoxin_ppb"])
    else:  # KERNEL_GRADE
        _forbid(b, ("moisture_pct", "kernel_pct", "foreign_material_pct", "aflatoxin_ppb"))
        rec["edible_kernel_pct"] = check_range(req_number(b, "edible_kernel_pct"),
                                               "edible_kernel_pct", gt=0, le=1)
        rec["size_spec"] = req_enum(b, "size_spec", SIZE_SPECS)
    # state gate (6)
    if test_type == "KERNEL_GRADE":
        check_state(lot, ("PROCESSED",), LOT_TERMINAL, "FieldLot")
    else:
        if lot["status"] in LOT_TERMINAL:
            raise ApiError(ERR_ALREADY_TERMINAL, 409,
                           "Lot is already in terminal state %s" % lot["status"])
    rec["recorded_at"] = db.now_ts()
    db.stamp(rec)
    db.store.lab_tests[rec["id"]] = rec
    # side effects
    if test_type == "MOISTURE_KERNEL":
        lot["intake_moisture_pct"] = rec["moisture_pct"]
        lot["intake_kernel_pct"] = rec["kernel_pct"]
        lot["intake_fm_pct"] = rec["foreign_material_pct"]
        lot["provisional_kernel_lbs"] = calc.provisional_kernel_lbs(lot)
        if lot["status"] == "RECEIVED":
            lot["status"] = "SAMPLED"
        db.touch(lot)
    elif test_type == "AFLATOXIN":
        lot["aflatoxin_ppb"] = rec["aflatoxin_ppb"]
        if rec["aflatoxin_verdict"] == "PASS" and lot["status"] == "SAMPLED":
            lot["status"] = "GRADED"
            db.touch(lot)
            cascade.aflatoxin_pass_compensation(lot)
        elif rec["aflatoxin_verdict"] == "FAIL" and lot["status"] in (
                "SAMPLED", "GRADED", "ROUTED_IN_SHELL", "ROUTED_KERNEL",
                "PROCESSING", "PROCESSED"):
            lot["status"] = "REJECTED"
            db.touch(lot)
            cascade.aflatoxin_fail_cascade(lot)
        else:
            db.touch(lot)
    else:  # KERNEL_GRADE
        lot["edible_kernel_pct"] = rec["edible_kernel_pct"]
        lot["size_spec"] = rec["size_spec"]
        calc.recompute_graded_kernel_weight(lot)
        db.touch(lot)
    return response.ok(lab_test_out(rec), 201)


@bp.route("/lab-tests", methods=["GET"])
def list_lab_tests():
    auth = authenticate()
    require_roles(auth, LAB_READ_ROLES)
    lot_id = request.args.get("lot_id")
    test_type = opt_enum_filter(request.args, "test_type", TEST_TYPES)
    items = list(db.store.lab_tests.values())
    if lot_id is not None:
        items = [t for t in items if t["lot_id"] == lot_id]
    if test_type is not None:
        items = [t for t in items if t["test_type"] == test_type]
    return response.paginate(items, lab_test_out)


@bp.route("/lab-tests/<rid>", methods=["GET"])
def get_lab_test(rid):
    auth = authenticate()
    require_roles(auth, LAB_READ_ROLES)
    rec = db.store.lab_tests.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Lab test not found: %s" % rid)
    return response.ok(lab_test_out(rec))
