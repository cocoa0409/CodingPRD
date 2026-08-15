"""Injury cases, treatment plans, daily status entries."""
from flask import Blueprint, request

from db import STORE, new_id, now_stamp, touch, clock_date
from errors import (bad_request, not_found, conflict, unprocessable,
                    ERR_CASE_NOT_OPEN, ERR_NO_STATUS_ENTRY,
                    ERR_CASE_NOT_IN_REHAB, ERR_CASE_NOT_CLEARED,
                    ERR_PLAN_STILL_ACTIVE, ERR_CLAIMS_OPEN,
                    ERR_DESIGNATION_NOT_OUT, ERR_CASE_NOT_LONG_TERM,
                    ERR_PLAN_NOT_DRAFT, ERR_PLAN_NOT_ACTIVE,
                    ERR_PLAN_NOT_SUSPENDED, ERR_PLAN_NOT_COMPLETABLE,
                    ERR_INVALID_STATE, ERR_FUTURE_DATE_NOT_ALLOWED,
                    ERR_INVALID_SUPERSEDE_TARGET)
from middleware import require_roles
from response import ok_obj, ok_list
from routes.serializers import (injury_case_json, treatment_plan_json,
                                daily_status_entry_json, sorted_items)
from services.common import (find_all, find_one, protocol_for_case,
                             latest_current_entry)
from services.derived import recompute_athlete
from util import (body, present, require_str, require_enum, require_date,
                  require_int, require_bool, optional_str)

bp = Blueprint("cases", __name__)

SURFACES = ["GRASS", "TURF", "COURT", "ICE", "TRAINING_ROOM"]
MECHANISMS = ["CONTACT", "NON_CONTACT", "OVERUSE", "UNKNOWN"]
DESIGNATIONS = ["OUT", "LIMITED", "MODIFIED", "FULL"]
CASE_READERS = ("MedicalStaff", "TeamPhysician", "BillingStaff", "TeamAdmin")
PLAN_READERS = ("MedicalStaff", "TeamPhysician", "TeamAdmin")
ENTRY_READERS = ("MedicalStaff", "TeamPhysician", "TeamAdmin")


def _get_case(case_id):
    c = STORE["injury_cases"].get(case_id)
    if c is None:
        raise not_found("InjuryCase not found")
    return c


def _get_plan(plan_id):
    p = STORE["treatment_plans"].get(plan_id)
    if p is None:
        raise not_found("TreatmentPlan not found")
    return p


# ---------------- Injury cases ----------------

@bp.route("/injury-cases", methods=["POST"])
def create_injury_case():
    uid, _ = require_roles("MedicalStaff")
    j = body()
    # existence (3): provided FKs
    athlete = None
    if present(j, "athlete_id"):
        athlete = STORE["athletes"].get(j["athlete_id"])
        if athlete is None:
            raise not_found("Athlete not found: athlete_id")
    diag = None
    if present(j, "diagnosis_code_id"):
        diag = STORE["diagnosis_codes"].get(j["diagnosis_code_id"])
        if diag is None:
            raise not_found("DiagnosisCode not found: diagnosis_code_id")
    # field constraints (10)
    if athlete is None:
        require_str(j, "athlete_id")
    if diag is None:
        require_str(j, "diagnosis_code_id")
    oraw, odate = require_date(j, "occurred_on")
    surface = require_enum(j, "surface", SURFACES)
    mechanism = require_enum(j, "mechanism", MECHANISMS)
    # future-date (14)
    if odate > clock_date():
        raise unprocessable(ERR_FUTURE_DATE_NOT_ALLOWED,
                            "occurred_on later than current date")
    ts = now_stamp()
    case = {
        "id": new_id(), "athlete_id": athlete["id"], "team_id": athlete["team_id"],
        "diagnosis_code_id": diag["id"], "occurred_on": oraw, "_occurred_on": odate,
        "surface": surface, "mechanism": mechanism, "status": "OPEN",
        "reported_by_user_id": uid,
        "severity_class_snapshot": diag["severity_class"],
        "is_concussion_snapshot": diag["is_concussion"],
        "cleared_on": None, "closed_on": None, "_closed_on": None,
        "days_lost": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    STORE["injury_cases"][case["id"]] = case
    recompute_athlete(athlete, bump=True)
    return ok_obj(injury_case_json(case), 201)


@bp.route("/injury-cases", methods=["GET"])
def list_injury_cases():
    require_roles(*CASE_READERS)
    items = sorted_items(STORE["injury_cases"])
    athlete_id = request.args.get("athlete_id")
    team_id = request.args.get("team_id")
    diagnosis_code_id = request.args.get("diagnosis_code_id")
    status = request.args.get("status")
    if athlete_id is not None:
        items = [c for c in items if c["athlete_id"] == athlete_id]
    if team_id is not None:
        items = [c for c in items if c["team_id"] == team_id]
    if diagnosis_code_id is not None:
        items = [c for c in items if c["diagnosis_code_id"] == diagnosis_code_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return ok_list([injury_case_json(c) for c in items])


@bp.route("/injury-cases/<caseId>", methods=["GET"])
def get_injury_case(caseId):
    require_roles(*CASE_READERS)
    return ok_obj(injury_case_json(_get_case(caseId)))


@bp.route("/injury-cases/<caseId>/start-rehab", methods=["POST"])
def start_rehab(caseId):
    require_roles("MedicalStaff")
    case = _get_case(caseId)
    if case["status"] != "OPEN":
        raise conflict(ERR_CASE_NOT_OPEN, "start-rehab requires case OPEN")
    has_entry = any(e["injury_case_id"] == case["id"] and e["is_current"]
                    for e in STORE["daily_status_entries"].values())
    if not has_entry:
        raise conflict(ERR_NO_STATUS_ENTRY,
                       "start-rehab requires at least one current status entry")
    case["status"] = "REHAB"
    touch(case)
    athlete = STORE["athletes"][case["athlete_id"]]
    recompute_athlete(athlete, bump=True)
    return ok_obj(injury_case_json(case))


@bp.route("/injury-cases/<caseId>/mark-long-term", methods=["POST"])
def mark_long_term(caseId):
    require_roles("MedicalStaff")
    case = _get_case(caseId)
    if case["status"] != "REHAB":
        raise conflict(ERR_CASE_NOT_IN_REHAB, "mark-long-term requires case REHAB")
    latest = latest_current_entry(case["id"])
    if latest is None or latest["designation"] != "OUT":
        raise conflict(ERR_DESIGNATION_NOT_OUT,
                       "mark-long-term requires latest designation OUT")
    case["status"] = "LONG_TERM"
    touch(case)
    athlete = STORE["athletes"][case["athlete_id"]]
    recompute_athlete(athlete, bump=True)
    return ok_obj(injury_case_json(case))


@bp.route("/injury-cases/<caseId>/resume-rehab", methods=["POST"])
def resume_rehab(caseId):
    require_roles("MedicalStaff")
    case = _get_case(caseId)
    if case["status"] != "LONG_TERM":
        raise conflict(ERR_CASE_NOT_LONG_TERM, "resume-rehab requires case LONG_TERM")
    case["status"] = "REHAB"
    touch(case)
    athlete = STORE["athletes"][case["athlete_id"]]
    recompute_athlete(athlete, bump=True)
    return ok_obj(injury_case_json(case))


@bp.route("/injury-cases/<caseId>/close", methods=["POST"])
def close_case(caseId):
    require_roles("MedicalStaff")
    case = _get_case(caseId)
    if case["status"] != "CLEARED":
        raise conflict(ERR_CASE_NOT_CLEARED, "close requires case CLEARED")
    blocking_plan = find_one("treatment_plans",
                             lambda p: p["injury_case_id"] == case["id"]
                             and p["status"] in ("ACTIVE", "SUSPENDED"))
    if blocking_plan is not None:
        raise conflict(ERR_PLAN_STILL_ACTIVE,
                       "close blocked by ACTIVE/SUSPENDED treatment plan")
    blocking_claim = find_one("claims",
                              lambda c: c["injury_case_id"] == case["id"]
                              and c["status"] in ("DRAFT", "SUBMITTED", "APPEALED"))
    if blocking_claim is not None:
        raise conflict(ERR_CLAIMS_OPEN,
                       "close blocked by claim in DRAFT/SUBMITTED/APPEALED")
    today = clock_date()
    case["status"] = "CLOSED"
    case["closed_on"] = today.isoformat()
    case["_closed_on"] = today
    case["days_lost"] = (today - case["_occurred_on"]).days
    touch(case)
    athlete = STORE["athletes"][case["athlete_id"]]
    recompute_athlete(athlete, bump=True)
    return ok_obj(injury_case_json(case))


# ---------------- Treatment plans ----------------

@bp.route("/treatment-plans", methods=["POST"])
def create_treatment_plan():
    require_roles("MedicalStaff")
    j = body()
    case = None
    if present(j, "injury_case_id"):
        case = STORE["injury_cases"].get(j["injury_case_id"])
        if case is None:
            raise not_found("InjuryCase not found: injury_case_id")
    if case is None:
        require_str(j, "injury_case_id")
    title = require_str(j, "title")
    spw = require_int(j, "planned_sessions_per_week", 1, 14)
    dur = require_int(j, "estimated_duration_weeks", 1, 52)
    ts = now_stamp()
    plan = {
        "id": new_id(), "injury_case_id": case["id"],
        "athlete_id": case["athlete_id"], "title": title,
        "planned_sessions_per_week": spw, "estimated_duration_weeks": dur,
        "status": "DRAFT", "suspension_reason": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    STORE["treatment_plans"][plan["id"]] = plan
    return ok_obj(treatment_plan_json(plan), 201)


@bp.route("/treatment-plans", methods=["GET"])
def list_treatment_plans():
    require_roles(*PLAN_READERS)
    items = sorted_items(STORE["treatment_plans"])
    injury_case_id = request.args.get("injury_case_id")
    athlete_id = request.args.get("athlete_id")
    status = request.args.get("status")
    if injury_case_id is not None:
        items = [p for p in items if p["injury_case_id"] == injury_case_id]
    if athlete_id is not None:
        items = [p for p in items if p["athlete_id"] == athlete_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return ok_list([treatment_plan_json(p) for p in items])


@bp.route("/treatment-plans/<planId>", methods=["GET"])
def get_treatment_plan(planId):
    require_roles(*PLAN_READERS)
    return ok_obj(treatment_plan_json(_get_plan(planId)))


@bp.route("/treatment-plans/<planId>/activate", methods=["POST"])
def activate_plan(planId):
    require_roles("MedicalStaff")
    plan = _get_plan(planId)
    if plan["status"] != "DRAFT":
        raise conflict(ERR_PLAN_NOT_DRAFT, "activate requires plan DRAFT")
    case = STORE["injury_cases"][plan["injury_case_id"]]
    if case["status"] not in ("OPEN", "REHAB", "LONG_TERM", "RTP"):
        raise conflict(ERR_INVALID_STATE,
                       "Parent case state does not allow activation")
    plan["status"] = "ACTIVE"
    touch(plan)
    return ok_obj(treatment_plan_json(plan))


@bp.route("/treatment-plans/<planId>/suspend", methods=["POST"])
def suspend_plan(planId):
    require_roles("MedicalStaff")
    plan = _get_plan(planId)
    if plan["status"] != "ACTIVE":
        raise conflict(ERR_PLAN_NOT_ACTIVE, "suspend requires plan ACTIVE")
    j = body()
    reason = require_str(j, "reason")
    plan["status"] = "SUSPENDED"
    plan["suspension_reason"] = reason
    touch(plan)
    return ok_obj(treatment_plan_json(plan))


@bp.route("/treatment-plans/<planId>/resume", methods=["POST"])
def resume_plan(planId):
    require_roles("MedicalStaff")
    plan = _get_plan(planId)
    if plan["status"] != "SUSPENDED":
        raise conflict(ERR_PLAN_NOT_SUSPENDED, "resume requires plan SUSPENDED")
    plan["status"] = "ACTIVE"
    plan["suspension_reason"] = None
    touch(plan)
    return ok_obj(treatment_plan_json(plan))


@bp.route("/treatment-plans/<planId>/complete", methods=["POST"])
def complete_plan(planId):
    require_roles("MedicalStaff")
    plan = _get_plan(planId)
    if plan["status"] not in ("ACTIVE", "SUSPENDED"):
        raise conflict(ERR_PLAN_NOT_COMPLETABLE,
                       "complete requires plan ACTIVE or SUSPENDED")
    plan["status"] = "COMPLETED"
    touch(plan)
    return ok_obj(treatment_plan_json(plan))


# ---------------- Daily status entries ----------------

@bp.route("/daily-status-entries", methods=["POST"])
def create_daily_status_entry():
    uid, _ = require_roles("MedicalStaff")
    j = body()
    # existence (3)
    case = None
    if present(j, "injury_case_id"):
        case = STORE["injury_cases"].get(j["injury_case_id"])
        if case is None:
            raise not_found("InjuryCase not found: injury_case_id")
    if case is None:
        require_str(j, "injury_case_id")
    # field constraints (10)
    eraw, edate = require_date(j, "entry_date")
    designation = require_enum(j, "designation", DESIGNATIONS)
    symptom_free = require_bool(j, "symptom_free")
    score = require_int(j, "functional_test_score", 0, 100)
    notes = optional_str(j, "notes")
    # supersede target validity (13)
    supersedes_id = j.get("supersedes_entry_id")
    target = None
    if supersedes_id is not None:
        target = STORE["daily_status_entries"].get(supersedes_id)
        if (target is None
                or target["injury_case_id"] != case["id"]
                or target["_entry_date"] != edate
                or not target["is_current"]):
            raise unprocessable(ERR_INVALID_SUPERSEDE_TARGET,
                                "supersedes_entry_id is not a current entry for the same case and date")
    # future-date (14)
    if edate > clock_date():
        raise unprocessable(ERR_FUTURE_DATE_NOT_ALLOWED,
                            "entry_date later than current date")
    ts = now_stamp()
    # is_current bookkeeping: new entry is sole current for (case, entry_date)
    for e in STORE["daily_status_entries"].values():
        if e["injury_case_id"] == case["id"] and e["_entry_date"] == edate:
            e["is_current"] = False
    entry = {
        "id": new_id(), "injury_case_id": case["id"],
        "athlete_id": case["athlete_id"], "entry_date": eraw, "_entry_date": edate,
        "designation": designation, "symptom_free": symptom_free,
        "functional_test_score": score, "notes": notes,
        "recorded_by_user_id": uid,
        "supersedes_entry_id": supersedes_id,
        "is_current": True, "created_at": ts,
    }
    STORE["daily_status_entries"][entry["id"]] = entry

    athlete = STORE["athletes"][case["athlete_id"]]
    recompute_athlete(athlete, bump=True)

    # concussion auto-overlay
    if case["is_concussion_snapshot"]:
        protocol = protocol_for_case(case["id"])
        if protocol is not None:
            latest = latest_current_entry(case["id"])
            if latest is not None:
                if protocol["status"] == "IN_PROGRESS" and latest["symptom_free"] is False:
                    protocol["status"] = "SUSPENDED_CONCUSSION"
                    touch(protocol)
                elif protocol["status"] == "SUSPENDED_CONCUSSION" and latest["symptom_free"] is True:
                    protocol["status"] = "IN_PROGRESS"
                    touch(protocol)
    return ok_obj(daily_status_entry_json(entry), 201)


@bp.route("/daily-status-entries", methods=["GET"])
def list_daily_status_entries():
    require_roles(*ENTRY_READERS)
    items = sorted_items(STORE["daily_status_entries"])
    injury_case_id = request.args.get("injury_case_id")
    athlete_id = request.args.get("athlete_id")
    entry_date = request.args.get("entry_date")
    is_current = request.args.get("is_current")
    supersedes_entry_id = request.args.get("supersedes_entry_id")
    if injury_case_id is not None:
        items = [e for e in items if e["injury_case_id"] == injury_case_id]
    if athlete_id is not None:
        items = [e for e in items if e["athlete_id"] == athlete_id]
    if entry_date is not None:
        items = [e for e in items if e["entry_date"] == entry_date]
    if is_current is not None:
        want = is_current.strip().lower() == "true"
        items = [e for e in items if e["is_current"] == want]
    if supersedes_entry_id is not None:
        items = [e for e in items if e["supersedes_entry_id"] == supersedes_entry_id]
    return ok_list([daily_status_entry_json(e) for e in items])


@bp.route("/daily-status-entries/<entryId>", methods=["GET"])
def get_daily_status_entry(entryId):
    require_roles(*ENTRY_READERS)
    e = STORE["daily_status_entries"].get(entryId)
    if e is None:
        raise not_found("DailyStatusEntry not found")
    return ok_obj(daily_status_entry_json(e))
