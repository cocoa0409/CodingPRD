"""Utility rebate programs and field technicians (PRD section 3.1)."""

from flask import Blueprint

import calc
import lookup
import serialize
from envelope import object_response
from errors import ApiError
from guard import (ALL_ROLES, ROLE_PROGRAM_ADMIN, authenticate, body, vbool, venum,
                   vdt, vint, vnum, vstr)
from routes import PREFIX
from store import db, new_record, touch

bp = Blueprint("programs", __name__)


@bp.post(PREFIX + "/utility-programs")
def create_utility_program():
    authenticate((ROLE_PROGRAM_ADMIN,))
    data = body()
    name = vstr(data, "name")
    rebate_basis = venum(data, "rebate_basis", calc.REBATE_BASIS)
    rate = vint(data, "rate_cents_per_cfm_reduced", minimum=0)
    bps = vint(data, "pct_of_invoice_bps", minimum=0, maximum=10000)
    cap = vint(data, "cap_cents", minimum=0)
    budget = vint(data, "annual_budget_cents", minimum=0)
    min_reduction = vnum(data, "min_reduction_pct", minimum=0, maximum=100)
    requires_inspector = vbool(data, "requires_inspector_verification",
                               required=False, default=True)
    combustion_required = vbool(data, "combustion_safety_required",
                                required=False, default=True)

    row = new_record()
    row.update({
        "name": name,
        "rebate_basis": rebate_basis,
        "rate_cents_per_cfm_reduced": rate,
        "pct_of_invoice_bps": bps,
        "cap_cents": cap,
        "annual_budget_cents": budget,
        "min_reduction_pct": calc.rhu(min_reduction, 2),
        "requires_inspector_verification": requires_inspector,
        "combustion_safety_required": combustion_required,
    })
    db.utility_programs[row["id"]] = row
    return object_response(serialize.utility_program(row), 201)


@bp.get(PREFIX + "/utility-programs/<program_id>")
def read_utility_program(program_id):
    authenticate(ALL_ROLES)
    row = lookup.program_or_404(program_id)
    return object_response(serialize.utility_program(row))


@bp.post(PREFIX + "/technicians")
def create_technician():
    authenticate((ROLE_PROGRAM_ADMIN,))
    data = body()
    full_name = vstr(data, "full_name")
    license_number = vstr(data, "license_number")
    status = venum(data, "certification_status", calc.CERTIFICATION_STATUS,
                   required=False, default="PENDING")
    expires_at = vdt(data, "certification_expires_at", required=False, nullable=True)
    for existing in db.rows("technicians"):
        if existing["license_number"] == license_number:
            # No dedicated error exists for the uniqueness rule of PRD section 3.1,
            # so the duplicate is a malformed request.
            raise ApiError("ERR_INVALID_REQUEST",
                           "license_number must be unique across technicians.")

    row = new_record()
    row.update({
        "full_name": full_name,
        "license_number": license_number,
        "certification_status": status,
        "certification_expires_at": expires_at,
    })
    db.technicians[row["id"]] = row
    return object_response(serialize.technician(row), 201)


@bp.get(PREFIX + "/technicians/<technician_id>")
def read_technician(technician_id):
    authenticate(ALL_ROLES)
    row = lookup.technician_or_404(technician_id)
    return object_response(serialize.technician(row))


@bp.post(PREFIX + "/technicians/<technician_id>/certification")
def record_certification(technician_id):
    authenticate((ROLE_PROGRAM_ADMIN,))
    row = lookup.technician_or_404(technician_id)
    data = body()
    status = venum(data, "certification_status", calc.CERTIFICATION_STATUS)
    expires_at = vdt(data, "certification_expires_at", required=True, nullable=True)
    row["certification_status"] = status
    row["certification_expires_at"] = expires_at
    touch(row)
    return object_response(serialize.technician(row))
