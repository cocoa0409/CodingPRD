"""Application routes: submit, screen, reject, withdraw, reads."""

from flask import Blueprint, request, g

from db import db
from errors import (
    err_validation,
    err_forbidden,
    err_season_posture_forbidden,
    err_application_state_forbidden,
    err_application_window_closed,
    err_duplicate_application,
    err_school_application_cap_reached,
    err_school_dropped,
    err_screening_threshold_not_met,
)
from middleware import require_auth
from response import success_object, success_list
from services.calculations import screening_score
from services.domain import (
    get_season,
    get_school_target,
    get_candidate,
    get_application,
    application_view,
)
from utils import (
    parse_pagination,
    require_field,
    require_enum,
    optional_int,
    optional_bool,
    stamp_new,
    now_utc,
    touch,
)

bp = Blueprint("applications", __name__)

# Terminal statuses (school cap excludes these two only)
CAP_EXCLUDED_STATUSES = {"SCREENED_OUT", "WITHDRAWN"}


@bp.route("/seasons/<sid>/applications", methods=["POST"])
@require_auth(["Candidate"])
def submit_application(sid):
    season = get_season(sid)
    payload = request.get_json(silent=True) or {}
    candidate_id = require_field(payload, "candidate_id")
    if not isinstance(candidate_id, str):
        raise err_validation("candidate_id must be a string")
    school_target_id = require_field(payload, "school_target_id")
    if not isinstance(school_target_id, str):
        raise err_validation("school_target_id must be a string")
    relocation_distance_miles = require_field(payload, "relocation_distance_miles")
    if isinstance(relocation_distance_miles, bool) or not isinstance(relocation_distance_miles, int) or relocation_distance_miles < 0:
        raise err_validation("relocation_distance_miles must be an integer >= 0")
    referral_flag = optional_bool(payload, "referral_flag", default=False)
    prior_internship_count = optional_int(payload, "prior_internship_count", default=0, min_value=0)

    # Ownership (priority 3): payload candidate_id must equal X-User-ID
    if candidate_id != g.user_id:
        raise err_forbidden("candidate_id must equal X-User-ID")
    # Existence of referenced entities (left-to-right: season checked above)
    get_candidate(candidate_id)
    school = get_school_target(school_target_id)
    if school["season_id"] != sid:
        from errors import err_not_found
        raise err_not_found(f"SchoolTarget {school_target_id} not in season {sid}")

    # Posture gate (priority 8)
    if season["status"] != "OPEN":
        raise err_season_posture_forbidden()

    # Application window (priority 23)
    now = now_utc()
    if not (season["_application_open_at"] <= now <= season["_application_close_at"]):
        raise err_application_window_closed()

    # Duplicate application (priority 32)
    for a in db.applications.values():
        if a["candidate_id"] == candidate_id and a["season_id"] == sid:
            raise err_duplicate_application()

    # School cap (priority 33)
    in_flight = sum(
        1 for a in db.applications.values()
        if a["school_target_id"] == school_target_id
        and a["season_id"] == sid
        and a["status"] not in CAP_EXCLUDED_STATUSES
    )
    if in_flight >= school["application_cap"]:
        raise err_school_application_cap_reached()

    # School must be ACTIVE (priority 34)
    if school["status"] != "ACTIVE":
        raise err_school_dropped()

    a = {
        "season_id": sid,
        "candidate_id": candidate_id,
        "school_target_id": school_target_id,
        "status": "SUBMITTED",
        "referral_flag": referral_flag,
        "prior_internship_count": prior_internship_count,
        "relocation_distance_miles": relocation_distance_miles,
        "screening_score_provisional": None,
        "screening_score_final": None,
    }
    stamp_new(a)
    # Provisional variant: as_of = application.created_at; tier is current
    # created_at is stamped from the logical clock by stamp_new via format_iso(now_utc()).
    from utils import parse_iso
    as_of = parse_iso(a["created_at"])
    a["screening_score_provisional"] = screening_score(a, school, as_of)
    db.applications[a["id"]] = a
    season["applications_total_count"] += 1
    touch(season)
    return success_object(application_view(a), 201)


@bp.route("/applications/<aid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Candidate"])
def get_one_application(aid):
    a = get_application(aid)
    if g.role == "Candidate" and g.user_id != a["candidate_id"]:
        raise err_forbidden("Candidate may read only its own applications")
    return success_object(application_view(a))


@bp.route("/seasons/<sid>/applications", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_season_applications(sid):
    get_season(sid)
    limit, offset = parse_pagination(request.args)
    school_target_id = request.args.get("school_target_id")
    status = request.args.get("status")
    items = [
        a for a in db.applications.values()
        if a["season_id"] == sid
        and (school_target_id is None or a["school_target_id"] == school_target_id)
        and (status is None or a["status"] == status)
    ]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([application_view(a) for a in page], total, limit, offset)


@bp.route("/school-targets/<tid>/applications", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_school_applications(tid):
    get_school_target(tid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        a for a in db.applications.values()
        if a["school_target_id"] == tid
        and (status is None or a["status"] == status)
    ]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([application_view(a) for a in page], total, limit, offset)


@bp.route("/applications/<aid>/screen", methods=["POST"])
@require_auth(["Recruiter"])
def screen_application(aid):
    a = get_application(aid)
    payload = request.get_json(silent=True) or {}
    decision = require_enum(payload, "decision", {"SHORTLIST", "REJECT"})
    season = get_season(a["season_id"])
    # Posture
    if season["status"] != "SELECTION":
        raise err_season_posture_forbidden()
    # State
    if a["status"] != "SUBMITTED":
        raise err_application_state_forbidden("screen requires SUBMITTED")
    # Compute final variant
    school = get_school_target(a["school_target_id"])
    now = now_utc()
    final_score = screening_score(a, school, now)
    a["screening_score_final"] = final_score
    if decision == "SHORTLIST":
        if final_score < season["shortlist_score_threshold"]:
            # still store final score but fail
            touch(a)
            raise err_screening_threshold_not_met()
        a["status"] = "SHORTLISTED"
    else:
        a["status"] = "SCREENED_OUT"
    touch(a)
    return success_object(application_view(a))


@bp.route("/applications/<aid>/reject", methods=["POST"])
@require_auth(["Recruiter"])
def reject_application(aid):
    a = get_application(aid)
    season = get_season(a["season_id"])
    if season["status"] not in ("SELECTION", "OFFER_PERIOD"):
        raise err_season_posture_forbidden()
    if a["status"] != "DECISION_PENDING":
        raise err_application_state_forbidden("reject requires DECISION_PENDING")
    a["status"] = "REJECTED"
    touch(a)
    return success_object(application_view(a))


@bp.route("/applications/<aid>/withdraw", methods=["POST"])
@require_auth(["Candidate"])
def withdraw_application(aid):
    a = get_application(aid)
    # Ownership
    if g.user_id != a["candidate_id"]:
        raise err_forbidden("X-User-ID must equal application.candidate_id")
    # State gate: allowed from SUBMITTED/SHORTLISTED/INTERVIEW_SCHEDULED/DECISION_PENDING/OFFER_PENDING
    allowed = {"SUBMITTED", "SHORTLISTED", "INTERVIEW_SCHEDULED", "DECISION_PENDING", "OFFER_PENDING"}
    if a["status"] not in allowed:
        raise err_application_state_forbidden("Withdraw not allowed from current status")
    prior = a["status"]
    if prior in ("SUBMITTED", "SHORTLISTED", "DECISION_PENDING"):
        a["status"] = "WITHDRAWN"
        touch(a)
        return success_object(application_view(a))

    if prior == "INTERVIEW_SCHEDULED":
        # Ordered cascade: cancel each BOOKED slot (decrement day's booked_count); suppress auto-flip
        slots = [s for s in db.interview_slots.values() if s["application_id"] == aid and s["status"] == "BOOKED"]
        slots.sort(key=lambda s: s["created_at"])
        for s in slots:
            s["status"] = "CANCELLED"
            touch(s)
            day = db.interview_days.get(s["interview_day_id"])
            if day is not None:
                day["booked_count"] -= 1
                touch(day)
        a["status"] = "WITHDRAWN"
        touch(a)
        return success_object(application_view(a))

    # prior == OFFER_PENDING: decline offer (suppress app-flip), cancel BOOKED slots, then WITHDRAWN
    offer = None
    for o in db.offers.values():
        if o["application_id"] == aid:
            offer = o
            break
    if offer is not None and offer["status"] == "EXTENDED":
        offer["status"] = "DECLINED"
        touch(offer)
    slots = [s for s in db.interview_slots.values() if s["application_id"] == aid and s["status"] == "BOOKED"]
    slots.sort(key=lambda s: s["created_at"])
    for s in slots:
        s["status"] = "CANCELLED"
        touch(s)
        day = db.interview_days.get(s["interview_day_id"])
        if day is not None:
            day["booked_count"] -= 1
            touch(day)
    a["status"] = "WITHDRAWN"
    touch(a)
    return success_object(application_view(a))
