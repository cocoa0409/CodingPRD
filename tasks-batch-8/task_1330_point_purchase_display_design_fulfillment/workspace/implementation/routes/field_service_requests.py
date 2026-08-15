"""FieldServiceRequest endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_string, require_enum, touch, paginate,
    sort_by_created, serialize,
)

bp = Blueprint("field_service_requests", __name__)

ISSUE_TYPES = {"ASSEMBLY_HELP", "MISSING_PARTS", "INSTRUCTION_CLARIFICATION"}
GET_FSR_ROLES = ("PlatformAdmin", "ProgramManager", "FieldServiceManager")


def _get_fsr_or_404(fsr_id):
    f = db.field_service_requests.get(fsr_id)
    if not f:
        raise errors.err_not_found("Field service request not found")
    return f


@bp.route("/pop/field-service-requests", methods=["POST"])
@require_roles("FieldServiceManager", "ProgramManager")
def create_fsr():
    body = request.get_json(silent=True) or {}
    store_id = require_string(body, "store_id")
    program_id = require_string(body, "program_id")
    issue_type = require_enum(body, "issue_type", ISSUE_TYPES)

    store = db.stores.get(store_id)
    if not store:
        raise errors.err_not_found("Store not found")
    program = db.programs.get(program_id)
    if not program:
        raise errors.err_not_found("Program not found")
    if store["program_id"] != program_id:
        raise errors.err_referential("program_id does not match the store's program")

    fsr = new_common_fields()
    fsr.update({
        "store_id": store_id,
        "program_id": program_id,
        "issue_type": issue_type,
        "status": "OPEN",
    })
    db.field_service_requests[fsr["id"]] = fsr
    return response.success_object(serialize(fsr), 201)


@bp.route("/pop/field-service-requests/<fsr_id>", methods=["GET"])
def get_fsr(fsr_id):
    _, role = get_auth()
    if role not in GET_FSR_ROLES:
        raise errors.err_unauthorized()
    fsr = _get_fsr_or_404(fsr_id)
    return response.success_object(serialize(fsr), 200)


@bp.route("/pop/stores/<store_id>/field-service-requests", methods=["GET"])
def list_store_fsrs(store_id):
    _, role = get_auth()
    if role not in GET_FSR_ROLES:
        raise errors.err_unauthorized()
    if not db.stores.get(store_id):
        raise errors.err_not_found("Store not found")
    items = sort_by_created([f for f in db.field_service_requests.values() if f["store_id"] == store_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(f) for f in page], limit, offset, total)


@bp.route("/pop/programs/<program_id>/field-service-requests", methods=["GET"])
def list_program_fsrs(program_id):
    _, role = get_auth()
    if role not in GET_FSR_ROLES:
        raise errors.err_unauthorized()
    if not db.programs.get(program_id):
        raise errors.err_not_found("Program not found")
    items = sort_by_created([f for f in db.field_service_requests.values() if f["program_id"] == program_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(f) for f in page], limit, offset, total)


@bp.route("/pop/field-service-requests/<fsr_id>/dispatch", methods=["POST"])
@require_roles("FieldServiceManager")
def dispatch_fsr(fsr_id):
    fsr = _get_fsr_or_404(fsr_id)
    if fsr["status"] != "OPEN":
        raise errors.err_invalid_state("FSR is not in OPEN")
    fsr["status"] = "DISPATCHED"
    touch(fsr)
    return response.success_object(serialize(fsr), 200)


@bp.route("/pop/field-service-requests/<fsr_id>/resolve", methods=["POST"])
@require_roles("FieldServiceManager")
def resolve_fsr(fsr_id):
    fsr = _get_fsr_or_404(fsr_id)
    if fsr["status"] != "DISPATCHED":
        raise errors.err_invalid_state("FSR is not in DISPATCHED")
    fsr["status"] = "RESOLVED"
    touch(fsr)
    return response.success_object(serialize(fsr), 200)
