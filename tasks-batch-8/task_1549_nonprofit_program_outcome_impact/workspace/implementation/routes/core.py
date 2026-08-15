"""Clock, Programs, Funders."""
from flask import Blueprint, request

from db import db, parse_dt, new_entity
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    req_str_nonempty,
    req_datetime,
    get_or_404,
    page_of,
    serialize,
    touch,
)
import services

bp = Blueprint("core", __name__)

READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward", "PrivacyOfficer", "FieldCollector")


# ---------------------------------------------------------------- clock
@bp.post("/_clock/set_current_utc")
@require_roles("ProgramDirector")
def set_clock():
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    db.clock_dt = parse_dt(to_iso8601)
    db.clock_iso = to_iso8601
    return ok_object({"current_utc": db.clock_iso})


# ---------------------------------------------------------------- programs
@bp.post("/programs")
@require_roles("ProgramDirector")
def create_program():
    body = get_body()
    name = req_str(body, "name")
    code = req_str_nonempty(body, "code")
    if any(p["code"] == code for p in db.programs.values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, f"Program code already in use: {code}")
    ent = new_entity(
        db.programs,
        {
            "name": name,
            "code": code,
            "status": "DRAFT",
            "current_logic_model_id": None,
            "current_consent_form_version": 1,
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/programs")
@require_roles(*READ_ROLES)
def list_programs():
    items = list(db.programs.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    clm = request.args.get("current_logic_model_id")
    if clm is not None:
        items = [p for p in items if p["current_logic_model_id"] == clm]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/programs/<pid>")
@require_roles(*READ_ROLES)
def get_program(pid):
    return ok_object(serialize(get_or_404(db.programs, pid)))


def _program_transition(pid, allowed_from, to, extra_check=None):
    program = get_or_404(db.programs, pid)
    if program["status"] not in allowed_from:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Program in state {program['status']} cannot transition to {to}.",
        )
    if extra_check is not None:
        extra_check(program)
    program["status"] = to
    touch(db.programs, program)
    return ok_object(serialize(program))


@bp.post("/programs/<pid>/activate")
@require_roles("ProgramDirector")
def activate_program(pid):
    return _program_transition(pid, ("DRAFT",), "ACTIVE")


@bp.post("/programs/<pid>/suspend")
@require_roles("ProgramDirector")
def suspend_program(pid):
    return _program_transition(pid, ("ACTIVE",), "SUSPENDED")


@bp.post("/programs/<pid>/resume")
@require_roles("ProgramDirector")
def resume_program(pid):
    return _program_transition(pid, ("SUSPENDED",), "ACTIVE")


@bp.post("/programs/<pid>/archive")
@require_roles("ProgramDirector")
def archive_program(pid):
    def _cycles_archived(program):
        cycles = [c for c in db.cycles.values() if c["program_id"] == program["id"]]
        if any(c["status"] != "ARCHIVED" for c in cycles):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Program cannot be archived until every program cycle is ARCHIVED.",
            )

    return _program_transition(pid, ("ACTIVE", "SUSPENDED"), "ARCHIVED", _cycles_archived)


@bp.post("/programs/<pid>/consent-form-bump")
@require_roles("PrivacyOfficer")
def consent_form_bump(pid):
    program = get_or_404(db.programs, pid)
    program["current_consent_form_version"] += 1
    new_version = program["current_consent_form_version"]
    touch(db.programs, program)
    # Supersede every GRANTED consent of every participant in every cycle of
    # this program whose form_version trails the new value.
    program_cycles = {c["id"] for c in db.cycles.values() if c["program_id"] == pid}
    program_participants = [
        p for p in db.participants.values() if p["program_cycle_id"] in program_cycles
    ]
    pids = {p["id"] for p in program_participants}
    for consent in db.consents.values():
        if (
            consent["participant_id"] in pids
            and consent["status"] == "GRANTED"
            and consent["form_version"] < new_version
        ):
            consent["status"] = "SUPERSEDED"
            touch(db.consents, consent)
    for participant in program_participants:
        services.refresh_participant_consent(participant)
    return ok_object(serialize(program))


# ---------------------------------------------------------------- funders
@bp.post("/funders")
@require_roles("ProgramDirector")
def create_funder():
    body = get_body()
    name = req_str(body, "name")
    code = req_str_nonempty(body, "code")
    if any(f["code"] == code for f in db.funders.values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, f"Funder code already in use: {code}")
    ent = new_entity(db.funders, {"name": name, "code": code, "status": "ACTIVE"})
    return ok_object(serialize(ent), 201)


FUNDER_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward", "PrivacyOfficer")


@bp.get("/funders")
@require_roles(*FUNDER_READ_ROLES)
def list_funders():
    items = list(db.funders.values())
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/funders/<fid>")
@require_roles(*FUNDER_READ_ROLES)
def get_funder(fid):
    return ok_object(serialize(get_or_404(db.funders, fid)))


@bp.post("/funders/<fid>/deactivate")
@require_roles("ProgramDirector")
def deactivate_funder(fid):
    funder = get_or_404(db.funders, fid)
    if funder["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE funder can be deactivated.")
    funder["status"] = "INACTIVE"
    touch(db.funders, funder)
    return ok_object(serialize(funder))


@bp.post("/funders/<fid>/reactivate")
@require_roles("ProgramDirector")
def reactivate_funder(fid):
    funder = get_or_404(db.funders, fid)
    if funder["status"] != "INACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an INACTIVE funder can be reactivated.")
    funder["status"] = "ACTIVE"
    touch(db.funders, funder)
    return ok_object(serialize(funder))
