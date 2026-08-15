"""Reconciliation event endpoints: list, get, resolve, escalate."""
from flask import Blueprint, request

import db
from calc import compute_priority
from errors import raise_error
from helpers import (
    get_or_404,
    list_page,
    require_program_active,
    touch,
)
from middleware import (
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_enum,
    validate_string,
)
from response import success_list, success_object
from serializers import reconciliation_out

bp = Blueprint("reconciliations", __name__)

ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor"}


def _case_after_event_settled(case, settled_event_id):
    """Cascade up: when no OPEN reconciliation events remain on a case in
    UNDER_REVIEW, the case moves to RECONCILED."""
    other_open = any(
        e for e in db.reconciliations.values()
        if e["patient_case_id"] == case["id"]
        and e["id"] != settled_event_id
        and e["status"] == "OPEN"
    )
    if not other_open and case["status"] == "UNDER_REVIEW":
        case["status"] = "RECONCILED"


@bp.route("/api/reconciliation-events", methods=["GET"])
def list_reconciliations():
    require_roles(ROLES)
    case_id = request.args.get("patient_case_id")
    program_id = request.args.get("cdi_program_id")
    status = request.args.get("status")
    items = list(db.reconciliations.values())
    if case_id is not None:
        items = [e for e in items if e["patient_case_id"] == case_id]
    if program_id is not None:
        items = [e for e in items if e["cdi_program_id"] == program_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, limit, offset, total = list_page(items)
    return success_list([reconciliation_out(e) for e in page], limit, offset, total)


@bp.route("/api/reconciliation-events/<eventId>", methods=["GET"])
def get_reconciliation(eventId):
    require_roles(ROLES)
    event = get_or_404(db.reconciliations, eventId, "reconciliation event")
    return success_object(reconciliation_out(event))


@bp.route("/api/reconciliation-events/<eventId>/resolve", methods=["POST"])
def resolve_reconciliation(eventId):
    require_roles({"CDIManager"})
    event = get_or_404(db.reconciliations, eventId, "reconciliation event")
    program = db.programs.get(event["cdi_program_id"])
    require_program_active(program)
    if event["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "Only an OPEN reconciliation can be resolved")
    body = get_json_body()
    check_known_fields(body, {"outcome", "resolution_note"})
    require_fields(body, ["outcome", "resolution_note"])
    outcome = validate_enum(body["outcome"], {"CDI_PREVAILS", "CODER_PREVAILS"}, "outcome")
    note = validate_string(body["resolution_note"], "resolution_note")
    case = db.cases.get(event["patient_case_id"])
    if outcome == "CDI_PREVAILS":
        event["status"] = "RESOLVED_CDI_PREVAILS"
        if case is not None:
            # CDI values win: working DRG fields left unchanged.
            case["reconciliation_status"] = "RESOLVED_CDI_PREVAILS"
    else:
        event["status"] = "RESOLVED_CODER_PREVAILS"
        if case is not None:
            # Coder values win: working DRG fields overwritten.
            case["reconciliation_status"] = "RESOLVED_CODER_PREVAILS"
            case["working_drg_code"] = event["coder_drg_code"]
            case["working_drg_weight"] = event["coder_drg_weight"]
            compute_priority(case)
    event["resolution_note"] = note
    touch(event)
    if case is not None:
        _case_after_event_settled(case, event["id"])
        touch(case)
    return success_object(reconciliation_out(event))


@bp.route("/api/reconciliation-events/<eventId>/escalate", methods=["POST"])
def escalate_reconciliation(eventId):
    require_roles({"CDIManager"})
    event = get_or_404(db.reconciliations, eventId, "reconciliation event")
    get_json_body()
    program = db.programs.get(event["cdi_program_id"])
    require_program_active(program)
    if event["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "Only an OPEN reconciliation can be escalated")
    event["status"] = "ESCALATED"
    touch(event)
    case = db.cases.get(event["patient_case_id"])
    if case is not None:
        case["reconciliation_status"] = "ESCALATED"
        _case_after_event_settled(case, event["id"])
        touch(case)
    return success_object(reconciliation_out(event))
