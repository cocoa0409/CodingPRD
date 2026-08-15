"""Program lifecycle, sweep, supply-plan, attendance summaries (PRD §3.1, §3.3, §3.6, §3.7)."""

from datetime import time

from flask import Blueprint

import clock
import store
from auth import authenticate, require_role
from derived import (
    program_view,
    classrooms_of_program,
    days_of_program,
    enrolled_total,
    non_closed_classrooms,
    kit_base,
    kit_required_final,
    craft_packs_for_classroom,
    budget_remaining_cents,
    attended_days,
)
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_PROGRAM_DATE_OVERLAP,
    ERR_NO_PROGRAM_DAYS,
    ERR_DAYS_STILL_OPEN,
    ERR_FORBIDDEN,
)
from routes.common import paginate, empty_body
from validate import Field, get_body, validate_body, bad
from util import round4

bp = Blueprint("programs", __name__)

PROGRAM_ROADS = ("ProgramDirector", "RegistrationCoordinator", "VolunteerCoordinator",
                 "SafetyOfficer", "CheckInStaff")

_CREATE_SPEC = {
    "name": Field("str", required=True),
    "program_year": Field("int", required=True),
    "start_date": Field("date", required=True),
    "end_date": Field("date", required=True),
    "registration_opens_at": Field("datetime", required=True),
    "registration_closes_at": Field("datetime", required=True),
    "supply_budget_cents": Field("int", required=True),
    "child_staff_ratio": Field("int", default=8),
    "waitlist_offer_ttl_hours": Field("int", default=48),
    "pickup_cutoff_time": Field("time", default=time(12, 0)),
}


def _get_program_or_404(program_id):
    program = store.get("programs", program_id)
    if program is None:
        raise_err(ERR_NOT_FOUND, "program not found")
    return program


@bp.post("/vbs/programs")
def create_program():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    if data["supply_budget_cents"] < 0:
        bad("supply_budget_cents must be >= 0")
    if data["child_staff_ratio"] < 1:
        bad("child_staff_ratio must be >= 1")
    if data["waitlist_offer_ttl_hours"] < 1:
        bad("waitlist_offer_ttl_hours must be >= 1")
    if data["end_date"] < data["start_date"]:
        bad("end_date must not be before start_date")
    if data["registration_closes_at"] <= data["registration_opens_at"]:
        bad("registration_closes_at must be strictly after registration_opens_at")
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    # Priority 7(iv): inclusive date-range overlap against non-ARCHIVED programs.
    for other in store.all_of("programs"):
        if other["status"] == "ARCHIVED":
            continue
        if data["start_date"] <= other["end_date"] and other["start_date"] <= data["end_date"]:
            raise_err(ERR_PROGRAM_DATE_OVERLAP, "program date range overlaps an existing program")
    program = store.new_record(
        name=data["name"],
        program_year=data["program_year"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        registration_opens_at=data["registration_opens_at"],
        registration_closes_at=data["registration_closes_at"],
        supply_budget_cents=data["supply_budget_cents"],
        child_staff_ratio=data["child_staff_ratio"],
        waitlist_offer_ttl_hours=data["waitlist_offer_ttl_hours"],
        pickup_cutoff_time=data["pickup_cutoff_time"],
        status="DRAFT",
        current_day_index=0,
    )
    store.put("programs", program)
    return ok_object(program_view(program), status=201)


@bp.get("/vbs/programs")
def list_programs():
    ctx = authenticate()
    require_role(ctx, *PROGRAM_ROADS)
    from flask import request

    items = list(store.all_of("programs"))
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, program_view)


@bp.get("/vbs/programs/<program_id>")
def get_program(program_id):
    ctx = authenticate()
    require_role(ctx, *PROGRAM_ROADS, "Parent", "Volunteer")
    program = _get_program_or_404(program_id)
    return ok_object(program_view(program))


def _lifecycle(program_id, expect_from, to, extra_check=None):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    program = _get_program_or_404(program_id)
    if program["status"] != expect_from:
        raise_err(ERR_INVALID_STATE, "program is not %s" % expect_from)
    if extra_check is not None:
        extra_check(program)
    program["status"] = to
    store.touch(program)
    return program


@bp.post("/vbs/programs/<program_id>/open-registration")
def open_registration(program_id):
    program = _lifecycle(program_id, "DRAFT", "REGISTRATION_OPEN")
    for c in classrooms_of_program(program["id"]):
        if c["status"] == "SETUP":
            c["status"] = "ACCEPTING"
            store.touch(c)
    return ok_object(program_view(program))


@bp.post("/vbs/programs/<program_id>/close-registration")
def close_registration(program_id):
    program = _lifecycle(program_id, "REGISTRATION_OPEN", "REGISTRATION_CLOSED")
    return ok_object(program_view(program))


@bp.post("/vbs/programs/<program_id>/start-session")
def start_session(program_id):
    def _needs_day(program):
        if not days_of_program(program["id"]):
            raise_err(ERR_NO_PROGRAM_DAYS, "start-session requires at least one program day")

    program = _lifecycle(program_id, "REGISTRATION_CLOSED", "IN_SESSION", _needs_day)
    return ok_object(program_view(program))


@bp.post("/vbs/programs/<program_id>/complete")
def complete_program(program_id):
    def _needs_all_closed(program):
        if any(d["status"] != "CLOSED" for d in days_of_program(program["id"])):
            raise_err(ERR_DAYS_STILL_OPEN, "all program days must be CLOSED to complete")

    program = _lifecycle(program_id, "IN_SESSION", "COMPLETED", _needs_all_closed)
    return ok_object(program_view(program))


@bp.post("/vbs/programs/<program_id>/archive")
def archive_program(program_id):
    program = _lifecycle(program_id, "COMPLETED", "ARCHIVED")
    return ok_object(program_view(program))


@bp.post("/vbs/programs/<program_id>/sweep-expired-offers")
def sweep_expired_offers(program_id):
    body = get_body()
    data = validate_body(body, {"expected_program_version": Field("int", required=True)})
    ctx = authenticate()
    require_role(ctx, "RegistrationCoordinator")
    program = _get_program_or_404(program_id)
    # Priority 4 (OCC) ahead of every business rule.
    if data["expected_program_version"] != program["version"]:
        raise_err(ERR_STALE_VERSION, "expected_program_version does not match the program version")
    if program["status"] == "ARCHIVED":
        raise_err(ERR_INVALID_STATE, "program is archived (read-only)")
    now = clock.now()
    affected = {}
    for reg in store.all_of("registrations"):
        if reg["status"] != "OFFERED":
            continue
        classroom = store.get("classrooms", reg["classroom_id"])
        if classroom is None or classroom["program_id"] != program["id"]:
            continue
        if reg["offer_expires_at"] is not None and reg["offer_expires_at"] <= now:
            reg["status"] = "EXPIRED"
            reg["offer_expires_at"] = None
            store.touch(reg)
            affected[classroom["id"]] = classroom
    from cascade import seat_freed  # local import: avoids cycle

    for classroom in sorted(affected.values(), key=lambda c: c["_seq"]):
        seat_freed(classroom)
    store.touch(program)
    return ok_object(program_view(program))


@bp.get("/vbs/programs/<program_id>/supply-plan")
def supply_plan(program_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    program = _get_program_or_404(program_id)
    classrooms = sorted(non_closed_classrooms(program), key=lambda c: c["_seq"])
    per_classroom = [
        {"classroom_id": c["id"], "packs": craft_packs_for_classroom(c)} for c in classrooms
    ]
    data = {
        "enrolled_total": enrolled_total(program),
        "classroom_count": len(classrooms),
        "kit_quantity_provisional": kit_base(program),
        "kit_quantity_final": kit_required_final(program),
        "craft_packs_required": sum(p["packs"] for p in per_classroom),
        "craft_packs_per_classroom": per_classroom,
        "budget_remaining_cents": budget_remaining_cents(program),
    }
    return ok_object(data)


@bp.get("/vbs/programs/<program_id>/attendance-summaries/<child_id>")
def attendance_summary(program_id, child_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "SafetyOfficer", "Parent")
    program = _get_program_or_404(program_id)
    child = store.get("children", child_id)
    if child is None:
        raise_err(ERR_NOT_FOUND, "child not found")
    if ctx.role == "Parent" and child["family_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "parents may only read their own children's summaries")
    days = days_of_program(program["id"])
    total_days = len(days)
    days_closed = sum(1 for d in days if d["status"] == "CLOSED")
    attended = attended_days(program["id"], child_id)
    data = {
        "attended_days": attended,
        "days_closed": days_closed,
        "total_days": total_days,
        "provisional_rate": round4(attended, days_closed),
        "projected_final_rate": round4(attended, total_days),
    }
    return ok_object(data)
