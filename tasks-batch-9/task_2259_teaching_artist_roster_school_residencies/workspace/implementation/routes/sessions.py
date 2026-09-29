"""Session scheduling, confirmation, substitute coverage, delivery and cancellation."""
from flask import Blueprint, request

import db
import middleware as mw
import response
from enums import (
    ARTIST_CANCEL_REASONS,
    CANCEL_REASONS,
    CANCELLED_SESSION_STATUSES,
    EVALUATION_TYPES,
    MAKEUP_ELIGIBLE_REASONS,
    SCHOOL_CANCEL_REASONS,
    SESSION_STATUSES,
    SESSION_TYPES,
)
from errors import ApiError
from routes.artists import find_artist
from routes.lesson_plans import find_plan
from routes.residencies import find_residency
from services import calc, derive
from validators import Payload, bad, minutes_of

bp = Blueprint("sessions", __name__)

EVALUATION_ROLE = {
    "OBSERVATION_RUBRIC": ("CurriculumSpecialist",),
    "TEACHER_SURVEY": ("SchoolLiaison",),
    "STUDENT_WORK_SAMPLE": ("SchoolLiaison",),
}

CANCEL_REASON_BY_ROLE = {
    "SchoolLiaison": SCHOOL_CANCEL_REASONS,
    "TeachingArtist": ("ARTIST_ILLNESS",),
    "RosterCoordinator": tuple(r for r in CANCEL_REASONS if r != "RESIDENCY_DESCOPED"),
}


def find_session(session_id):
    session = db.sessions.get(session_id)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "session %s not found" % session_id)
    return session


def invalid_transition(message="the requested transition is not declared from the current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def _residency_of(session):
    return find_residency(session["residency_id"])


def _school_liaison_gate(user_id, role, residency):
    """PRD 2.9 priority 6 for the entity-backed SchoolLiaison role."""
    if role != "SchoolLiaison":
        return
    if residency["school_partner_id"] != user_id:
        raise ApiError("ERR_ACTOR_NOT_RESOURCE_OWNER",
                       "the acting liaison does not host this residency")


def _check_stale_residency(residency, expected):
    if expected != residency["version"]:
        raise ApiError("ERR_STALE_RESIDENCY_VERSION",
                       "the residency has moved on to version %d" % residency["version"])


def _check_stale_session(session, expected):
    if expected != session["version"]:
        raise ApiError("ERR_STALE_SESSION_VERSION",
                       "the session has moved on to version %d" % session["version"])


def _clearance_covers(artist, session_date):
    expires_on = calc.clearance_expires_on(artist)
    return expires_on is not None and expires_on >= session_date


def _gate_cleared(artist):
    """Priority 9 — the child-safety screening gate."""
    if artist["vetting_status"] != "CLEARED" or calc.clearance_status(artist) != "CLEARED":
        raise ApiError("ERR_ARTIST_NOT_CLEARED", "the artist is not vetted and cleared")


def _gate_clearance_date(artist, session_date):
    """Priority 10 — the clearance must still cover the session's own date."""
    if not _clearance_covers(artist, session_date):
        raise ApiError("ERR_CLEARANCE_EXPIRED",
                       "the artist's clearance does not cover %s" % session_date)


def _gate_roster(artist):
    """Priority 11."""
    if artist["roster_status"] != "ACTIVE":
        raise ApiError("ERR_ARTIST_NOT_ON_ACTIVE_ROSTER",
                       "the artist is not on the active roster")


def _gate_blackout(residency, session_date):
    """Priority 23."""
    if calc.blackout_hit(residency["school_partner_id"], session_date):
        raise ApiError("ERR_CALENDAR_BLACKOUT",
                       "%s falls inside a school blackout window" % session_date)


def _budget_room(residency, delta):
    """Priority 27 — the encumbrance move must keep available_cents >= 0."""
    if delta > calc.budget_ledger(residency)["available_cents"]:
        raise ApiError("ERR_RESIDENCY_BUDGET_EXCEEDED",
                       "the residency budget cannot absorb this commitment")


# --- scheduling -------------------------------------------------------------
@bp.post("/sessions")
@mw.school_health_sync
def create_session():
    mw.auth("RosterCoordinator")
    body = Payload(request.get_json(silent=True))
    residency_id = body.string("residency_id", required=True)
    assigned_artist_id = body.string("assigned_artist_id", required=True)
    session_date = body.date("session_date", required=True)
    start_time = body.time("start_time", required=True, multiple_of_5=True)
    end_time = body.time("end_time", required=True)
    session_type = body.enum("session_type", SESSION_TYPES, default="REGULAR")
    lesson_plan_id = body.string("lesson_plan_id", default=None)
    makeup_for_session_id = body.string("makeup_for_session_id", default=None)
    expected_version = body.integer("expected_residency_version", required=True, minimum=0)
    start = minutes_of(start_time)
    end = minutes_of(end_time)
    if end <= start:
        bad("end_time must be strictly after start_time")

    # priority 5 — body references resolved in payload order
    residency = find_residency(residency_id)
    artist = find_artist(assigned_artist_id)
    if lesson_plan_id is not None:
        find_plan(lesson_plan_id)
    origin = find_session(makeup_for_session_id) if makeup_for_session_id is not None else None

    _check_stale_residency(residency, expected_version)          # 7
    _gate_cleared(artist)                                        # 9
    _gate_clearance_date(artist, session_date)                   # 10
    _gate_roster(artist)                                         # 11

    school = calc.school_of_residency(residency)                 # 12
    if school is not None:
        health = calc.school_health(school)[0]
        if health == "INTAKE_SUSPENDED":
            raise ApiError("ERR_PARTNERSHIP_INTAKE_SUSPENDED",
                           "the school is not accepting new sessions")
        if (health == "WATCH"
                and calc.staffing_status(residency) != "STAFFED"
                and session_type != "MAKEUP"):
            raise ApiError("ERR_PARTNERSHIP_HEALTH_GATE",
                           "the partnership is on watch and the residency is not fully staffed")

    calc.capability_check(residency, artist)                     # 17

    if session_type == "MAKEUP":                                 # 19
        if (origin is None
                or origin["residency_id"] != residency["id"]
                or origin["status"] not in CANCELLED_SESSION_STATUSES
                or not origin["makeup_eligible"]
                or origin["makeup_consumed"]):
            raise ApiError("ERR_MAKEUP_CREDIT_UNAVAILABLE",
                           "no unconsumed make-up credit matches this request")

    if not (residency["term_start_date"] <= session_date <= residency["term_end_date"]):
        raise ApiError("ERR_SESSION_OUTSIDE_RESIDENCY_TERM",  # 22
                       "%s lies outside the residency term" % session_date)

    _gate_blackout(residency, session_date)                      # 23
    calc.check_artist_intervals(residency, artist["id"], session_date, start, end)   # 24
    calc.check_school_capacity(residency, session_date, start, end)                  # 25

    ledger = calc.session_ledger(residency)                      # 26
    if session_type == "REGULAR":
        if ledger["sessions_unscheduled_count"] < 1:
            raise ApiError("ERR_SESSION_ALLOTMENT_EXHAUSTED",
                           "no contracted allotment remains")
    elif ledger["makeup_credits_outstanding"] < 1:
        raise ApiError("ERR_SESSION_ALLOTMENT_EXHAUSTED",
                       "no make-up credit remains")

    row = db.base_row()
    row.update({
        "residency_id": residency["id"],
        "assigned_artist_id": artist["id"],
        "vacated_artist_id": None,
        "lesson_plan_id": lesson_plan_id,
        "makeup_for_session_id": makeup_for_session_id if session_type == "MAKEUP" else None,
        "payment_voucher_id": None,
        "session_type": session_type,
        "is_substitute": False,
        "session_date": session_date,
        "start_time": start_time,
        "end_time": end_time,
        "classroom_teacher_name": None,
        "co_planning_completed": False,
        "status": "PLANNED",
        "cancel_reason": None,
        "makeup_eligible": False,
        "makeup_consumed": False,
        "students_present_count": None,
        "minutes_delivered": None,
        "travel_miles": None,
        "materials_spend_cents": None,
        "encumbered_cents": 0,
        "fee_cents": None,
        "travel_reimbursement_cents": None,
        "materials_reimbursement_cents": None,
        "payable_cents": None,
    })
    db.sessions[row["id"]] = row

    if session_type == "REGULAR":
        residency["sessions_unscheduled_count"] = residency["sessions_unscheduled_count"] - 1
    else:
        origin["makeup_consumed"] = True
        db.touch(origin)
    db.touch(residency)
    return response.ok(derive.session_view(row), 201)


@bp.get("/sessions/<session_id>")
def read_session(session_id):
    mw.auth()
    return response.ok(derive.session_view(find_session(session_id)))


@bp.get("/sessions")
def list_sessions():
    mw.auth()
    limit, offset = mw.pagination()
    residency_id = mw.q_str("residency_id")
    assigned_artist_id = mw.q_str("assigned_artist_id")
    vacated_artist_id = mw.q_str("vacated_artist_id")
    lesson_plan_id = mw.q_str("lesson_plan_id")
    makeup_for_session_id = mw.q_str("makeup_for_session_id")
    payment_voucher_id = mw.q_str("payment_voucher_id")
    status = mw.q_enum("status", SESSION_STATUSES)
    date_from = mw.q_date("session_date_from")
    date_to = mw.q_date("session_date_to")

    rows = db.ordered(list(db.sessions.values()))
    if residency_id:
        rows = [s for s in rows if s["residency_id"] == residency_id]
    if assigned_artist_id:
        rows = [s for s in rows if s["assigned_artist_id"] == assigned_artist_id]
    if vacated_artist_id:
        rows = [s for s in rows if s["vacated_artist_id"] == vacated_artist_id]
    if lesson_plan_id:
        rows = [s for s in rows if s["lesson_plan_id"] == lesson_plan_id]
    if makeup_for_session_id:
        rows = [s for s in rows if s["makeup_for_session_id"] == makeup_for_session_id]
    if payment_voucher_id:
        rows = [s for s in rows if s["payment_voucher_id"] == payment_voucher_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    if date_from:
        rows = [s for s in rows if s["session_date"] >= date_from]
    if date_to:
        rows = [s for s in rows if s["session_date"] <= date_to]
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.session_view(s) for s in page], limit, offset, total)


# --- confirmation -----------------------------------------------------------
@bp.post("/sessions/<session_id>/confirm")
@mw.school_health_sync
def confirm_session(session_id):
    user_id, role = mw.auth("SchoolLiaison", "RosterCoordinator")
    session = find_session(session_id)
    body = Payload(request.get_json(silent=True))
    teacher_name = body.string("classroom_teacher_name", required=True)
    co_planning = body.boolean("co_planning_completed", required=True)

    residency = _residency_of(session)
    _school_liaison_gate(user_id, role, residency)               # 6

    if residency["status"] != "ACTIVE":                           # 8
        raise invalid_transition("the residency is not ACTIVE")
    if session["status"] != "PLANNED":
        raise invalid_transition()

    artist = db.teaching_artists.get(session["assigned_artist_id"])
    if artist is None:                                            # 9
        raise ApiError("ERR_ARTIST_NOT_CLEARED", "the session has no assigned artist")
    _gate_cleared(artist)
    _gate_clearance_date(artist, session["session_date"])         # 10
    _gate_roster(artist)                                          # 11

    plan = db.lesson_plans.get(session["lesson_plan_id"]) if session["lesson_plan_id"] else None
    if plan is None or plan["status"] != "ALIGNED":               # 13
        raise ApiError("ERR_NO_ALIGNED_LESSON_PLAN",
                       "the session does not name an aligned lesson plan")

    if residency["collaboration_expectation"] == "CO_TEACH" and not co_planning:   # 21
        raise ApiError("ERR_CO_PLANNING_INCOMPLETE",
                       "a co-taught residency requires completed co-planning")

    _gate_blackout(residency, session["session_date"])            # 23

    amount = calc.full_length_fee(residency, session, artist=artist)
    _budget_room(residency, amount - (session["encumbered_cents"] or 0))           # 27

    session["classroom_teacher_name"] = teacher_name
    session["co_planning_completed"] = co_planning
    session["status"] = "CONFIRMED"
    session["encumbered_cents"] = amount
    db.touch(session)
    db.touch(residency)
    return response.ok(derive.session_view(session))


# --- substitute coverage ----------------------------------------------------
@bp.post("/sessions/<session_id>/reassign")
@mw.school_health_sync
def reassign_session(session_id):
    mw.auth("RosterCoordinator")
    session = find_session(session_id)
    body = Payload(request.get_json(silent=True))
    substitute_id = body.string("substitute_artist_id", required=True)
    expected_version = body.integer("expected_session_version", required=True, minimum=0)
    if session["status"] == "CONFIRMED" and substitute_id == session["assigned_artist_id"]:
        bad("substitute_artist_id must differ from the current assigned_artist_id")

    substitute = find_artist(substitute_id)                       # 5
    _check_stale_session(session, expected_version)               # 7
    if session["status"] not in ("VACATED", "CONFIRMED"):         # 8
        raise invalid_transition()

    residency = _residency_of(session)
    if calc.clearance_status(substitute) != "CLEARED":            # 9
        raise ApiError("ERR_ARTIST_NOT_CLEARED",
                       "the substitute does not hold a current clearance")
    _gate_clearance_date(substitute, session["session_date"])     # 10
    if substitute["vetting_status"] != "CLEARED" or substitute["roster_status"] != "ACTIVE":
        raise ApiError("ERR_ARTIST_NOT_ON_ACTIVE_ROSTER",         # 11
                       "the substitute is not on the active roster")
    calc.capability_check(residency, substitute)                  # 17

    start = minutes_of(session["start_time"])
    end = minutes_of(session["end_time"])
    calc.check_artist_intervals(residency, substitute["id"], session["session_date"],
                               start, end, exclude_id=session["id"])               # 24
    calc.check_school_capacity(residency, session["session_date"], start, end,
                              exclude_id=session["id"])                            # 25

    held = session["encumbered_cents"] or 0
    amount = calc.session_fee(residency, substitute, residency["session_length_minutes"],
                              is_substitute=True,
                              is_lead=(substitute["id"] == residency["lead_artist_id"]))
    _budget_room(residency, amount - held)                        # 27

    if session["status"] == "CONFIRMED":
        session["vacated_artist_id"] = session["assigned_artist_id"]
    session["assigned_artist_id"] = substitute["id"]
    session["is_substitute"] = True
    session["status"] = "CONFIRMED"
    session["encumbered_cents"] = amount
    db.touch(session)
    db.touch(residency)
    return response.ok(derive.session_view(session))


# --- cancellation -----------------------------------------------------------
@bp.post("/sessions/<session_id>/cancel")
@mw.school_health_sync
def cancel_session(session_id):
    user_id, role = mw.auth("SchoolLiaison", "RosterCoordinator", "TeachingArtist")
    session = find_session(session_id)
    body = Payload(request.get_json(silent=True))
    reason = body.enum("cancel_reason", CANCEL_REASONS, required=True)
    body.string("note", default=None, min_len=0)

    residency = _residency_of(session)
    if role == "TeachingArtist" and user_id != session["assigned_artist_id"]:      # 6
        raise ApiError("ERR_ACTOR_NOT_RESOURCE_OWNER",
                       "only the assigned artist may cancel this session")
    _school_liaison_gate(user_id, role, residency)

    artist_side = reason in ARTIST_CANCEL_REASONS
    if session["status"] not in ("PLANNED", "CONFIRMED", "VACATED"):               # 8
        raise invalid_transition()
    if artist_side and session["status"] == "VACATED":
        raise invalid_transition("a vacated session has no artist to cancel it")

    permitted = CANCEL_REASON_BY_ROLE.get(role, ())                                # 20
    if reason == "RESIDENCY_DESCOPED" or reason not in permitted:
        raise ApiError("ERR_CANCEL_REASON_NOT_PERMITTED",
                       "role %s may not cancel with reason %s" % (role, reason))

    holder = db.teaching_artists.get(session["assigned_artist_id"])
    session["status"] = "CANCELLED_ARTIST" if artist_side else "CANCELLED_SCHOOL"
    session["cancel_reason"] = reason
    session["makeup_eligible"] = reason in MAKEUP_ELIGIBLE_REASONS
    session["encumbered_cents"] = 0
    db.touch(session)
    db.touch(residency)

    if artist_side:
        derive.cascade_b(session, holder)
    return response.ok(derive.session_view(session))


# --- delivery ---------------------------------------------------------------
@bp.post("/sessions/<session_id>/deliver")
@mw.school_health_sync
def deliver_session(session_id):
    user_id, _role = mw.auth("TeachingArtist")
    session = find_session(session_id)
    body = Payload(request.get_json(silent=True))
    students_present = body.integer("students_present_count", required=True, minimum=0)
    minutes_delivered = body.integer("minutes_delivered", required=True, minimum=0)
    travel_miles = body.number("travel_miles", required=True, minimum=0, decimals=1)
    materials_spend = body.integer("materials_spend_cents", required=True, minimum=0)

    if user_id != session["assigned_artist_id"]:                  # 6
        raise ApiError("ERR_ACTOR_NOT_RESOURCE_OWNER",
                       "only the assigned artist may report this delivery")

    residency = _residency_of(session)
    if session["status"] != "CONFIRMED" or residency["status"] != "ACTIVE":        # 8
        raise invalid_transition()

    artist = db.teaching_artists.get(session["assigned_artist_id"])
    if artist is None or not _clearance_covers(artist, session["session_date"]):   # 10
        raise ApiError("ERR_CLEARANCE_EXPIRED",
                       "the artist's clearance does not cover %s" % session["session_date"])

    if minutes_delivered < calc.min_delivery_minutes(residency):                   # 19
        raise ApiError("ERR_SESSION_UNDERDELIVERED",
                       "at least %d minutes must be taught"
                       % calc.min_delivery_minutes(residency))

    fee = calc.session_fee(residency, artist, minutes_delivered,
                           is_substitute=bool(session["is_substitute"]),
                           is_lead=calc.is_lead_session(residency, session))
    travel, materials = calc.session_reimbursement(travel_miles, materials_spend)
    payable = fee + travel + materials
    held = session["encumbered_cents"] or 0
    _budget_room(residency, payable - held)                                        # 27

    session["students_present_count"] = students_present
    session["minutes_delivered"] = minutes_delivered
    session["travel_miles"] = travel_miles
    session["materials_spend_cents"] = materials_spend
    session["fee_cents"] = fee
    session["travel_reimbursement_cents"] = travel
    session["materials_reimbursement_cents"] = materials
    session["payable_cents"] = payable
    session["encumbered_cents"] = payable
    session["status"] = "DELIVERED"
    db.touch(session)
    db.touch(residency)

    before = (artist["reliability_bps_rolling"], artist["reliability_bps_program_year"],
              artist["roster_tier_effective"])
    calc.recompute_reliability(artist)
    calc.recompute_tier(artist)
    if before != (artist["reliability_bps_rolling"], artist["reliability_bps_program_year"],
                  artist["roster_tier_effective"]):
        db.touch(artist)

    derive.invalidate_reports(residency["id"], session["session_date"])
    return response.ok(derive.session_view(session))


# --- evaluation records -----------------------------------------------------
@bp.post("/sessions/<session_id>/evaluations")
def create_evaluation(session_id):
    user_id, role = mw.auth("CurriculumSpecialist", "SchoolLiaison")
    raw = request.get_json(silent=True)
    if isinstance(raw, dict):
        declared = raw.get("evaluation_type")
        if declared in EVALUATION_TYPES and role not in EVALUATION_ROLE[declared]:
            raise ApiError("ERR_UNAUTHORIZED",
                           "role %s may not attach a %s record" % (role, declared))

    session = find_session(session_id)
    body = Payload(raw)
    evaluation_type = body.enum("evaluation_type", EVALUATION_TYPES, required=True)
    evaluator_user_id = body.string("evaluator_user_id", required=True)
    engagement = body.integer("rubric_engagement_score", minimum=1, maximum=4)
    craft = body.integer("rubric_craft_score", minimum=1, maximum=4)
    evidence = body.integer("rubric_standards_evidence_score", minimum=1, maximum=4)
    survey = body.integer("teacher_survey_score", minimum=1, maximum=5)
    artifacts = body.integer("student_work_artifact_count", minimum=0)

    if evaluation_type == "OBSERVATION_RUBRIC":
        if engagement is None or craft is None or evidence is None:
            bad("an observation rubric requires all three rubric scores")
        if survey is not None or artifacts is not None:
            bad("an observation rubric must not carry survey or artifact fields")
    elif evaluation_type == "TEACHER_SURVEY":
        if survey is None:
            bad("a teacher survey requires teacher_survey_score")
        if engagement is not None or craft is not None or evidence is not None \
                or artifacts is not None:
            bad("a teacher survey must not carry rubric or artifact fields")
    else:
        if artifacts is None:
            bad("a student work sample requires student_work_artifact_count")
        if engagement is not None or craft is not None or evidence is not None \
                or survey is not None:
            bad("a student work sample must not carry rubric or survey fields")

    residency = _residency_of(session)
    _school_liaison_gate(user_id, role, residency)               # 6

    row = db.base_row(versioned=False)
    row.update({
        "session_id": session["id"],
        "evaluation_type": evaluation_type,
        "evaluator_user_id": evaluator_user_id,
        "rubric_engagement_score": engagement,
        "rubric_craft_score": craft,
        "rubric_standards_evidence_score": evidence,
        "teacher_survey_score": survey,
        "student_work_artifact_count": artifacts,
    })
    db.evaluation_records[row["id"]] = row
    return response.ok(derive.evaluation_view(row), 201)


@bp.get("/sessions/<session_id>/evaluations")
def list_evaluations(session_id):
    mw.auth()
    session = find_session(session_id)
    limit, offset = mw.pagination()
    evaluation_type = mw.q_enum("evaluation_type", EVALUATION_TYPES)
    rows = calc.evaluations_of_session(session["id"])
    if evaluation_type:
        rows = [e for e in rows if e["evaluation_type"] == evaluation_type]
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.evaluation_view(e) for e in page], limit, offset, total)
