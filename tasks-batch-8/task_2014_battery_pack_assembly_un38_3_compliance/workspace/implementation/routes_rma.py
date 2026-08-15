"""ReturnAuthorization lifecycle and safe discharge (§3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from domain import (
    new_row, touch, sorted_rows, get_program, get_rma, require_program_open,
    raise_if_pack_under_recall, ser_rma, soc_band_after_discharge,
    REASON_CODES, SAFE_DISCHARGE_MAX_PERCENT,
)
from errors import (
    err_pack_not_found, err_cross_program, err_rma_not_requested,
    err_pack_not_delivered, err_sod_rma_approve, err_target_soc_too_high,
    err_rma_not_approved, err_rma_not_discharge_pending,
    err_discharge_target_not_met, err_rma_not_discharged, err_rma_pack_mismatch,
    err_rma_not_received, err_invalid_request,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, as_str, as_decimal, as_enum, round_half_up

bp = Blueprint("rmas", __name__)


def _soc_field(body, name):
    v = as_decimal(req_field(body, name), name)
    if v < 0 or v > 100:
        raise err_invalid_request("%s must be within 0..100" % name)
    return round_half_up(v, 1)


@bp.route("/integration-programs/<programId>/return-authorizations", methods=["POST"])
@require_roles("CustomerService")
def create_rma(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    pack_id = as_str(req_field(body, "battery_pack_id"), "battery_pack_id")
    reason_code = as_enum(req_field(body, "reason_code"), "reason_code", REASON_CODES)
    target_soc = _soc_field(body, "target_soc_percent")

    pack = db.packs.get(pack_id)
    if pack is None:
        raise err_pack_not_found()
    require_program_open(program)
    # priority 12: cross-program referential integrity
    if pack["program_id"] != program["id"]:
        raise err_cross_program()

    row = new_row()
    row.update(
        program_id=program["id"],
        battery_pack_id=pack["id"],
        reason_code=reason_code,
        requested_by_id=actor.user_id,
        approved_by_id=None,
        target_soc_percent=target_soc,
        actual_soc_after_discharge=None,
        status="REQUESTED",
    )
    db.rmas[row["id"]] = row
    return success_created(ser_rma(row))


@bp.route("/integration-programs/<programId>/return-authorizations", methods=["GET"])
@require_roles()
def list_rmas(actor, programId):
    get_program(programId)
    rows = [r for r in db.rmas.values() if r["program_id"] == programId]
    v = request.args.get("battery_pack_id")
    if v is not None:
        rows = [r for r in rows if r["battery_pack_id"] == v]
    return success_list(sorted_rows(rows), ser_rma)


@bp.route("/integration-programs/<programId>/return-authorizations/<rmaId>", methods=["GET"])
@require_roles()
def get_one_rma(actor, programId, rmaId):
    get_program(programId)
    return success_object(ser_rma(get_rma(programId, rmaId)))


@bp.route("/integration-programs/<programId>/return-authorizations/<rmaId>/approve", methods=["POST"])
@require_roles("SafetyOfficer")
def approve_rma(actor, programId, rmaId):
    program = get_program(programId)
    rma = get_rma(programId, rmaId)
    get_body()
    require_program_open(program)
    if rma["status"] != "REQUESTED":
        raise err_rma_not_requested()
    pack = db.packs[rma["battery_pack_id"]]
    if pack["logistics_status"] != "DELIVERED":
        raise err_pack_not_delivered()
    # priority 6: segregation of duties — approver != requester
    if actor.user_id == rma["requested_by_id"]:
        raise err_sod_rma_approve()
    # priority 11: safe-discharge ceiling
    if rma["target_soc_percent"] > SAFE_DISCHARGE_MAX_PERCENT:
        raise err_target_soc_too_high()

    rma["status"] = "APPROVED"
    rma["approved_by_id"] = actor.user_id
    touch(rma)
    pack["disposition"] = "RETURN_PENDING"
    touch(pack)
    return success_object(ser_rma(rma))


@bp.route("/integration-programs/<programId>/return-authorizations/<rmaId>/deny", methods=["POST"])
@require_roles("SafetyOfficer")
def deny_rma(actor, programId, rmaId):
    program = get_program(programId)
    rma = get_rma(programId, rmaId)
    get_body()
    require_program_open(program)
    if rma["status"] != "REQUESTED":
        raise err_rma_not_requested()
    rma["status"] = "DENIED"
    touch(rma)
    return success_object(ser_rma(rma))


@bp.route("/integration-programs/<programId>/return-authorizations/<rmaId>/begin-discharge", methods=["POST"])
@require_roles("QualityEngineer")
def begin_discharge(actor, programId, rmaId):
    program = get_program(programId)
    rma = get_rma(programId, rmaId)
    get_body()
    require_program_open(program)
    if rma["status"] != "APPROVED":
        raise err_rma_not_approved()
    pack = db.packs[rma["battery_pack_id"]]
    # priority 20: a recall hold blocks the start of discharge
    raise_if_pack_under_recall(pack)
    rma["status"] = "DISCHARGE_PENDING"
    touch(rma)
    return success_object(ser_rma(rma))


@bp.route("/integration-programs/<programId>/return-authorizations/<rmaId>/complete-discharge", methods=["POST"])
@require_roles("QualityEngineer")
def complete_discharge(actor, programId, rmaId):
    program = get_program(programId)
    rma = get_rma(programId, rmaId)
    body = get_body(required=True)
    final_soc = _soc_field(body, "final_soc_percent")
    require_program_open(program)
    if rma["status"] != "DISCHARGE_PENDING":
        raise err_rma_not_discharge_pending()
    if final_soc > rma["target_soc_percent"]:
        raise err_discharge_target_not_met()

    pack = db.packs[rma["battery_pack_id"]]
    rma["actual_soc_after_discharge"] = final_soc
    rma["status"] = "DISCHARGED"
    touch(rma)

    pack["soc_percent"] = final_soc
    firmware = db.firmwares.get(pack["bms_firmware_id"]) if pack["bms_firmware_id"] else None
    # hysteresis variant applies only when the flashed firmware supports it
    pack["soc_band"] = soc_band_after_discharge(pack["soc_band"], final_soc, firmware)
    pack["is_safe_discharged"] = True
    pack["disposition"] = "DISCHARGED"
    touch(pack)
    return success_object(ser_rma(rma))


@bp.route("/integration-programs/<programId>/return-authorizations/<rmaId>/receive", methods=["POST"])
@require_roles("CustomerService")
def receive_rma(actor, programId, rmaId):
    program = get_program(programId)
    rma = get_rma(programId, rmaId)
    body = get_body()
    require_program_open(program)
    if rma["status"] != "DISCHARGED":
        raise err_rma_not_discharged()
    # when the caller names the pack being received, it must be the RMA's pack
    if "battery_pack_id" in body and body["battery_pack_id"] is not None:
        named = as_str(body["battery_pack_id"], "battery_pack_id")
        if named not in db.packs:
            raise err_pack_not_found()
        if named != rma["battery_pack_id"]:
            raise err_rma_pack_mismatch()

    pack = db.packs[rma["battery_pack_id"]]
    rma["status"] = "RECEIVED"
    touch(rma)
    pack["logistics_status"] = "RETURNED"
    pack["disposition"] = "SCRAPPED"
    touch(pack)
    return success_object(ser_rma(rma))


@bp.route("/integration-programs/<programId>/return-authorizations/<rmaId>/close", methods=["POST"])
@require_roles("CustomerService")
def close_rma(actor, programId, rmaId):
    program = get_program(programId)
    rma = get_rma(programId, rmaId)
    get_body()
    require_program_open(program)
    if rma["status"] != "RECEIVED":
        raise err_rma_not_received()
    rma["status"] = "CLOSED"
    touch(rma)
    return success_object(ser_rma(rma))
