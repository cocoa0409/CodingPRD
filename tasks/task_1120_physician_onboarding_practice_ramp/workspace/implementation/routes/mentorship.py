"""Mentorship assignment and check-in endpoints (PRD 3.9)."""

from flask import Blueprint, request

import domain as D
from db import store, new_record, new_point_record, bump
from errors import (
    ApiError, ERR_VALIDATION, ERR_CASE_NOT_FOUND, ERR_PHYSICIAN_NOT_FOUND,
    ERR_MENTORSHIP_NOT_FOUND, ERR_STALE_VERSION, ERR_MENTOR_IS_MENTEE,
    ERR_MENTOR_NOT_ACTIVE_PHYSICIAN, ERR_MENTOR_SPECIALTY_MISMATCH,
    ERR_MENTORSHIP_NOT_ACTIVE, ERR_CHECKINS_INCOMPLETE,
    ERR_CHECKIN_ALREADY_RECORDED, ERR_CHECKIN_OUT_OF_ORDER,
)
from middleware import get_context, require_role, forbid
from response import success_object, paginate

bp = Blueprint("mentorship", __name__)


def _get_assignment(aid):
    assignment = store.assignments.get(aid)
    if assignment is None:
        raise ApiError(ERR_MENTORSHIP_NOT_FOUND, 404, "MentorshipAssignment not found")
    return assignment


@bp.route("/onboarding/mentorship-assignments", methods=["POST"])
def create_assignment():
    _uid, role = get_context()
    require_role(role, ["OnboardingDirector"])
    body = D.get_body()
    case_id = D.req_str(body, "onboarding_case_id")
    mentor_physician_id = D.req_str(body, "mentor_physician_id")
    expected_version = D.req_int(body, "expected_onboarding_case_version")

    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "OnboardingCase not found")
    mentor = store.physicians.get(mentor_physician_id)
    if mentor is None:
        raise ApiError(ERR_PHYSICIAN_NOT_FOUND, 404, "Mentor physician not found")
    if expected_version != case["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_onboarding_case_version does not match the case's current version")

    # Mentor rules, pinned in order.
    if mentor_physician_id == case["physician_id"]:
        raise ApiError(ERR_MENTOR_IS_MENTEE, 422,
                       "The mentor may not be the mentee")
    if mentor["status"] != "ACTIVE":
        raise ApiError(ERR_MENTOR_NOT_ACTIVE_PHYSICIAN, 422,
                       "The mentor must be an ACTIVE physician")
    mentee = store.physicians.get(case["physician_id"])
    if mentee is not None and mentor["specialty"] != mentee["specialty"]:
        raise ApiError(ERR_MENTOR_SPECIALTY_MISMATCH, 422,
                       "The mentor's specialty must match the mentee's")

    for existing in D.assignments_of_case(case_id):
        if existing["status"] == "ACTIVE":
            existing["status"] = "SUPERSEDED"
            bump(existing)

    rec = new_record()
    rec.update({
        "onboarding_case_id": case_id,
        "mentor_physician_id": mentor_physician_id,
        "checkins_recorded": 0,
        "escalated": False,
        "status": "ACTIVE",
    })
    store.assignments[rec["id"]] = rec
    bump(case)
    return success_object(D.serialize_assignment(rec), status=201)


@bp.route("/onboarding/mentorship-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    get_context()
    return success_object(D.serialize_assignment(_get_assignment(aid)))


@bp.route("/onboarding/mentorship-assignments", methods=["GET"])
def list_assignments():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    mentor_id = request.args.get("mentor_physician_id")
    status = request.args.get("status")
    records = sorted(store.assignments.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if mentor_id is not None:
        records = [r for r in records if r["mentor_physician_id"] == mentor_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([D.serialize_assignment(r) for r in records], request.args)


@bp.route("/onboarding/mentorship-assignments/<aid>/complete", methods=["POST"])
def complete_assignment(aid):
    _uid, role = get_context()
    require_role(role, ["OnboardingDirector"])
    assignment = _get_assignment(aid)
    if assignment["status"] != "ACTIVE":
        raise ApiError(ERR_MENTORSHIP_NOT_ACTIVE, 409,
                       "Only an ACTIVE assignment can be completed")
    if assignment["checkins_recorded"] != len(D.DAY_MARKERS):
        raise ApiError(ERR_CHECKINS_INCOMPLETE, 422,
                       "All five check-ins must be recorded before completion")
    assignment["status"] = "COMPLETED"
    bump(assignment)
    return success_object(D.serialize_assignment(assignment))


@bp.route("/onboarding/mentorship-assignments/<aid>/check-ins", methods=["POST"])
def record_checkin(aid):
    uid, role = get_context()
    require_role(role, ["MentorPhysician"])
    assignment = _get_assignment(aid)
    if assignment["mentor_physician_id"] != uid:
        forbid("A mentor may record check-ins only on their own assignments")
    body = D.get_body()
    day_marker = D.req_enum(body, "day_marker", D.DAY_MARKERS)
    sentiment = D.req_enum(body, "sentiment", D.SENTIMENTS)
    notes = D.opt_str(body, "notes")
    if assignment["status"] != "ACTIVE":
        raise ApiError(ERR_MENTORSHIP_NOT_ACTIVE, 409,
                       "Check-ins can be recorded only on an ACTIVE assignment")
    existing = D.checkins_of_assignment(aid)
    recorded_markers = {c["day_marker"] for c in existing}
    # Unique-then-ordered: the already-recorded check runs first.
    if day_marker in recorded_markers:
        raise ApiError(ERR_CHECKIN_ALREADY_RECORDED, 409,
                       "This day_marker has already been recorded")
    expected = D.DAY_MARKERS[len(recorded_markers)] \
        if len(recorded_markers) < len(D.DAY_MARKERS) else None
    if day_marker != expected:
        raise ApiError(ERR_CHECKIN_OUT_OF_ORDER, 422,
                       "day_marker must be the immediate next marker in D30..D365 order")

    rec = new_point_record()
    rec.update({
        "mentorship_id": aid,
        "day_marker": day_marker,
        "sentiment": sentiment,
        "occurred_on": D.clock_date().isoformat(),
        "notes": notes,
    })
    store.checkins[rec["id"]] = rec
    assignment["checkins_recorded"] += 1
    if sentiment == "CRISIS":
        assignment["escalated"] = True
    bump(assignment)
    case = store.cases.get(assignment["onboarding_case_id"])
    if case is not None:
        if sentiment == "CRISIS":
            case["at_risk"] = True
        bump(case)
    return success_object(D.serialize_checkin(rec), status=201)


@bp.route("/onboarding/mentorship-assignments/<aid>/check-ins", methods=["GET"])
def list_checkins(aid):
    get_context()
    _get_assignment(aid)
    records = sorted(
        D.checkins_of_assignment(aid),
        key=lambda r: (D.DAY_MARKERS.index(r["day_marker"]), r["_seq"]),
    )
    return paginate([D.serialize_checkin(r) for r in records], request.args)
