"""Program endpoints + logical clock. PRD §3.1, §2.9."""
from flask import Blueprint

import db
from errors import err
from middleware import require_roles
from response import success
from services import common as c

bp = Blueprint("programs", __name__)


def program_view(p):
    return dict(p)


@bp.post("/pace/programs")
@require_roles("ProgramAdmin")
def create_program():
    body = c.get_body()
    name = c.as_str(body, "name")
    state_code = c.as_str(body, "state_code")
    daily_census_capacity = c.as_int(body, "daily_census_capacity", min_val=1)
    max_roster = c.as_int(body, "max_roster", min_val=1)
    medicaid_rate = c.as_int(body, "medicaid_monthly_rate_cents", min_val=0)
    medicare_rate = c.as_int(body, "medicare_monthly_rate_cents", min_val=0)
    supplement = c.as_int(body, "medicare_only_supplement_cents",
                          required=False, default=0, min_val=0)
    lock_in_days = c.as_int(body, "lock_in_days", required=False, default=30, min_val=0)
    loc_validity_days = c.as_int(body, "loc_validity_days", required=False, default=365)

    p = c.base_fields()
    p.update({
        "name": name,
        "state_code": state_code,
        "daily_census_capacity": daily_census_capacity,
        "max_roster": max_roster,
        "medicaid_monthly_rate_cents": medicaid_rate,
        "medicare_monthly_rate_cents": medicare_rate,
        "medicare_only_supplement_cents": supplement,
        "lock_in_days": lock_in_days,
        "loc_validity_days": loc_validity_days,
        "enrolled_count": 0,
        "status": "OPEN",
    })
    db.programs[p["id"]] = p
    return success(program_view(p), status=201)


@bp.get("/pace/programs/<program_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def get_program(program_id):
    p = c.find_or_404(db.programs, program_id)
    return success(program_view(p))


@bp.post("/pace/programs/<program_id>/suspend")
@require_roles("ProgramAdmin")
def suspend_program(program_id):
    p = c.find_or_404(db.programs, program_id)
    p["status"] = "SUSPENDED"
    c.touch(p)
    return success(program_view(p))


@bp.post("/pace/programs/<program_id>/reopen")
@require_roles("ProgramAdmin")
def reopen_program(program_id):
    p = c.find_or_404(db.programs, program_id)
    p["status"] = "OPEN"
    c.touch(p)
    return success(program_view(p))


@bp.post("/_clock/set_current_utc")
@require_roles("ProgramAdmin")
def set_clock():
    body = c.get_body()
    to_iso = c.as_str(body, "to_iso8601")
    dt = c.parse_iso(to_iso, "to_iso8601")
    db.set_clock(dt)
    return success({"current_utc": c.iso_out(dt)})
