"""Control runs (PRD 3.4)."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import valid
from middleware import route
from services import calc, derive

bp = Blueprint("qc", __name__)

ALL_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor",
             "Operator")


@route(bp, "/qc-runs", ["POST"], ["Operator", "QualityCoordinator"])
def record_run(user_id, role):
    payload = valid.body()
    # Ranks 11, 12, 13 in precedence order.
    operator = valid.resolve_body("operators", payload, "operator_id")
    device = valid.resolve_body("devices", payload, "device_id")
    lot = valid.resolve_body("lots", payload, "reagent_lot_id")
    # Rank 20.
    control_level = valid.req_enum(payload, "control_level",
                                   ("LEVEL_1", "LEVEL_2"))
    measured_value = valid.req_num(payload, "measured_value")
    performed_at = valid.opt_datetime(payload, "performed_at")
    # Rank 43.
    if lot["verification_status"] in ("QUARANTINED", "DISCARDED", "REJECTED"):
        raise errors.ApiError("ERR_LOT_QUARANTINED", 409)
    # Rank 50 — a locked instrument may still run controls; a retired one may not.
    if device["status"] not in ("ACTIVE", "QC_LOCKED"):
        raise errors.invalid_state("A RETIRED instrument cannot run controls.")
    if lot["verification_status"] not in ("UNVERIFIED", "VERIFIED"):
        raise errors.invalid_state("The reagent lot is not usable.")
    # Rank 52.
    if operator["access_status"] != "ACTIVE":
        raise errors.ApiError("ERR_OPERATOR_ACCESS_LOCKED", 422)
    # Rank 53.
    if operator["competency_status"] not in ("PROVISIONAL", "COMPETENT"):
        raise errors.ApiError("ERR_OPERATOR_COMPETENCY_LAPSED", 422)
    # Rank 54.
    if clock.today() > clock.parse_date(lot["expiration_date"]):
        raise errors.ApiError("ERR_REAGENT_LOT_EXPIRED", 422)
    # Rank 59.
    if lot["device_model"] != device["device_model"]:
        raise errors.ApiError("ERR_LOT_DEVICE_MODEL_MISMATCH", 422)
    # Rank 60.
    if (operator["site_id"] != device["site_id"]
            or lot["site_id"] != device["site_id"]):
        raise errors.ApiError("ERR_CROSS_SITE_REFERENCE", 422)

    if control_level == "LEVEL_1":
        expected_min = lot["control_min_level_1"]
        expected_max = lot["control_max_level_1"]
    else:
        expected_min = lot["control_min_level_2"]
        expected_max = lot["control_max_level_2"]
    result = calc.qc_run_result(measured_value, expected_min, expected_max)
    locks = result == "FAIL" and device["status"] == "ACTIVE"

    row = db.insert("qc_runs", {
        "device_id": device["id"],
        "reagent_lot_id": lot["id"],
        "operator_id": operator["id"],
        "control_level": control_level,
        "measured_value": measured_value,
        "performed_at": clock.iso(performed_at) if performed_at else clock.now_iso(),
        "expected_min": expected_min,
        "expected_max": expected_max,
        "result": result,
        "locked_device": locks,
    }, common=False)

    if locks:
        derive.cascade_qc_failure(device, row)
    derive.recompute_device_rates(device)
    derive.recompute_site(derive.site_of_device(device))
    return response.object_response(serializers.dump("qc_runs", row), 201)


@route(bp, "/qc-runs/<run_id>", ["GET"], ALL_ROLES)
def read_run(user_id, role, run_id):
    row = valid.resolve("qc_runs", run_id)
    return response.object_response(serializers.dump("qc_runs", row))


@route(bp, "/qc-runs", ["GET"], ALL_ROLES)
def list_runs(user_id, role):
    limit, offset = valid.pagination()
    device_id = valid.arg("device_id")
    lot_id = valid.arg("reagent_lot_id")
    operator_id = valid.arg("operator_id")
    result = valid.arg("result")
    items = [r for r in db.rows("qc_runs")
             if (device_id is None or r["device_id"] == device_id)
             and (lot_id is None or r["reagent_lot_id"] == lot_id)
             and (operator_id is None or r["operator_id"] == operator_id)
             and (result is None or r["result"] == result)]
    return response.list_response(
        serializers.dump_many("qc_runs", valid.page(items, limit, offset)),
        limit, offset, len(items))
