"""Clock + admission cycle + grade section routes."""

from flask import Blueprint

import db
import errors
from middleware import require_roles, get_json_body, check_fields
from response import success, success_list
from services import serializers as ser
from services.helpers import make_record, get_or_404, ref_or_404, sort_created
from services.lifecycle import run_decision_sweep, run_ops_sweep

bp = Blueprint("cycles", __name__)

CYCLE_ROLES = ("AdmissionDirector", "AdmissionOfficer", "FinancialAidOfficer", "Parent")
GRADE_LEVELS = ("K", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8",
                "G9", "G10", "G11", "G12")


# --- Logical clock ---------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require_roles("AdmissionDirector")
def set_clock(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {"to_iso8601": "datetime"}, {})
    db.set_clock(vals["to_iso8601"])
    return success({"current_utc": db.fmt_clock(db.get_clock())})


# --- Cycles ----------------------------------------------------------------

@bp.post("/admissions/cycles")
@require_roles("AdmissionDirector")
def create_cycle(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "academic_year": "string",
        "early_deadline_at": "datetime",
        "regular_deadline_at": "datetime",
        "reenroll_response_deadline_at": "datetime",
        "melt_deadline_at": "datetime",
        "aid_budget_total_cents": "int_nonneg",
    }, {})
    early = vals["early_deadline_at"]
    regular = vals["regular_deadline_at"]
    reenroll = vals["reenroll_response_deadline_at"]
    melt = vals["melt_deadline_at"]
    if not (early < regular and regular < reenroll and reenroll <= melt):
        raise errors.err(errors.ERR_VALIDATION,
                         "Cycle deadlines must satisfy early < regular < reenroll <= melt")
    cycle = make_record(db.cycles, {
        "academic_year": vals["academic_year"],
        "early_deadline_at": db.fmt_clock(early),
        "regular_deadline_at": db.fmt_clock(regular),
        "reenroll_response_deadline_at": db.fmt_clock(reenroll),
        "melt_deadline_at": db.fmt_clock(melt),
        "aid_budget_total_cents": vals["aid_budget_total_cents"],
        "status": "DRAFT",
    })
    return success(ser.cycle_view(cycle), 201)


@bp.get("/admissions/cycles")
@require_roles(*CYCLE_ROLES)
def list_cycles(_uid, _role):
    status = None
    from flask import request
    if "status" in request.args:
        status = request.args.get("status")
    items = [c for c in db.cycles.values() if status is None or c["status"] == status]
    return success_list([ser.cycle_view(c) for c in sort_created(items)])


@bp.get("/admissions/cycles/<cycleId>")
@require_roles(*CYCLE_ROLES)
def get_cycle(cycleId, _uid, _role):
    cycle = get_or_404(db.cycles, cycleId, "AdmissionCycle")
    return success(ser.cycle_view(cycle))


@bp.post("/admissions/cycles/<cycleId>/open")
@require_roles("AdmissionDirector")
def open_cycle(cycleId, _uid, _role):
    cycle = get_or_404(db.cycles, cycleId, "AdmissionCycle")
    if cycle["status"] != "DRAFT":
        raise errors.err(errors.ERR_CYCLE_INVALID_STATE,
                         "Only a DRAFT cycle may be opened")
    if not any(s["cycle_id"] == cycleId for s in db.grade_sections.values()):
        raise errors.err(errors.ERR_CYCLE_HAS_NO_SECTIONS,
                         "Cycle has no grade sections")
    cycle["status"] = "OPEN"
    from services.lifecycle import touch
    touch(cycle)
    return success(ser.cycle_view(cycle))


@bp.post("/admissions/cycles/<cycleId>/close-round")
@require_roles("AdmissionDirector")
def close_round(cycleId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {"round": ("enum", ("EARLY", "REGULAR"))}, {})
    cycle = get_or_404(db.cycles, cycleId, "AdmissionCycle")
    round_name = vals["round"]
    clock = db.get_clock()

    if round_name == "EARLY":
        if cycle["status"] != "OPEN":
            raise errors.err(errors.ERR_CYCLE_INVALID_STATE,
                             "Closing EARLY requires the cycle to be OPEN")
        deadline = db.parse_iso(cycle["early_deadline_at"])
        if clock <= deadline:
            raise errors.err(errors.ERR_ROUND_STILL_OPEN,
                             "The EARLY round deadline has not yet passed")
        run_decision_sweep(cycle, "EARLY")
        cycle["status"] = "EARLY_CLOSED"
    else:  # REGULAR
        if cycle["status"] != "EARLY_CLOSED":
            raise errors.err(errors.ERR_CYCLE_INVALID_STATE,
                             "Closing REGULAR requires the cycle to be EARLY_CLOSED")
        deadline = db.parse_iso(cycle["regular_deadline_at"])
        if clock <= deadline:
            raise errors.err(errors.ERR_ROUND_STILL_OPEN,
                             "The REGULAR round deadline has not yet passed")
        run_decision_sweep(cycle, "REGULAR")
        cycle["status"] = "CLOSED"

    from services.lifecycle import touch
    touch(cycle)
    return success(ser.cycle_view(cycle))


@bp.post("/admissions/cycles/<cycleId>/run-sweep")
@require_roles("AdmissionDirector")
def run_sweep(cycleId, _uid, _role):
    cycle = get_or_404(db.cycles, cycleId, "AdmissionCycle")
    result = run_ops_sweep(cycle)
    return success(result)


@bp.post("/admissions/cycles/<cycleId>/archive")
@require_roles("AdmissionDirector")
def archive_cycle(cycleId, _uid, _role):
    cycle = get_or_404(db.cycles, cycleId, "AdmissionCycle")
    if cycle["status"] != "CLOSED":
        raise errors.err(errors.ERR_CYCLE_INVALID_STATE,
                         "Only a CLOSED cycle may be archived")
    cycle["status"] = "ARCHIVED"
    from services.lifecycle import touch
    touch(cycle)
    return success(ser.cycle_view(cycle))


# --- Grade sections --------------------------------------------------------

@bp.post("/admissions/grade-sections")
@require_roles("AdmissionDirector")
def create_section(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "cycle_id": "string",
        "grade_level": ("enum", GRADE_LEVELS),
        "capacity": "int_pos",
        "tuition_cents": "int_nonneg",
        "max_aid_seat_pct": "number",
    }, {})
    pct = vals["max_aid_seat_pct"]
    if pct < 0 or pct > 1:
        raise errors.err(errors.ERR_VALIDATION,
                         "max_aid_seat_pct must be between 0 and 1 inclusive")
    cycle = ref_or_404(db.cycles, vals["cycle_id"], "AdmissionCycle")
    if cycle["status"] != "DRAFT":
        raise errors.err(errors.ERR_CYCLE_INVALID_STATE,
                         "Grade sections may only be created while the cycle is DRAFT")
    section = make_record(db.grade_sections, {
        "cycle_id": vals["cycle_id"],
        "grade_level": vals["grade_level"],
        "capacity": vals["capacity"],
        "tuition_cents": vals["tuition_cents"],
        "max_aid_seat_pct": pct,
    })
    return success(ser.section_view(section), 201)


@bp.get("/admissions/grade-sections")
@require_roles(*CYCLE_ROLES)
def list_sections(_uid, _role):
    from flask import request
    cycle_id = request.args.get("cycle_id")
    grade_level = request.args.get("grade_level")
    items = [s for s in db.grade_sections.values()
             if (cycle_id is None or s["cycle_id"] == cycle_id)
             and (grade_level is None or s["grade_level"] == grade_level)]
    return success_list([ser.section_view(s) for s in sort_created(items)])


@bp.get("/admissions/grade-sections/<sectionId>")
@require_roles(*CYCLE_ROLES)
def get_section(sectionId, _uid, _role):
    section = get_or_404(db.grade_sections, sectionId, "GradeSection")
    return success(ser.section_view(section))
