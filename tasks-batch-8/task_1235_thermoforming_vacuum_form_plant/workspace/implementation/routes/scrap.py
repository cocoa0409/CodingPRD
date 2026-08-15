"""ScrapRecord endpoints (PRD §3.2)."""

from flask import request

from db import STORE, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_scrap
from services import get_batch, get_scrap, batch_recompute
from util import as_enum, as_string, body_dict, req_present

from routes import bp


@bp.route("/scrap-records", methods=["GET"])
@endpoint(ANY_ROLE)
def list_scrap(user_id, role):
    items = list(STORE["scrap_records"].values())
    run_id = request.args.get("forming_run_id")
    if run_id is not None:
        items = [s for s in items if s["forming_run_id"] == run_id]
    batch_id = request.args.get("regrind_batch_id")
    if batch_id is not None:
        items = [s for s in items if s["regrind_batch_id"] == batch_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_scrap)


@bp.route("/scrap-records/<scrapId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_scrap(user_id, role, scrapId):
    return ok_object(ser_scrap(get_scrap(scrapId)))


@bp.route("/scrap-records/<scrapId>/certify", methods=["POST"])
@endpoint({"MaterialsPlanner"})
def certify_scrap(user_id, role, scrapId):
    body = body_dict(request.get_json(silent=True))
    regrind_batch_id = as_string(req_present(body, "regrind_batch_id"), "regrind_batch_id")
    decision = as_enum(req_present(body, "decision"), "decision", {"CERTIFY", "REJECT"})

    # p4 existence (path id first, then body id)
    scrap = get_scrap(scrapId)
    batch = get_batch(regrind_batch_id)
    # p6 state: record must be PENDING
    if scrap["status"] != "PENDING":
        raise ApiError("ERR_INVALID_SCRAP_STATE", "Scrap certify requires status PENDING")

    if decision == "REJECT":
        scrap["status"] = "REJECTED"
        return ok_object(ser_scrap(scrap))

    # CERTIFY: batch must be ACCEPTING, resin must match
    if batch["status"] != "ACCEPTING":
        raise ApiError("ERR_INVALID_BATCH_STATE", "Scrap certify requires an ACCEPTING batch")
    if batch["resin_type"] != scrap["resin_type"]:
        raise ApiError("ERR_RESIN_MISMATCH", "Batch resin_type differs from the scrap's")

    scrap["regrind_batch_id"] = batch["id"]
    scrap["status"] = "CERTIFIED"
    batch["accumulated_kg"] += scrap["weight_kg"]
    batch_recompute(batch)
    bump(batch)
    # Auto-advance at target fill
    if batch["status"] == "ACCEPTING" and batch["accumulated_kg"] >= batch["target_kg"]:
        batch["status"] = "PENDING_CERT"
        bump(batch)
    return ok_object(ser_scrap(scrap))
