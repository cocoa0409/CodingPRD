"""Lesson plans and curriculum alignment against the state arts standards."""
from flask import Blueprint, request

import clock
import db
import middleware as mw
import response
from enums import LESSON_PLAN_STATUSES, REVIEW_DECISIONS
from errors import ApiError
from routes.residencies import find_residency
from routes.standards import resolve_codes
from services import calc, derive
from validators import Payload

bp = Blueprint("lesson_plans", __name__)


def find_plan(plan_id):
    plan = db.lesson_plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_LESSON_PLAN_NOT_FOUND", "lesson plan %s not found" % plan_id)
    return plan


def invalid_transition(message="the requested transition is not declared from the current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def strands_of(standards):
    """Distinct strand values in order of first appearance."""
    out = []
    for standard in standards:
        if standard["strand"] not in out:
            out.append(standard["strand"])
    return out


def round_limit_check(plan):
    if plan["revision_round"] >= calc.ADAPTATION_ROUND_LIMIT:
        raise ApiError("ERR_ADAPTATION_ROUND_LIMIT",
                       "the plan has already used %d adaptation rounds"
                       % calc.ADAPTATION_ROUND_LIMIT)


# --- submission -------------------------------------------------------------
@bp.post("/lesson-plans")
def create_plan():
    user_id, role = mw.auth("TeachingArtist", "RosterCoordinator")
    body = Payload(request.get_json(silent=True))
    residency_id = body.string("residency_id", required=True)
    title = body.string("title", required=True)
    sequence_no = body.integer("session_sequence_no", required=True, minimum=1, maximum=60)
    standard_codes = body.array("standard_codes", required=True)
    materials_list = body.string("materials_list", default=None, min_len=0)
    adaptation_summary = body.string("adaptation_summary", default=None, min_len=0)

    residency = find_residency(residency_id)
    standards = resolve_codes(standard_codes)

    if role == "TeachingArtist":
        if user_id not in db.teaching_artists:
            raise ApiError("ERR_ACTOR_NOT_RESOURCE_OWNER",
                           "the acting identifier is not a rostered teaching artist")
        author_artist_id = user_id
    else:
        author_artist_id = residency.get("lead_artist_id")

    for existing in db.lesson_plans.values():
        if (existing["residency_id"] == residency["id"]
                and existing["session_sequence_no"] == sequence_no):
            raise ApiError("ERR_DUPLICATE_SEQUENCE_NO",
                           "sequence number %d is already used in this residency" % sequence_no)

    row = db.base_row()
    row.update({
        "residency_id": residency["id"],
        "author_artist_id": author_artist_id,
        "title": title,
        "session_sequence_no": sequence_no,
        "standard_codes": standard_codes,
        "materials_list": materials_list,
        "adaptation_summary": adaptation_summary,
        "status": "SUBMITTED",
        "revision_round": 0,
        "covered_strands": strands_of(standards),
        "reviewer_note": None,
        "reviewer_user_id": None,
        "aligned_on": None,
    })
    db.lesson_plans[row["id"]] = row
    return response.ok(derive.lesson_plan_view(row), 201)


@bp.get("/lesson-plans/<plan_id>")
def read_plan(plan_id):
    mw.auth()
    return response.ok(derive.lesson_plan_view(find_plan(plan_id)))


@bp.get("/lesson-plans")
def list_plans():
    mw.auth()
    limit, offset = mw.pagination()
    residency_id = mw.q_str("residency_id")
    author_artist_id = mw.q_str("author_artist_id")
    status = mw.q_enum("status", LESSON_PLAN_STATUSES)

    rows = db.ordered(list(db.lesson_plans.values()))
    if residency_id:
        rows = [p for p in rows if p["residency_id"] == residency_id]
    if author_artist_id:
        rows = [p for p in rows if p["author_artist_id"] == author_artist_id]
    if status:
        rows = [p for p in rows if p["status"] == status]
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.lesson_plan_view(p) for p in page], limit, offset, total)


# --- curriculum review ------------------------------------------------------
@bp.post("/lesson-plans/<plan_id>/review")
def review_plan(plan_id):
    user_id, _role = mw.auth("CurriculumSpecialist")
    plan = find_plan(plan_id)
    body = Payload(request.get_json(silent=True))
    decision = body.enum("decision", REVIEW_DECISIONS, required=True)
    reviewer_note = body.string("reviewer_note", default=None, min_len=0)

    current = plan["status"]
    if decision == "ALIGN":
        if current != "SUBMITTED":
            raise invalid_transition()
        residency = find_residency(plan["residency_id"])
        standards = resolve_codes(plan["standard_codes"])
        for standard in standards:
            if standard["discipline"] != residency["discipline"]:
                raise ApiError("ERR_DISCIPLINE_MISMATCH",
                               "standard %s is not a %s standard"
                               % (standard["code"], residency["discipline"]))
        for standard in standards:
            if standard["grade_band"] != residency["grade_band"]:
                raise ApiError("ERR_GRADE_BAND_MISMATCH",
                               "standard %s is not a %s standard"
                               % (standard["code"], residency["grade_band"]))
        covered = strands_of(standards)
        if not covered:
            raise ApiError("ERR_NO_ALIGNED_LESSON_PLAN", "the plan covers no strand")
        plan["covered_strands"] = covered
        plan["status"] = "ALIGNED"
        plan["aligned_on"] = clock.logical_iso()
        plan["reviewer_user_id"] = user_id
    else:
        if current not in ("SUBMITTED", "ALIGNED"):
            raise invalid_transition()
        if current == "ALIGNED":
            for session in db.sessions.values():
                if (session["lesson_plan_id"] == plan["id"]
                        and session["status"] == "DELIVERED"):
                    raise invalid_transition(
                        "the plan has already been taught in a delivered session")
        round_limit_check(plan)
        plan["status"] = "CHANGES_REQUESTED"
        plan["revision_round"] = plan["revision_round"] + 1
        plan["reviewer_note"] = reviewer_note
        plan["reviewer_user_id"] = user_id
        if current == "ALIGNED":
            plan["aligned_on"] = None

    db.touch(plan)
    return response.ok(derive.lesson_plan_view(plan))


# --- adaptation resubmission ------------------------------------------------
@bp.post("/lesson-plans/<plan_id>/revisions")
def revise_plan(plan_id):
    user_id, role = mw.auth("TeachingArtist", "RosterCoordinator")
    plan = find_plan(plan_id)
    body = Payload(request.get_json(silent=True))
    adaptation_summary = body.string("adaptation_summary", required=True)
    standard_codes = body.array("standard_codes", default=None)
    title = body.string("title", default=None)
    materials_list = body.string("materials_list", default=None, min_len=0)

    standards = resolve_codes(standard_codes) if standard_codes is not None else None

    if role == "TeachingArtist" and user_id != plan["author_artist_id"]:
        raise ApiError("ERR_ACTOR_NOT_RESOURCE_OWNER",
                       "only the authoring artist may resubmit this plan")
    if plan["status"] != "CHANGES_REQUESTED":
        raise invalid_transition()
    round_limit_check(plan)

    plan["adaptation_summary"] = adaptation_summary
    if standard_codes is not None:
        plan["standard_codes"] = standard_codes
        plan["covered_strands"] = strands_of(standards)
    if title is not None:
        plan["title"] = title
    if materials_list is not None:
        plan["materials_list"] = materials_list
    plan["status"] = "SUBMITTED"
    db.touch(plan)
    return response.ok(derive.lesson_plan_view(plan))
