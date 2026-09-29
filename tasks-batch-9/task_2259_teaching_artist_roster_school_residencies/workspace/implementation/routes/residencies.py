"""Residency scoping, lead-artist staffing and the residency lifecycle."""
from flask import Blueprint, request

import db
import middleware as mw
import response
from enums import (
    COLLABORATION_EXPECTATIONS,
    DISCIPLINES,
    GRADE_BANDS,
    RESIDENCY_STATUSES,
    STAFFING_STATUSES,
    STRANDS,
)
from errors import ApiError
from routes.artists import find_artist
from routes.schools import find_school
from services import calc, derive
from validators import Payload, bad

bp = Blueprint("residencies", __name__)

RESIDENCY_TRANSITIONS = {
    ("DRAFT", "APPROVED"),
    ("APPROVED", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "COMPLETED"),
    ("COMPLETED", "CLOSED"),
    ("DRAFT", "CANCELLED"),
}


def find_residency(residency_id):
    residency = db.residencies.get(residency_id)
    if residency is None:
        raise ApiError("ERR_RESIDENCY_NOT_FOUND", "residency %s not found" % residency_id)
    return residency


def invalid_transition(message="the requested transition is not declared from the current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def plans_of_residency(residency_id):
    return db.ordered([p for p in db.lesson_plans.values()
                       if p["residency_id"] == residency_id])


def archive_plans(residency, statuses):
    for plan in plans_of_residency(residency["id"]):
        if plan["status"] in statuses:
            plan["status"] = "ARCHIVED"
            db.touch(plan)


# --- scoping ----------------------------------------------------------------
@bp.post("/residencies")
@mw.school_health_sync
def create_residency():
    mw.auth("ProgramDirector", "RosterCoordinator")
    body = Payload(request.get_json(silent=True))
    school_partner_id = body.string("school_partner_id", required=True)
    title = body.string("title", required=True)
    discipline = body.enum("discipline", DISCIPLINES, required=True)
    grade_band = body.enum("grade_band", GRADE_BANDS, required=True)
    instruction_language = body.language("instruction_language", default="en")
    contracted = body.integer("contracted_session_count", required=True, minimum=1, maximum=60)
    length = body.integer("session_length_minutes", required=True, minimum=30, maximum=120,
                          multiple_of=5)
    budget_cents = body.integer("budget_cents", required=True, minimum=1)
    stipend = body.integer("materials_stipend_cents", default=0, minimum=0)
    collaboration = body.enum("collaboration_expectation", COLLABORATION_EXPECTATIONS,
                              required=True)
    co_planning = body.integer("co_planning_hours_required", default=0, minimum=0, maximum=20)
    required_strands = body.array("required_strands", required=True, allowed=STRANDS)
    term_start = body.date("term_start_date", required=True)
    term_end = body.date("term_end_date", required=True)
    if term_end < term_start:
        bad("term_end_date must not be earlier than term_start_date")
    enrolled = body.integer("enrolled_student_count", required=True, minimum=1)

    school = find_school(school_partner_id)
    if calc.school_health(school)[0] == "INTAKE_SUSPENDED":
        raise ApiError("ERR_PARTNERSHIP_INTAKE_SUSPENDED",
                       "the school is not accepting new residencies")

    row = db.base_row()
    row.update({
        "school_partner_id": school["id"],
        "lead_artist_id": None,
        "title": title,
        "discipline": discipline,
        "grade_band": grade_band,
        "instruction_language": instruction_language,
        "contracted_session_count": contracted,
        "session_length_minutes": length,
        "budget_cents": budget_cents,
        "materials_stipend_cents": stipend,
        "collaboration_expectation": collaboration,
        "co_planning_hours_required": co_planning,
        "required_strands": required_strands,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "enrolled_student_count": enrolled,
        "status": "DRAFT",
        "sessions_unscheduled_count": 0,
        "_forfeited_extra": 0,
        "_ledger_init": False,
    })
    db.residencies[row["id"]] = row
    return response.ok(derive.residency_view(row), 201)


@bp.get("/residencies/<residency_id>")
def read_residency(residency_id):
    mw.auth()
    return response.ok(derive.residency_view(find_residency(residency_id)))


@bp.get("/residencies")
def list_residencies():
    mw.auth()
    limit, offset = mw.pagination()
    school_partner_id = mw.q_str("school_partner_id")
    lead_artist_id = mw.q_str("lead_artist_id")
    status = mw.q_enum("status", RESIDENCY_STATUSES)
    staffing = mw.q_enum("staffing_status", STAFFING_STATUSES)

    rows = db.ordered(list(db.residencies.values()))
    if school_partner_id:
        rows = [r for r in rows if r["school_partner_id"] == school_partner_id]
    if lead_artist_id:
        rows = [r for r in rows if r["lead_artist_id"] == lead_artist_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if staffing:
        rows = [r for r in rows if calc.staffing_status(r) == staffing]
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.residency_view(r) for r in page], limit, offset, total)


# --- lead artist ------------------------------------------------------------
@bp.post("/residencies/<residency_id>/lead-artist")
@mw.school_health_sync
def assign_lead_artist(residency_id):
    mw.auth("ProgramDirector", "RosterCoordinator")
    residency = find_residency(residency_id)
    body = Payload(request.get_json(silent=True))
    teaching_artist_id = body.string("teaching_artist_id", required=True)
    artist = find_artist(teaching_artist_id)

    if artist["vetting_status"] != "CLEARED" or calc.clearance_status(artist) != "CLEARED":
        raise ApiError("ERR_ARTIST_NOT_CLEARED",
                       "the nominated artist is not vetted and cleared")
    if artist["roster_status"] != "ACTIVE":
        raise ApiError("ERR_ARTIST_NOT_ON_ACTIVE_ROSTER",
                       "the nominated artist is not on the active roster")
    calc.capability_check(residency, artist)

    residency["lead_artist_id"] = artist["id"]
    db.touch(residency)
    return response.ok(derive.residency_view(residency))


# --- lifecycle --------------------------------------------------------------
@bp.post("/residencies/<residency_id>/status")
@mw.school_health_sync
def move_status(residency_id):
    mw.auth("ProgramDirector")
    residency = find_residency(residency_id)
    body = Payload(request.get_json(silent=True))
    target = body.enum("to_status", RESIDENCY_STATUSES, required=True)
    body.string("reason", default=None, min_len=0)

    current = residency["status"]
    if (current, target) not in RESIDENCY_TRANSITIONS:
        raise invalid_transition()

    if target == "APPROVED":
        _approve(residency)
    elif target == "ACTIVE" and current == "APPROVED":
        _activate(residency)
    elif target == "SUSPENDED":
        _suspend(residency)
    elif target == "ACTIVE" and current == "SUSPENDED":
        if calc.staffing_status(residency) == "LEAD_VACANT":
            raise invalid_transition("a residency with no lead artist cannot resume")
        residency["status"] = "ACTIVE"
    elif target == "COMPLETED":
        _complete(residency)
    elif target == "CLOSED":
        _close(residency)
    elif target == "CANCELLED":
        _cancel(residency)

    db.touch(residency)
    return response.ok(derive.residency_view(residency))


def _approve(residency):
    lead_id = residency.get("lead_artist_id")
    if lead_id is None:
        raise invalid_transition("a residency cannot be approved without a lead artist")
    lead = db.teaching_artists.get(lead_id)
    if lead is None or calc.clearance_status(lead) != "CLEARED":
        raise ApiError("ERR_ARTIST_NOT_CLEARED", "the lead artist does not hold a current clearance")
    if lead["vetting_status"] != "CLEARED" or lead["roster_status"] != "ACTIVE":
        raise ApiError("ERR_ARTIST_NOT_ON_ACTIVE_ROSTER",
                       "the lead artist is not on the active roster")
    school = calc.school_of_residency(residency)
    if school is not None and calc.school_health(school)[0] == "INTAKE_SUSPENDED":
        raise ApiError("ERR_PARTNERSHIP_INTAKE_SUSPENDED",
                       "the school is not accepting new commitments")
    residency["status"] = "APPROVED"
    residency["sessions_unscheduled_count"] = residency["contracted_session_count"]
    residency["_ledger_init"] = True


def _activate(residency):
    aligned = [p for p in plans_of_residency(residency["id"]) if p["status"] == "ALIGNED"]
    if not aligned:
        raise ApiError("ERR_NO_ALIGNED_LESSON_PLAN",
                       "the residency has no aligned lesson plan")
    covered = set()
    for plan in aligned:
        covered.update(plan.get("covered_strands") or [])
    missing = [s for s in residency["required_strands"] if s not in covered]
    if missing:
        raise ApiError("ERR_STANDARDS_COVERAGE_INCOMPLETE",
                       "aligned plans do not cover %s" % ", ".join(missing))
    residency["status"] = "ACTIVE"


def _suspend(residency):
    residency["status"] = "SUSPENDED"
    for session in db.ordered(calc.sessions_of_residency(residency["id"])):
        if session["status"] not in ("PLANNED", "CONFIRMED", "VACATED"):
            continue
        session["status"] = "CANCELLED_SCHOOL"
        session["cancel_reason"] = "RESIDENCY_DESCOPED"
        session["makeup_eligible"] = False
        session["encumbered_cents"] = 0
        db.touch(session)


def _complete(residency):
    ledger = calc.session_ledger(residency)
    if ledger["sessions_open_count"] != 0:
        raise ApiError("ERR_RESIDENCY_HAS_OPEN_SESSIONS",
                       "the residency still holds open sessions")
    outstanding = ledger["makeup_credits_outstanding"]
    unscheduled = ledger["sessions_unscheduled_count"]
    for session in db.ordered(calc.sessions_of_residency(residency["id"])):
        if (session["status"] in ("CANCELLED_SCHOOL", "CANCELLED_ARTIST")
                and session["makeup_eligible"] and not session["makeup_consumed"]):
            session["makeup_consumed"] = True
            db.touch(session)
    residency["_forfeited_extra"] = (residency.get("_forfeited_extra", 0)
                                     + unscheduled + outstanding)
    residency["sessions_unscheduled_count"] = 0
    residency["status"] = "COMPLETED"


def _close(residency):
    for voucher in calc.vouchers_of_residency(residency["id"]):
        if voucher["status"] in ("DRAFT", "SUBMITTED"):
            raise ApiError("ERR_RESIDENCY_HAS_OPEN_VOUCHERS",
                           "the residency still holds an unresolved payment voucher")
    if calc.budget_ledger(residency)["encumbered_cents"] != 0:
        raise ApiError("ERR_RESIDENCY_HAS_OPEN_VOUCHERS",
                       "the residency still holds encumbered funds")
    residency["status"] = "CLOSED"
    archive_plans(residency, ("SUBMITTED", "CHANGES_REQUESTED", "ALIGNED"))


def _cancel(residency):
    if calc.session_ledger(residency)["sessions_open_count"] != 0:
        raise ApiError("ERR_RESIDENCY_HAS_OPEN_SESSIONS",
                       "the residency still holds open sessions")
    residency["status"] = "CANCELLED"
    archive_plans(residency, ("SUBMITTED", "CHANGES_REQUESTED", "ALIGNED"))
