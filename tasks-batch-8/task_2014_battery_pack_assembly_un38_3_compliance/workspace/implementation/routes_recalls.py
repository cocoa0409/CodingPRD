"""RecallCampaign lifecycle (§3.9): activation cascade with capture-set
computation, force-release of stored/staged packs, containment and closure."""

from flask import Blueprint, request

import db
from domain import (
    new_row, touch, sorted_rows, get_program, get_recall, require_program_open,
    ser_recall, recall_capture_set, release_placement, decrement_risk,
    active_placement_for_pack, SEVERITIES, SEVERITY_WEIGHT,
)
from errors import (
    err_lot_not_found, err_bom_not_found, err_cross_program,
    err_recall_not_draft, err_recall_scope_empty, err_recall_not_active,
    err_recall_not_fully_contained, err_recall_not_contained,
    err_invalid_request,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, opt_field, as_str, as_enum

bp = Blueprint("recalls", __name__)


@bp.route("/integration-programs/<programId>/recall-campaigns", methods=["POST"])
@require_roles("SafetyOfficer")
def create_recall(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    recall_code = as_str(req_field(body, "recall_code"), "recall_code")
    severity = as_enum(req_field(body, "severity"), "severity", SEVERITIES)
    scope_lot_id = opt_field(body, "scope_lot_id")
    scope_bom_id = opt_field(body, "scope_bom_id")
    scope_serial_prefix = opt_field(body, "scope_serial_prefix")
    if scope_lot_id is not None:
        scope_lot_id = as_str(scope_lot_id, "scope_lot_id")
    if scope_bom_id is not None:
        scope_bom_id = as_str(scope_bom_id, "scope_bom_id")
    if scope_serial_prefix is not None:
        scope_serial_prefix = as_str(scope_serial_prefix, "scope_serial_prefix")

    # referenced scope selectors must resolve and belong to this program
    scope_lot = None
    if scope_lot_id is not None:
        scope_lot = db.cell_lots.get(scope_lot_id)
        if scope_lot is None:
            raise err_lot_not_found()
    scope_bom = None
    if scope_bom_id is not None:
        scope_bom = db.boms.get(scope_bom_id)
        if scope_bom is None:
            raise err_bom_not_found()
    require_program_open(program)
    if scope_lot is not None and scope_lot["program_id"] != program["id"]:
        raise err_cross_program()
    if scope_bom is not None and scope_bom["program_id"] != program["id"]:
        raise err_cross_program()

    row = new_row()
    row.update(
        program_id=program["id"],
        recall_code=recall_code,
        scope_lot_id=scope_lot_id,
        scope_bom_id=scope_bom_id,
        scope_serial_prefix=scope_serial_prefix,
        packs_in_scope=0,
        packs_contained=0,
        severity=severity,
        status="DRAFT",
    )
    db.recalls[row["id"]] = row
    return success_created(ser_recall(row))


@bp.route("/integration-programs/<programId>/recall-campaigns", methods=["GET"])
@require_roles()
def list_recalls(actor, programId):
    get_program(programId)
    rows = [r for r in db.recalls.values() if r["program_id"] == programId]
    for f in ("scope_lot_id", "scope_bom_id"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r.get(f) == v]
    return success_list(sorted_rows(rows), ser_recall)


@bp.route("/integration-programs/<programId>/recall-campaigns/<recallId>", methods=["GET"])
@require_roles()
def get_one_recall(actor, programId, recallId):
    get_program(programId)
    return success_object(ser_recall(get_recall(programId, recallId)))


@bp.route("/integration-programs/<programId>/recall-campaigns/<recallId>/activate", methods=["POST"])
@require_roles("SafetyOfficer")
def activate_recall(actor, programId, recallId):
    program = get_program(programId)
    recall = get_recall(programId, recallId)
    get_body()
    require_program_open(program)
    if recall["status"] != "DRAFT":
        raise err_recall_not_draft()
    if not (
        recall.get("scope_lot_id")
        or recall.get("scope_bom_id")
        or recall.get("scope_serial_prefix")
    ):
        raise err_recall_scope_empty()

    captured = recall_capture_set(recall)
    contained = 0
    for pack in captured.values():
        pack["active_recall_id"] = recall["id"]
        pack["disposition"] = "RECALLED_HOLD"
        # only packs at READY_TO_STORE fire the assembly-axis transition
        if pack["assembly_status"] == "READY_TO_STORE":
            pack["assembly_status"] = "RECALLED"
            contained += 1
        # packs sitting in rated storage are force-released
        if pack["logistics_status"] in ("STAGED", "STORED"):
            placement = active_placement_for_pack(pack["id"])
            if placement is not None:
                release_placement(placement, pack)
            pack["logistics_status"] = "NOT_STORED"
        touch(pack)

    recall["packs_in_scope"] = len(captured)
    recall["packs_contained"] = contained
    recall["status"] = "ACTIVE"
    touch(recall)

    program["recall_count"] += 1
    touch(program)
    decrement_risk(program, SEVERITY_WEIGHT[recall["severity"]] * len(captured))
    return success_object(ser_recall(recall))


@bp.route("/integration-programs/<programId>/recall-campaigns/<recallId>/mark-contained", methods=["POST"])
@require_roles("SafetyOfficer")
def mark_contained(actor, programId, recallId):
    program = get_program(programId)
    recall = get_recall(programId, recallId)
    get_body()
    require_program_open(program)
    if recall["status"] != "ACTIVE":
        raise err_recall_not_active()
    if recall["packs_contained"] != recall["packs_in_scope"]:
        raise err_recall_not_fully_contained()
    recall["status"] = "CONTAINED"
    touch(recall)
    return success_object(ser_recall(recall))


@bp.route("/integration-programs/<programId>/recall-campaigns/<recallId>/close", methods=["POST"])
@require_roles("SafetyOfficer")
def close_recall(actor, programId, recallId):
    program = get_program(programId)
    recall = get_recall(programId, recallId)
    get_body()
    require_program_open(program)
    if recall["status"] != "CONTAINED":
        raise err_recall_not_contained()
    recall["status"] = "CLOSED"
    touch(recall)
    program["recall_count"] -= 1
    touch(program)
    # clear the capture markers; RECALLED_HOLD disposition stays as evidence
    for pack in db.packs.values():
        if pack["program_id"] == program["id"] and pack["active_recall_id"] == recall["id"]:
            pack["active_recall_id"] = None
            touch(pack)
    return success_object(ser_recall(recall))
