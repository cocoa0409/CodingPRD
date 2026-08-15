"""Denial risk target endpoints."""
from flask import Blueprint, request

import db
from errors import raise_error
from helpers import (
    body_ref,
    get_or_404,
    list_page,
    make_record,
    require_program_active,
)
from middleware import (
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_int_range,
    validate_period,
    validate_string,
    validate_string_list,
)
from response import success_list, success_object
from serializers import target_out

bp = Blueprint("targets", __name__)

WRITE_ROLES = {"CDIManager", "ComplianceAuditor"}
READ_ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor"}


@bp.route("/api/denial-risk-targets", methods=["POST"])
def create_target():
    require_roles(WRITE_ROLES)
    body = get_json_body()
    check_known_fields(body, {
        "cdi_program_id", "drg_code", "required_evidence_tags",
        "severity_floor", "active_from_period", "active_to_period",
    })
    require_fields(body, [
        "cdi_program_id", "drg_code", "required_evidence_tags",
        "severity_floor", "active_from_period", "active_to_period",
    ])
    program = body_ref(body, "cdi_program_id", db.programs, "program")
    drg_code = validate_string(body["drg_code"], "drg_code")
    tags = validate_string_list(body["required_evidence_tags"], "required_evidence_tags")
    severity_floor = validate_int_range(body["severity_floor"], "severity_floor", 1, 4)
    active_from = validate_period(body["active_from_period"], "active_from_period")
    active_to = validate_period(body["active_to_period"], "active_to_period")
    if active_to < active_from:
        raise_error(
            "ERR_INVALID_REQUEST",
            "active_to_period must be >= active_from_period",
        )
    require_program_active(program)
    target = make_record(db.targets, {
        "cdi_program_id": program["id"],
        "drg_code": drg_code,
        "required_evidence_tags": tags,
        "severity_floor": severity_floor,
        "active_from_period": active_from,
        "active_to_period": active_to,
    })
    return success_object(target_out(target), status=201)


@bp.route("/api/denial-risk-targets", methods=["GET"])
def list_targets():
    require_roles(READ_ROLES)
    program_id = request.args.get("cdi_program_id")
    drg_code = request.args.get("drg_code")
    items = list(db.targets.values())
    if program_id is not None:
        items = [t for t in items if t["cdi_program_id"] == program_id]
    if drg_code is not None:
        items = [t for t in items if t["drg_code"] == drg_code]
    page, limit, offset, total = list_page(items)
    return success_list([target_out(t) for t in page], limit, offset, total)


@bp.route("/api/denial-risk-targets/<targetId>", methods=["GET"])
def get_target(targetId):
    require_roles(READ_ROLES)
    target = get_or_404(db.targets, targetId, "denial risk target")
    return success_object(target_out(target))
