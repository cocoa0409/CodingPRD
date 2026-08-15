"""MembershipCycle and CycleApplication endpoints."""

import re

from flask import Blueprint

import db
from core import (as_int, as_str, body, check_frozen, check_member_conflict,
                  compute_eligibility_score, cycle_candidate_ids, get_application,
                  get_chapter, get_cycle, new_record, recompute_chapter,
                  recompute_member, require_fields, serialize_cycle, touch,
                  ELIGIBILITY_SCORE_THRESHOLD)
from db import now, parse_dt
from decimal import Decimal
from errors import (ERR_ACTIVE_CYCLE_EXISTS, ERR_EMPTY_CANDIDATE_POOL,
                    ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD, ERR_INVALID_CYCLE_DATE,
                    ERR_INVALID_FORMAT, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_MEMBER_MISMATCH, ERR_NO_INDUCTED_APPLICATIONS,
                    ERR_STALE_CYCLE_VERSION, ApiError)
from middleware import auth, require_roles
from response import (apply_filters, list_response, serialize, serialize_many,
                      sorted_items, success)

bp = Blueprint("cycles", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")
CYCLE_LABEL_RE = re.compile(r"^\d{4}-(FALL|SPRING)$")
ACADEMIC_YEAR_RE = re.compile(r"^\d{4}-\d{4}$")


@bp.route("/chapters/<chapterId>/membership-cycles", methods=["POST"])
def create_cycle(chapterId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    check_frozen(ch)
    data = body()
    require_fields(data, ["cycle_label", "academic_year", "semester",
                          "nomination_open_date", "nomination_close_date",
                          "induction_date"])
    # guard 1: single active cycle per chapter
    for c in db.cycles.values():
        if c["chapter_id"] == ch["id"] and c["status"] in (
                "PLANNED", "NOMINATION", "REVIEW", "INDUCTED"):
            raise ApiError(ERR_ACTIVE_CYCLE_EXISTS, 409,
                           "Another MembershipCycle already exists in an active state")
    # guard 2: calendar coherence (strictly increasing dates)
    open_d = parse_dt(data["nomination_open_date"], "nomination_open_date")
    close_d = parse_dt(data["nomination_close_date"], "nomination_close_date")
    induct_d = parse_dt(data["induction_date"], "induction_date")
    if not (open_d < close_d < induct_d):
        raise ApiError(ERR_INVALID_CYCLE_DATE, 422,
                       "nomination_open_date must be strictly before nomination_close_date, "
                       "which must be strictly before induction_date")
    # guard 3: label formats
    cycle_label = as_str(data["cycle_label"], "cycle_label")
    academic_year = as_str(data["academic_year"], "academic_year")
    if not CYCLE_LABEL_RE.match(cycle_label) or not ACADEMIC_YEAR_RE.match(academic_year):
        raise ApiError(ERR_INVALID_FORMAT, 422,
                       "cycle_label must match \\d{4}-(FALL|SPRING) and academic_year \\d{4}-\\d{4}")
    semester = as_str(data["semester"], "semester")
    if semester not in ("FALL", "SPRING"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "semester must be FALL or SPRING")
    rec = new_record({
        "chapter_id": ch["id"],
        "cycle_label": cycle_label,
        "academic_year": academic_year,
        "semester": semester,
        "nomination_open_date": db.iso(open_d),
        "nomination_close_date": db.iso(close_d),
        "induction_date": db.iso(induct_d),
        "status": "PLANNED",
    })
    db.cycles[rec["id"]] = rec
    return success(serialize_cycle(rec), 201)


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>", methods=["GET"])
def fetch_cycle(chapterId, cycleId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    return success(serialize_cycle(c), 200)


@bp.route("/chapters/<chapterId>/membership-cycles", methods=["GET"])
def list_cycles(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    items = [c for c in db.cycles.values() if c["chapter_id"] == ch["id"]]
    items = apply_filters(items, ["status"])
    return list_response([serialize_cycle(c) for c in sorted_items(items)])


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/open-nominations", methods=["POST"])
def open_nominations(chapterId, cycleId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    check_frozen(ch)
    if c["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PLANNED cycle can open nominations")
    if ch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chapter must be ACTIVE to open nominations")
    cur = db.cycles.get(ch["current_cycle_id"]) if ch.get("current_cycle_id") else None
    if cur is not None and cur["status"] not in ("CLOSED", "CANCELLED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Chapter current_cycle_id already points at a live cycle")
    if now() < parse_dt(c["nomination_open_date"], "nomination_open_date"):
        raise ApiError(ERR_INVALID_CYCLE_DATE, 422,
                       "nomination_open_date has not yet been reached")
    c["status"] = "NOMINATION"
    touch(c)
    ch["current_cycle_id"] = c["id"]
    touch(ch)
    return success(serialize_cycle(c), 200)


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/close-nominations", methods=["POST"])
def close_nominations(chapterId, cycleId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    check_frozen(ch)
    if c["status"] != "NOMINATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a NOMINATION cycle can close nominations")
    if now() < parse_dt(c["nomination_close_date"], "nomination_close_date"):
        raise ApiError(ERR_INVALID_CYCLE_DATE, 422,
                       "nomination_close_date has not yet been reached")
    if not cycle_candidate_ids(c):
        raise ApiError(ERR_EMPTY_CANDIDATE_POOL, 409,
                       "Cannot close nominations with an empty candidate pool")
    # cascade: SUBMITTED -> UNDER_REVIEW and compute each eligibility score
    for a in db.applications.values():
        if a["cycle_id"] == c["id"] and a["status"] == "SUBMITTED":
            a["status"] = "UNDER_REVIEW"
            a["eligibility_score"] = compute_eligibility_score(a)
            touch(a)
    c["status"] = "REVIEW"
    touch(c)
    return success(serialize_cycle(c), 200)


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/induct", methods=["POST"])
def induct_cycle(chapterId, cycleId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    check_frozen(ch)
    data = body()
    # order: state legality, calendar, version freshness (PRD 3.2)
    if c["status"] != "REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REVIEW cycle can be inducted")
    pending = [a for a in db.applications.values()
               if a["cycle_id"] == c["id"] and a["status"] == "UNDER_REVIEW"]
    if pending:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Every application must be APPROVED, REJECTED, INDUCTED, or WITHDRAWN before induction")
    if now() < parse_dt(c["induction_date"], "induction_date"):
        raise ApiError(ERR_INVALID_CYCLE_DATE, 422, "induction_date has not yet been reached")
    if "expected_cycle_version" not in data or data["expected_cycle_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_cycle_version is required")
    expected = as_int(data["expected_cycle_version"], "expected_cycle_version")
    if expected != c["version"]:
        raise ApiError(ERR_STALE_CYCLE_VERSION, 412,
                       "expected_cycle_version does not match the cycle's current version")
    for a in db.applications.values():
        if a["cycle_id"] == c["id"] and a["status"] == "APPROVED":
            a["status"] = "INDUCTED"
            touch(a)
            m = db.members[a["member_id"]]
            m["status"] = "ACTIVE"
            m["inducted_cycle_id"] = c["id"]
            recompute_member(m)
    c["status"] = "INDUCTED"
    touch(c)
    recompute_chapter(ch)
    return success(serialize_cycle(c), 200)


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/close", methods=["POST"])
def close_cycle(chapterId, cycleId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    check_frozen(ch)
    if c["status"] != "INDUCTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an INDUCTED cycle can be closed")
    # election check first (state-legality matter), inducted-application check second
    open_elections = [e for e in db.elections.values()
                      if e.get("cycle_id") == c["id"] and e["chapter_id"] == ch["id"]
                      and e["status"] not in ("CERTIFIED", "VOIDED")]
    if open_elections:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "All elections tied to this cycle must be CERTIFIED or VOIDED before close")
    inducted = [a for a in db.applications.values()
                if a["cycle_id"] == c["id"] and a["status"] == "INDUCTED"]
    if not inducted:
        raise ApiError(ERR_NO_INDUCTED_APPLICATIONS, 409,
                       "The cycle must have at least one INDUCTED application before close")
    c["status"] = "CLOSED"
    touch(c)
    if ch.get("current_cycle_id") == c["id"]:
        ch["current_cycle_id"] = None
        touch(ch)
    return success(serialize_cycle(c), 200)


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/cancel", methods=["POST"])
def cancel_cycle(chapterId, cycleId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    check_frozen(ch)
    if c["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PLANNED cycle can be cancelled")
    c["status"] = "CANCELLED"
    touch(c)
    if ch.get("current_cycle_id") == c["id"]:
        ch["current_cycle_id"] = None
        touch(ch)
    return success(serialize_cycle(c), 200)


# --- CycleApplication ---

@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/applications", methods=["GET"])
def list_applications(chapterId, cycleId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    items = [a for a in db.applications.values() if a["cycle_id"] == c["id"]]
    items = apply_filters(items, ["status"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/applications/<applicationId>", methods=["GET"])
def fetch_application(chapterId, cycleId, applicationId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    a = get_application(c, applicationId)
    return success(serialize(a), 200)


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/applications/<applicationId>/approve", methods=["POST"])
def approve_application(chapterId, cycleId, applicationId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    a = get_application(c, applicationId)
    check_frozen(ch)
    # order: state legality, athletics check, then score/standing (PRD 3.2)
    if a["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an UNDER_REVIEW application can be approved")
    m = db.members[a["member_id"]]
    check_member_conflict(m["id"], parse_dt(c["induction_date"], "induction_date"))
    score = a["eligibility_score"]
    if score is None or Decimal(str(score)) < ELIGIBILITY_SCORE_THRESHOLD or not m["good_standing"]:
        raise ApiError(ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD, 422,
                       "eligibility_score must be at least 70.00 and the member must be in good standing")
    a["status"] = "APPROVED"
    touch(a)
    return success(serialize(a), 200)


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/applications/<applicationId>/reject", methods=["POST"])
def reject_application(chapterId, cycleId, applicationId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    a = get_application(c, applicationId)
    check_frozen(ch)
    if a["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an UNDER_REVIEW application can be rejected")
    data = body()
    if not data.get("rejection_reason") or not isinstance(data.get("rejection_reason"), str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "rejection_reason is required")
    a["status"] = "REJECTED"
    a["rejection_reason"] = data["rejection_reason"]
    touch(a)
    m = db.members[a["member_id"]]
    if m["status"] == "CANDIDATE":
        m["status"] = "PROSPECTIVE"
        recompute_member(m)
    return success(serialize(a), 200)


@bp.route("/chapters/<chapterId>/membership-cycles/<cycleId>/applications/<applicationId>/withdraw", methods=["POST"])
def withdraw_application(chapterId, cycleId, applicationId):
    uid, role = auth()
    require_roles(role, ("Member",))
    ch = get_chapter(chapterId)
    c = get_cycle(ch, cycleId)
    a = get_application(c, applicationId)
    check_frozen(ch)
    if a["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an UNDER_REVIEW application can be withdrawn")
    if uid != a["member_id"]:
        raise ApiError(ERR_MEMBER_MISMATCH, 403,
                       "Caller's X-User-ID must be the id of the applying member")
    a["status"] = "WITHDRAWN"
    touch(a)
    m = db.members[a["member_id"]]
    if m["status"] == "CANDIDATE":
        m["status"] = "PROSPECTIVE"
        recompute_member(m)
    return success(serialize(a), 200)
