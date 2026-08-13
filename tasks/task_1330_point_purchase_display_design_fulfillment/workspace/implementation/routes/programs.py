"""RetailerProgram endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_string, require_int, touch, paginate,
    sort_by_created, serialize, mint_recap,
)

bp = Blueprint("programs", __name__)

ALL_ROLES = (
    "PlatformAdmin", "ProgramManager", "Designer", "ComplianceOfficer",
    "ProductionPlanner", "WarehouseOperator", "LogisticsCoordinator",
    "ClaimsAdjuster", "FieldServiceManager",
)


def _get_program_or_404(program_id):
    p = db.programs.get(program_id)
    if not p:
        raise errors.err_not_found("Program not found")
    return p


@bp.route("/pop/programs", methods=["POST"])
@require_roles("ProgramManager")
def create_program():
    body = request.get_json(silent=True) or {}
    client_id = require_string(body, "client_id")
    retailer_name = require_string(body, "retailer_name")
    program_name = require_string(body, "program_name")
    store_count = require_int(body, "store_count", minimum=1)
    program_revenue_cents = require_int(body, "program_revenue_cents", minimum=0)

    client = db.clients.get(client_id)
    if not client:
        raise errors.err_not_found("Client not found")

    program = new_common_fields()
    program.update({
        "client_id": client_id,
        "retailer_name": retailer_name,
        "program_name": program_name,
        "store_count": store_count,
        "program_revenue_cents": program_revenue_cents,
        "status": "DRAFT",
    })
    db.programs[program["id"]] = program
    return response.success_object(serialize(program), 201)


@bp.route("/pop/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    _, role = get_auth()
    if role not in ALL_ROLES:
        raise errors.err_unauthorized()
    program = _get_program_or_404(program_id)
    return response.success_object(serialize(program), 200)


@bp.route("/pop/programs/<program_id>/start-design", methods=["POST"])
@require_roles("ProgramManager")
def start_design(program_id):
    program = _get_program_or_404(program_id)
    if program["status"] != "DRAFT":
        raise errors.err_invalid_state("Program is not in DRAFT")
    active_rules = [
        r for r in db.compliance_rules.values()
        if r["program_id"] == program_id and r.get("active", True)
    ]
    if not active_rules:
        raise errors.err_compliance_failed("Program has no active compliance rule")
    program["status"] = "DESIGN"
    touch(program)
    return response.success_object(serialize(program), 200)


@bp.route("/pop/programs/<program_id>/authorize-production", methods=["POST"])
@require_roles("ProgramManager")
def authorize_production(program_id):
    program = _get_program_or_404(program_id)
    if program["status"] != "DESIGN":
        raise errors.err_invalid_state("Program is not in DESIGN")
    approved = any(
        d["program_id"] == program_id and d["status"] == "APPROVED"
        for d in db.designs.values()
    )
    if not approved:
        raise errors.err_invalid_state("No APPROVED design exists for the program")
    program["status"] = "PRODUCTION"
    touch(program)
    return response.success_object(serialize(program), 200)


@bp.route("/pop/programs/<program_id>/start-fulfillment", methods=["POST"])
@require_roles("ProgramManager")
def start_fulfillment(program_id):
    program = _get_program_or_404(program_id)
    if program["status"] != "PRODUCTION":
        raise errors.err_invalid_state("Program is not in PRODUCTION")
    produced = any(
        r["program_id"] == program_id and r["status"] == "PRODUCED"
        for r in db.production_runs.values()
    )
    if not produced:
        raise errors.err_invalid_state("No PRODUCED production run exists for the program")
    program["status"] = "FULFILLMENT"
    touch(program)
    return response.success_object(serialize(program), 200)


@bp.route("/pop/programs/<program_id>/close", methods=["POST"])
@require_roles("ProgramManager")
def close_program(program_id):
    program = _get_program_or_404(program_id)
    if program["status"] != "FULFILLMENT":
        raise errors.err_invalid_state("Program is not in FULFILLMENT")
    # Every kit of the program must be terminal (DELIVERED or DAMAGED)
    program_runs = {r["id"] for r in db.production_runs.values() if r["program_id"] == program_id}
    for kit in db.kits.values():
        if kit["production_run_id"] in program_runs:
            if kit["status"] not in ("DELIVERED", "DAMAGED"):
                raise errors.err_invalid_state("Not every kit is in a terminal state")
    mint_recap(program)
    program["status"] = "CLOSED"
    touch(program)
    return response.success_object(serialize(program), 200)


@bp.route("/pop/programs/<program_id>/cancel", methods=["POST"])
@require_roles("ProgramManager")
def cancel_program(program_id):
    program = _get_program_or_404(program_id)
    if program["status"] not in ("DRAFT", "DESIGN"):
        raise errors.err_invalid_state("Program cannot be cancelled in its current state")
    # Cascade: all non-terminal designs -> REJECTED
    for d in db.designs.values():
        if d["program_id"] == program_id and d["status"] not in ("LOCKED", "REJECTED"):
            d["status"] = "REJECTED"
            touch(d)
    program["status"] = "CANCELLED"
    touch(program)
    return response.success_object(serialize(program), 200)


@bp.route("/pop/programs/<program_id>/recap", methods=["GET"])
def get_recap(program_id):
    _, role = get_auth()
    if role not in ("PlatformAdmin", "ProgramManager"):
        raise errors.err_unauthorized()
    _get_program_or_404(program_id)
    items = sort_by_created([r for r in db.recaps.values() if r["program_id"] == program_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(r) for r in page], limit, offset, total)
