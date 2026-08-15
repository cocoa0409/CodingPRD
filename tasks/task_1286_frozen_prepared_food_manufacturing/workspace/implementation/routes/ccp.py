"""Critical control point checks (PRD §3.6)."""

from flask import request

import services as svc
from db import STORE, logical_now, new_record
from errors import ApiError
from middleware import PLANT_ROLES, endpoint
from response import list_response, ok_object
from routes import bp
from serializers import check_out
from util import CHECK_TYPES, as_bool, as_enum, body_dict, opt_present, req_present, as_decimal


@bp.route("/plant/production-batches/<batchId>/ccp-checks", methods=["POST"])
@endpoint({"QATechnician"})
def create_check(user_id, role, batchId):
    body = body_dict(request.get_json(silent=True))
    check_type = as_enum(req_present(body, "check_type"), "check_type", CHECK_TYPES)
    detected = as_bool(req_present(body, "test_piece_detected"), "test_piece_detected")
    measured = opt_present(body, "measured_size_mm")
    if measured is not None:
        measured = as_decimal(measured, "measured_size_mm")

    batch = svc.require_record("batches", batchId, "ProductionBatch")
    if batch["status"] not in ("FROZEN", "PACKED", "COMPLETED", "ON_HOLD"):
        raise ApiError(
            "ERR_BATCH_STATE",
            "CCP checks require the batch to be FROZEN, PACKED, COMPLETED or ON_HOLD",
        )

    rec = new_record(common=False)  # append-only: id + created_at, no updated_at/version
    rec.update(
        batch_id=batch["id"],
        check_type=check_type,
        test_piece_detected=detected,
        measured_size_mm=measured,
        result="PASS" if detected else "FAIL",
        performed_by_user_id=user_id,
        performed_at=logical_now(),
    )
    STORE["ccp_checks"][rec["id"]] = rec

    if rec["result"] == "FAIL":
        svc.ccp_fail_cascade(batch, check_type)
    return ok_object(check_out(rec), 201)


@bp.route("/plant/ccp-checks/<checkId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_check(user_id, role, checkId):
    return ok_object(check_out(svc.require_record("ccp_checks", checkId, "CCPCheck")))


@bp.route("/plant/ccp-checks", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_checks(user_id, role):
    batch_id = request.args.get("batch_id")
    check_type = request.args.get("check_type")
    recs = list(STORE["ccp_checks"].values())
    if batch_id is not None:
        recs = [c for c in recs if c["batch_id"] == batch_id]
    if check_type is not None:
        recs = [c for c in recs if c["check_type"] == check_type]
    return list_response(recs, check_out)


@bp.route("/plant/production-batches/<batchId>/ccp-checks", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_batch_checks(user_id, role, batchId):
    svc.require_record("batches", batchId, "ProductionBatch")
    return list_response(svc.checks_of_batch(batchId), check_out)
