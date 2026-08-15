"""Case assignment, posture, closure, time entries, referrals, surveys."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, new_id, now
from errors import (ERR_CASE_NOT_ASSIGNED_TO_YOU, ERR_CASE_NOT_CLOSED,
                    ERR_CASE_PLACEMENT_CONFLICT,
                    ERR_CASELOAD_CAPACITY_EXCEEDED, ERR_DUPLICATE_SURVEY,
                    ERR_INVALID_CASE_STATE, ERR_INVALID_REQUEST,
                    ERR_PANEL_CAPACITY_REACHED, ERR_PANEL_COVERAGE_MISMATCH,
                    ERR_PANEL_MEMBER_NOT_ACTIVE,
                    ERR_PARALEGAL_SUPERVISION_MISMATCH, ERR_STAFF_NOT_ACTIVE,
                    ERR_STAFF_COVERAGE_MISMATCH, ERR_STALE_VERSION,
                    ERR_TIME_ENTRY_FORBIDDEN, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services import derived
from services.case_ops import close_case
from services.common import get_or_404, list_response, stamp_new, stamp_new_aux, touch
from services.enums import ACTIVITY_CODES, OUTCOME_CODES
from services.serialize import case_json, survey_json, time_entry_json
from validators import (body, check_allowed, opt_str, req_bool, req_enum,
                        req_int, req_number, req_str, req_date)

bp = Blueprint("cases", __name__)

ADVICE_WINDOW_DAYS = 30
REFERRAL_RESPONSE_DAYS = 10


def _get_case(cid):
    return get_or_404(db.cases, cid)


def _require_case_state(case, states):
    if case["status"] not in states:
        fail(ERR_INVALID_CASE_STATE,
             "Case is {} and cannot perform this transition".format(
                 case["status"]))


@bp.route("/cases/<cid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_case(cid):
    return ok_object(case_json(_get_case(cid)))


@bp.route("/cases", methods=["GET"])
@require_roles(ALL_ROLES)
def list_cases():
    records = list(db.cases.values())
    for param in ("application_id", "grant_program_id",
                  "assigned_attorney_id", "assigned_paralegal_id", "status",
                  "funding_status", "placement"):
        value = request.args.get(param)
        if value is not None:
            records = [c for c in records if c[param] == value]
    return list_response(records, case_json)


def _set_advice_window(case):
    if case["service_level"] == "ADVICE_ONLY" and case["advice_deadline"] is None:
        case["advice_deadline"] = case["opened_at"] + timedelta(
            days=ADVICE_WINDOW_DAYS)


@bp.route("/cases/<cid>/assign", methods=["POST"])
@require_roles(["SupervisingAttorney"])
def assign_case(cid):
    case = _get_case(cid)
    b = body()
    check_allowed(b, ["attorney_id", "paralegal_id", "expected_case_version"])
    attorney_id = req_str(b, "attorney_id")
    paralegal_id = b.get("paralegal_id")
    if paralegal_id is not None and not isinstance(paralegal_id, str):
        fail(ERR_INVALID_REQUEST, "Field paralegal_id must be a string")
    expected = req_int(b, "expected_case_version")
    # Body FK existence (priority 6).
    attorney = get_or_404(db.staff, attorney_id)
    paralegal = None
    if paralegal_id is not None:
        paralegal = get_or_404(db.staff, paralegal_id)
    # State legality (priority 7).
    _require_case_state(case, ["PENDING_ASSIGNMENT", "OPEN"])
    # OCC (priority 8).
    if expected != case["version"]:
        fail(ERR_STALE_VERSION,
             "expected_case_version {} does not match current version "
             "{}".format(expected, case["version"]))
    # Superseding assignment requires INTERNAL placement.
    if case["status"] == "OPEN" and case["placement"] != "INTERNAL":
        fail(ERR_CASE_PLACEMENT_CONFLICT,
             "Case is pro bono-placed and cannot be reassigned")
    # Assignee checks (same for both paths).
    if attorney["staff_type"] != "ATTORNEY" or attorney["status"] != "ACTIVE":
        fail(ERR_STAFF_NOT_ACTIVE,
             "Attorney must be an ACTIVE ATTORNEY")
    app = derived.application_of(case)
    if (app["case_type"] not in attorney["practice_areas"]
            or app["incident_county"] not in attorney["admitted_counties"]):
        fail(ERR_STAFF_COVERAGE_MISMATCH,
             "Attorney does not cover this case type or county")
    if paralegal is not None:
        if (paralegal["staff_type"] != "PARALEGAL"
                or paralegal["status"] != "ACTIVE"
                or paralegal["supervising_attorney_id"] != attorney_id):
            fail(ERR_PARALEGAL_SUPERVISION_MISMATCH,
                 "Paralegal must be ACTIVE and supervised by the attorney")
    load, _ = derived.attorney_load_count(attorney_id)
    if load + case["case_weight"] > attorney["max_units"]:
        fail(ERR_CASELOAD_CAPACITY_EXCEEDED,
             "Assignment would exceed the attorney's caseload ceiling")

    old_attorney_id = case["assigned_attorney_id"]
    was_pending = case["status"] == "PENDING_ASSIGNMENT"
    case["assigned_attorney_id"] = attorney_id
    case["assigned_paralegal_id"] = paralegal_id
    case["status"] = "OPEN"
    if was_pending and case["opened_at"] is None:
        case["opened_at"] = now()
        _set_advice_window(case)
    touch(case)
    touched = set()
    if old_attorney_id and old_attorney_id != attorney_id:
        old = db.staff.get(old_attorney_id)
        if old is not None:
            touch(old)
            touched.add(old_attorney_id)
    if attorney_id not in touched:
        touch(attorney)
    return ok_object(case_json(case))


@bp.route("/cases/<cid>/place-hold", methods=["POST"])
@require_roles(["SupervisingAttorney"])
def place_hold(cid):
    case = _get_case(cid)
    b = body()
    check_allowed(b, ["hold_reason"])
    opt_str(b, "hold_reason")
    _require_case_state(case, ["OPEN"])
    case["status"] = "ON_HOLD"
    touch(case)
    if case["assigned_attorney_id"] is not None:
        attorney = db.staff.get(case["assigned_attorney_id"])
        if attorney is not None:
            touch(attorney)  # load released (derived)
    return ok_object(case_json(case))


@bp.route("/cases/<cid>/resume", methods=["POST"])
@require_roles(["SupervisingAttorney"])
def resume_case(cid):
    case = _get_case(cid)
    b = body()
    check_allowed(b, [])
    _require_case_state(case, ["ON_HOLD"])
    attorney = None
    if case["assigned_attorney_id"] is not None:
        attorney = db.staff.get(case["assigned_attorney_id"])
    if attorney is not None:
        if attorney["status"] != "ACTIVE":
            fail(ERR_STAFF_NOT_ACTIVE,
                 "Assigned attorney is not ACTIVE")
        load, _ = derived.attorney_load_count(attorney["id"])
        if load + case["case_weight"] > attorney["max_units"]:
            fail(ERR_CASELOAD_CAPACITY_EXCEEDED,
                 "Resume would exceed the attorney's caseload ceiling")
    case["status"] = "OPEN"
    touch(case)
    if attorney is not None:
        touch(attorney)
    return ok_object(case_json(case))


@bp.route("/cases/<cid>/close", methods=["POST"])
@require_roles(["StaffAttorney", "SupervisingAttorney"])
def close_case_endpoint(cid):
    case = _get_case(cid)
    # Ownership scope (priority 4) runs before request-shape checks.
    if (g.user_role == "StaffAttorney"
            and case["assigned_attorney_id"] != g.user_id):
        fail(ERR_CASE_NOT_ASSIGNED_TO_YOU,
             "A StaffAttorney may close only their own assigned cases")
    b = body()
    check_allowed(b, ["outcome_code", "closure_reason"])
    outcome_code = req_enum(b, "outcome_code", OUTCOME_CODES)
    closure_reason = opt_str(b, "closure_reason")
    _require_case_state(case, ["OPEN", "ON_HOLD", "PENDING_ASSIGNMENT"])
    close_case(case, outcome_code, closure_reason)
    return ok_object(case_json(case))


# ---- TimeEntry ----

@bp.route("/cases/<cid>/time-entries", methods=["POST"])
@require_roles(["StaffAttorney", "Paralegal", "SupervisingAttorney"])
def create_time_entry(cid):
    case = _get_case(cid)
    # Ownership scope (priority 4) before shape: assigned attorney/paralegal only.
    if (g.user_id != case["assigned_attorney_id"]
            and g.user_id != case["assigned_paralegal_id"]):
        fail(ERR_TIME_ENTRY_FORBIDDEN,
             "Only the case's assigned attorney or paralegal may log time")
    b = body()
    check_allowed(b, ["hours", "activity_code", "work_date"])
    hours = req_number(b, "hours")
    if hours < Decimal("0.25") or hours > Decimal("24"):
        fail(ERR_INVALID_REQUEST, "hours must be between 0.25 and 24.00")
    activity_code = req_enum(b, "activity_code", ACTIVITY_CODES)
    work_date = req_date(b, "work_date")
    _require_case_state(case, ["OPEN"])
    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "staff_id": g.user_id,
        "hours": hours,
        "activity_code": activity_code,
        "work_date": work_date,
    }
    stamp_new_aux(rec)
    db.time_entries[rec["id"]] = rec
    return ok_object(time_entry_json(rec), 201)


# ---- Referral offer (nested under cases) ----

@bp.route("/cases/<cid>/referrals", methods=["POST"])
@require_roles(["SupervisingAttorney"])
def create_referral(cid):
    case = _get_case(cid)
    b = body()
    check_allowed(b, ["panel_member_id", "notes"])
    panel_member_id = req_str(b, "panel_member_id")
    notes = opt_str(b, "notes", "")
    member = get_or_404(db.panel_members, panel_member_id)
    if case["placement"] != "INTERNAL" or case["status"] not in (
            "PENDING_ASSIGNMENT", "OPEN"):
        fail(ERR_CASE_PLACEMENT_CONFLICT,
             "Case must be INTERNAL and PENDING_ASSIGNMENT or OPEN")
    if member["status"] != "ACTIVE":
        fail(ERR_PANEL_MEMBER_NOT_ACTIVE, "Panel member is not ACTIVE")
    app = derived.application_of(case)
    if (app["case_type"] not in member["practice_areas"]
            or app["incident_county"] not in member["counties"]):
        fail(ERR_PANEL_COVERAGE_MISMATCH,
             "Panel member does not cover this case type or county")
    if derived.panel_active_count(member["id"]) >= member["max_active_referrals"]:
        fail(ERR_PANEL_CAPACITY_REACHED,
             "Panel member is at their active referral cap")
    offered_at = now()
    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "panel_member_id": member["id"],
        "status": "OFFERED",
        "notes": notes,
        "offered_at": offered_at,
        "response_deadline": offered_at + timedelta(
            days=REFERRAL_RESPONSE_DAYS),
        "responded_at": None,
        "service_start_date": None,
        "service_end_date": None,
        "decline_reason": None,
    }
    stamp_new(rec)
    db.referrals[rec["id"]] = rec
    from services.serialize import referral_json
    return ok_object(referral_json(rec), 201)


# ---- Satisfaction surveys (nested under cases) ----

@bp.route("/cases/<cid>/satisfaction-surveys", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def create_survey(cid):
    case = _get_case(cid)
    b = body()
    check_allowed(b, ["score", "would_recommend", "comments"])
    score = req_int(b, "score", min_v=1, max_v=5)
    would_recommend = req_bool(b, "would_recommend")
    comments = opt_str(b, "comments", "")
    if case["status"] != "CLOSED":
        fail(ERR_CASE_NOT_CLOSED,
             "Satisfaction surveys require a CLOSED case")
    for s in db.surveys.values():
        if s["case_id"] == case["id"]:
            fail(ERR_DUPLICATE_SURVEY, "Case already has a survey")
    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "score": score,
        "would_recommend": would_recommend,
        "comments": comments,
    }
    stamp_new_aux(rec)
    db.surveys[rec["id"]] = rec
    return ok_object(survey_json(rec), 201)


@bp.route("/cases/<cid>/satisfaction-surveys", methods=["GET"])
@require_roles(["IntakeSpecialist", "SupervisingAttorney", "GrantsManager",
                "ProgramDirector"])
def list_surveys(cid):
    case = _get_case(cid)
    records = [s for s in db.surveys.values() if s["case_id"] == case["id"]]
    return list_response(records, survey_json)
