"""Enrollments: create / list / get / start / complete / cancel / reattempt /
void."""

from flask import Blueprint, g, request

from db import store, base_record, touch, clock_now
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_CONTENT_NOT_APPROVED,
                    ERR_SESSION_NOT_SCHEDULED, ERR_SESSION_FULL,
                    ERR_REGISTRATION_INACTIVE, ERR_REGISTRATION_TERMINATED,
                    ERR_DUPLICATE_ENROLLMENT, ERR_ENROLLMENT_INVALID_STATE,
                    ERR_ENROLLMENT_EXPIRED, ERR_MAX_ATTEMPTS_REACHED,
                    ERR_OWNERSHIP_REQUIRED)
from middleware import require_roles, actor, json_body, require_fields
from response import success, paginate
from services import (get_or_404, by_seq, active_seat_holders,
                      sync_session_seats, cancel_enrollment, complete_enrollment,
                      void_enrollment, enrollment_expires_at,
                      recompute_plans_for_rep, MAX_ATTEMPTS)
from util import view

bp = Blueprint("enrollments", __name__)

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


def _check_rep_active(rep):
    if rep["registration_status"] == "INACTIVE_CE":
        raise ApiError(ERR_REGISTRATION_INACTIVE, 409,
                       "Representative registration is INACTIVE_CE")
    if rep["registration_status"] == "TERMINATED":
        raise ApiError(ERR_REGISTRATION_TERMINATED, 409,
                       "Representative registration is TERMINATED")


def _check_ownership(enrollment):
    if g.actor_user_id != enrollment["rep_id"]:
        raise ApiError(ERR_OWNERSHIP_REQUIRED, 403,
                       "A RegisteredRep may act only on their own enrollments")


def _check_content_approved(enrollment):
    content = store.contents[enrollment["content_id"]]
    if content["content_status"] != "APPROVED":
        raise ApiError(ERR_CONTENT_NOT_APPROVED, 409,
                       "Enrollment content is not APPROVED")
    return content


@bp.post("/enrollments")
@require_roles("TrainingAdmin")
def create_enrollment():
    body = json_body()
    # Existence: body FKs in declared order — rep_id, content_id, session_id.
    rep = None
    content_ref = None
    session = None
    if body.get("rep_id") is not None:
        rep = get_or_404(store.representatives, body["rep_id"], "Representative")
    if body.get("content_id") is not None:
        content_ref = get_or_404(store.contents, body["content_id"],
                                 "TrainingContent")
    if body.get("session_id") is not None:
        session = get_or_404(store.sessions, body["session_id"], "CourseSession")
    # Shape: rep required; exactly one reference, lawful for the delivery format.
    require_fields(body, "rep_id")
    has_content = body.get("content_id") is not None
    has_session = body.get("session_id") is not None
    if not has_content and not has_session:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Exactly one of content_id or session_id is required")
    if has_session:
        effective_content = store.contents[session["content_id"]]
        if effective_content["delivery_format"] == "ELEARNING":
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "A session reference is not valid for ELEARNING content")
    else:
        effective_content = content_ref
        if effective_content["delivery_format"] == "INSTRUCTOR_LED":
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "INSTRUCTOR_LED content requires a session_id")
    # Target-state guards: content APPROVED, then session SCHEDULED.
    if effective_content["content_status"] != "APPROVED":
        raise ApiError(ERR_CONTENT_NOT_APPROVED, 409,
                       "Enrollments may be created only for APPROVED content")
    if session is not None and session["session_status"] != "SCHEDULED":
        raise ApiError(ERR_SESSION_NOT_SCHEDULED, 409,
                       "Session is not SCHEDULED")
    # Registration standing.
    _check_rep_active(rep)
    # Uniqueness: no second active enrollment for (rep_id, content_id).
    for e in store.enrollments.values():
        if e["rep_id"] == rep["id"] \
                and e["content_id"] == effective_content["id"] \
                and e["enrollment_status"] in ("ENROLLED", "IN_PROGRESS"):
            raise ApiError(ERR_DUPLICATE_ENROLLMENT, 409,
                           "Representative already holds an active enrollment "
                           "for this content")
    # Referential: an accompanying content_id must match the session's content.
    if has_content and has_session and content_ref["id"] != session["content_id"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "content_id does not match the session's content")
    # Capacity gate for session-linked enrollment.
    if session is not None \
            and active_seat_holders(session["id"]) >= session["capacity"]:
        raise ApiError(ERR_SESSION_FULL, 409, "Session has no available seats")
    created = clock_now()
    rec = base_record()
    rec.update({
        "rep_id": rep["id"],
        "content_id": effective_content["id"],
        "session_id": session["id"] if session is not None else None,
        "enrollment_status": "ENROLLED",
        "attempt_count": 0,
        "last_score": None,
        "expires_at": enrollment_expires_at(created),
        "completed_at": None,
    })
    store.enrollments[rec["id"]] = rec
    if session is not None:
        sync_session_seats(session)
    return success(view(rec), status=201)


@bp.get("/enrollments")
@require_roles(*ANY)
def list_enrollments():
    items = by_seq(store.enrollments.values())
    for param in ("rep_id", "content_id", "session_id", "enrollment_status"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e[param] == value]
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    page, pagination = paginate(items)
    return success([view(e) for e in page], is_list=True, pagination=pagination)


@bp.get("/enrollments/<enrollmentId>")
@require_roles(*ANY)
def get_enrollment(enrollmentId):
    rec = get_or_404(store.enrollments, enrollmentId, "Enrollment")
    return success(view(rec))


@bp.post("/enrollments/<enrollmentId>/start")
@require_roles("RegisteredRep")
def start_enrollment(enrollmentId):
    rec = get_or_404(store.enrollments, enrollmentId, "Enrollment")
    if rec["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_ENROLLMENT_INVALID_STATE, 409,
                       "start requires enrollment_status == ENROLLED")
    _check_content_approved(rec)
    if rec["session_id"] is not None:
        session = store.sessions[rec["session_id"]]
        if session["session_status"] != "SCHEDULED":
            raise ApiError(ERR_SESSION_NOT_SCHEDULED, 409,
                           "Linked session is not SCHEDULED")
    _check_rep_active(store.representatives[rec["rep_id"]])
    _check_ownership(rec)
    if clock_now() > rec["expires_at"]:
        raise ApiError(ERR_ENROLLMENT_EXPIRED, 409,
                       "Enrollment has expired")
    rec["enrollment_status"] = "IN_PROGRESS"
    touch(rec)
    # IN_PROGRESS FIRM_ELEMENT hours join the projected variant (PRD 3.6).
    recompute_plans_for_rep(rec["rep_id"])
    return success(view(rec))


@bp.post("/enrollments/<enrollmentId>/complete")
@require_roles("RegisteredRep")
def complete_enrollment_route(enrollmentId):
    rec = get_or_404(store.enrollments, enrollmentId, "Enrollment")
    body = json_body()
    # Shape: score present, integer, 0..100.
    require_fields(body, "score")
    score = body["score"]
    if isinstance(score, bool) or not isinstance(score, int):
        if isinstance(score, float) and score.is_integer():
            score = int(score)
        else:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Field 'score' must be an integer")
    if score < 0 or score > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'score' must be between 0 and 100")
    if rec["enrollment_status"] != "IN_PROGRESS":
        raise ApiError(ERR_ENROLLMENT_INVALID_STATE, 409,
                       "complete requires enrollment_status == IN_PROGRESS")
    _check_content_approved(rec)
    _check_rep_active(store.representatives[rec["rep_id"]])
    _check_ownership(rec)
    if clock_now() > rec["expires_at"]:
        raise ApiError(ERR_ENROLLMENT_EXPIRED, 409,
                       "Enrollment has expired")
    complete_enrollment(rec, score, actor())
    return success(view(rec))


@bp.post("/enrollments/<enrollmentId>/cancel")
@require_roles("TrainingAdmin")
def cancel_enrollment_route(enrollmentId):
    rec = get_or_404(store.enrollments, enrollmentId, "Enrollment")
    if rec["enrollment_status"] not in ("ENROLLED", "IN_PROGRESS"):
        raise ApiError(ERR_ENROLLMENT_INVALID_STATE, 409,
                       "cancel requires enrollment_status ENROLLED or IN_PROGRESS")
    cancel_enrollment(rec)
    return success(view(rec))


@bp.post("/enrollments/<enrollmentId>/reattempt")
@require_roles("RegisteredRep")
def reattempt_enrollment(enrollmentId):
    rec = get_or_404(store.enrollments, enrollmentId, "Enrollment")
    if rec["enrollment_status"] != "FAILED":
        raise ApiError(ERR_ENROLLMENT_INVALID_STATE, 409,
                       "reattempt requires enrollment_status == FAILED")
    _check_content_approved(rec)
    _check_rep_active(store.representatives[rec["rep_id"]])
    _check_ownership(rec)
    if rec["attempt_count"] >= MAX_ATTEMPTS:
        raise ApiError(ERR_MAX_ATTEMPTS_REACHED, 409,
                       "Maximum of %d attempts reached" % MAX_ATTEMPTS)
    rec["enrollment_status"] = "ENROLLED"
    rec["expires_at"] = enrollment_expires_at(clock_now())
    touch(rec)
    if rec["session_id"] is not None:
        sync_session_seats(store.sessions[rec["session_id"]])
    return success(view(rec))


@bp.post("/enrollments/<enrollmentId>/void")
@require_roles("ComplianceOfficer")
def void_enrollment_route(enrollmentId):
    rec = get_or_404(store.enrollments, enrollmentId, "Enrollment")
    body = json_body()
    # Shape: justification of at least ten characters.
    require_fields(body, "justification")
    justification = body["justification"]
    if not isinstance(justification, str) or len(justification) < 10:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'justification' must be at least 10 characters")
    if rec["enrollment_status"] != "COMPLETED":
        raise ApiError(ERR_ENROLLMENT_INVALID_STATE, 409,
                       "void requires enrollment_status == COMPLETED")
    void_enrollment(rec, justification, actor())
    return success(view(rec))
