"""BMSFirmware governance: register, review cycle, approval decisions,
deprecation with re-certification (§3.5)."""

from flask import Blueprint

import db
from domain import (
    new_row, touch, sorted_rows, get_program, get_firmware,
    require_program_open, ser_firmware, ser_approval,
    FIRMWARE_DECISIONS, FIRMWARE_IN_USE_STATES,
)
from errors import (
    err_invalid_request, err_firmware_not_draft, err_firmware_not_pending_review,
    err_sod_firmware_approve, err_firmware_not_approved, err_firmware_in_use,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, opt_field, as_str, as_bool, as_enum, SHA256_RE

bp = Blueprint("bms_firmwares", __name__)


@bp.route("/integration-programs/<programId>/bms-firmwares", methods=["POST"])
@require_roles("AssemblyLead")
def create_firmware(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    firmware_version = as_str(req_field(body, "firmware_version"), "firmware_version")
    binary_sha256 = as_str(req_field(body, "binary_sha256"), "binary_sha256")
    if not SHA256_RE.match(binary_sha256):
        raise err_invalid_request(
            "binary_sha256 must be 64 lowercase hexadecimal characters"
        )
    supports_hysteresis = opt_field(body, "supports_soc_hysteresis", False)
    if not isinstance(supports_hysteresis, bool):
        raise err_invalid_request("supports_soc_hysteresis must be a boolean")
    require_program_open(program)

    row = new_row()
    row.update(
        program_id=program["id"],
        firmware_version=firmware_version,
        binary_sha256=binary_sha256,
        supports_soc_hysteresis=supports_hysteresis,
        approval_record_id=None,
        status="DRAFT",
        _submitted_by_id=None,
    )
    db.firmwares[row["id"]] = row
    return success_created(ser_firmware(row))


@bp.route("/integration-programs/<programId>/bms-firmwares", methods=["GET"])
@require_roles()
def list_firmwares(actor, programId):
    get_program(programId)
    rows = sorted_rows(
        [r for r in db.firmwares.values() if r["program_id"] == programId]
    )
    return success_list(rows, ser_firmware)


@bp.route("/integration-programs/<programId>/bms-firmwares/<fwId>", methods=["GET"])
@require_roles()
def get_one_firmware(actor, programId, fwId):
    get_program(programId)
    return success_object(ser_firmware(get_firmware(programId, fwId)))


@bp.route("/integration-programs/<programId>/bms-firmwares/<fwId>/submit-review", methods=["POST"])
@require_roles("AssemblyLead")
def submit_review(actor, programId, fwId):
    program = get_program(programId)
    fw = get_firmware(programId, fwId)
    get_body()
    require_program_open(program)
    # both the DRAFT path and the DEPRECATED re-cert path lead to
    # PENDING_REVIEW; any other state rejects
    if fw["status"] not in ("DRAFT", "DEPRECATED"):
        raise err_firmware_not_draft()
    fw["status"] = "PENDING_REVIEW"
    fw["_submitted_by_id"] = actor.user_id
    touch(fw)
    return success_object(ser_firmware(fw))


@bp.route("/integration-programs/<programId>/bms-firmwares/<fwId>/approvals", methods=["POST"])
@require_roles("SafetyOfficer")
def record_approval(actor, programId, fwId):
    program = get_program(programId)
    fw = get_firmware(programId, fwId)
    body = get_body(required=True)
    decision = as_enum(req_field(body, "decision"), "decision", FIRMWARE_DECISIONS)
    if decision == "REVOKE":
        # REVOKE is never accepted on the decision endpoint; revocation rows
        # are written exclusively through deprecation (§3.5)
        raise err_invalid_request(
            "decision=REVOKE is not accepted here; use the deprecate endpoint"
        )
    rationale = as_str(req_field(body, "rationale"), "rationale")
    if len(rationale) < 20:
        raise err_invalid_request("rationale must be at least 20 characters")

    require_program_open(program)
    if fw["status"] != "PENDING_REVIEW":
        raise err_firmware_not_pending_review()
    if decision == "APPROVE":
        # priority 6: segregation of duties — approver != submitter
        if actor.user_id == fw.get("_submitted_by_id"):
            raise err_sod_firmware_approve()

    rec = new_row(common=False)
    rec.update(
        bms_firmware_id=fw["id"],
        program_id=program["id"],
        approver_id=actor.user_id,
        decision=decision,
        rationale=rationale,
    )
    db.approvals[rec["id"]] = rec

    if decision == "APPROVE":
        fw["status"] = "APPROVED"
        fw["approval_record_id"] = rec["id"]
    else:  # REJECT returns the firmware to DRAFT
        fw["status"] = "DRAFT"
    touch(fw)
    return success_created(ser_approval(rec))


@bp.route("/integration-programs/<programId>/bms-firmwares/<fwId>/approvals", methods=["GET"])
@require_roles()
def list_approvals(actor, programId, fwId):
    get_program(programId)
    fw = get_firmware(programId, fwId)
    rows = sorted_rows(
        [r for r in db.approvals.values() if r["bms_firmware_id"] == fw["id"]]
    )
    return success_list(rows, ser_approval)


@bp.route("/integration-programs/<programId>/bms-firmwares/<fwId>/deprecate", methods=["POST"])
@require_roles("SafetyOfficer")
def deprecate_firmware(actor, programId, fwId):
    program = get_program(programId)
    fw = get_firmware(programId, fwId)
    get_body()
    require_program_open(program)
    if fw["status"] != "APPROVED":
        raise err_firmware_not_approved()
    # refused while any non-terminal pack at TEST_QUEUED or beyond references it
    for pack in db.packs.values():
        if (
            pack["program_id"] == program["id"]
            and pack["bms_firmware_id"] == fw["id"]
            and pack["assembly_status"] in FIRMWARE_IN_USE_STATES
        ):
            raise err_firmware_in_use()

    rec = new_row(common=False)
    rec.update(
        bms_firmware_id=fw["id"],
        program_id=program["id"],
        approver_id=actor.user_id,
        decision="REVOKE",
        rationale="Firmware deprecated via deprecate endpoint",
    )
    db.approvals[rec["id"]] = rec

    fw["status"] = "DEPRECATED"
    fw["approval_record_id"] = None
    touch(fw)
    return success_object(ser_firmware(fw))
