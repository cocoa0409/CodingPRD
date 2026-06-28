"""Program routes (PRD 3.1, 3.8; §1.5)."""
from flask import Blueprint

import db
import helpers
import lookups
import response
from middleware import require
from services import calc

bp = Blueprint("programs", __name__)


def _validate_nonneg_int(data, name):
    v = helpers.require_int(data, name)
    if v < 0:
        raise __import__("errors").invalid_request(f"{name} must be >= 0")
    return v


@bp.post("/school/programs")
@require("Registrar")
def create_program():
    import errors
    data = helpers.body()
    helpers.require_fields(
        data, "name", "total_clock_hours", "tuition_cents",
        "kit_fee_cents", "lab_fee_cents", "clinic_phase_start_hour",
    )
    name = helpers.require_str(data, "name")
    total_clock_hours = helpers.require_int(data, "total_clock_hours")
    if total_clock_hours < 1:
        raise errors.invalid_request("total_clock_hours must be >= 1")
    tuition_cents = helpers.require_int(data, "tuition_cents")
    kit_fee_cents = helpers.require_int(data, "kit_fee_cents")
    lab_fee_cents = helpers.require_int(data, "lab_fee_cents")
    for n, v in (("tuition_cents", tuition_cents), ("kit_fee_cents", kit_fee_cents),
                 ("lab_fee_cents", lab_fee_cents)):
        if v < 0:
            raise errors.invalid_request(f"{n} must be >= 0")
    clinic_phase_start_hour = helpers.require_int(data, "clinic_phase_start_hour")
    if clinic_phase_start_hour < 0:
        raise errors.invalid_request("clinic_phase_start_hour must be >= 0")
    clock_hours_per_credit = helpers.opt_number(data, "clock_hours_per_credit", 37.5)
    if clock_hours_per_credit <= 0:
        raise errors.invalid_request("clock_hours_per_credit must be > 0")
    admin_fee_cap_cents = helpers.opt_int(data, "admin_fee_cap_cents", 15000)
    if admin_fee_cap_cents < 0:
        raise errors.invalid_request("admin_fee_cap_cents must be >= 0")

    row = {
        "name": name,
        "total_clock_hours": total_clock_hours,
        "tuition_cents": tuition_cents,
        "kit_fee_cents": kit_fee_cents,
        "lab_fee_cents": lab_fee_cents,
        "clock_hours_per_credit": clock_hours_per_credit,
        "clinic_phase_start_hour": clinic_phase_start_hour,
        "admin_fee_cap_cents": admin_fee_cap_cents,
        "credit_hours": calc.credit_hours(total_clock_hours, clock_hours_per_credit),
    }
    db.stamp_new(row)
    db.programs[row["id"]] = row
    return response.created(row)


@bp.get("/school/programs/<pid>")
@require("Registrar", "FinancialAidOfficer", "Instructor", "Student")
def get_program(pid):
    row = lookups.path(db.programs, pid)
    return response.ok(row)


@bp.get("/school/programs")
@require("Registrar", "FinancialAidOfficer", "Instructor", "Student")
def list_programs():
    rows, limit, offset, total = helpers.paginate(list(db.programs.values()))
    return response.listing(rows, limit, offset, total)


@bp.get("/school/programs/<pid>/placement-report")
@require("Registrar")
def placement_report(pid):
    lookups.path(db.programs, pid)
    grads = [
        e for e in db.enrollments.values()
        if e["program_id"] == pid and e["status"] == "GRADUATED"
    ]
    total_graduates = len(grads)
    excluded_count = sum(1 for e in grads if e["placement_status"] == "EXCLUDED")
    placed_count = sum(1 for e in grads if e["placement_status"] == "PLACED")
    rate = calc.placement_rate(total_graduates, excluded_count, placed_count)
    return response.ok({
        "program_id": pid,
        "total_graduates": total_graduates,
        "excluded_count": excluded_count,
        "placed_count": placed_count,
        "placement_rate_pct": rate,
    })
