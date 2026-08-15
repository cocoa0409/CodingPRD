"""Student plan endpoints: create, pause/resume/exit/cancel, probes, sessions,
plus flat read/list aliases."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from errors import (
    err, ERR_PLAN_NOT_FOUND, ERR_STUDENT_NOT_FOUND, ERR_CATALOG_NOT_FOUND,
    ERR_INTERVENTIONIST_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_CATALOG_MISMATCH, ERR_CAPACITY_EXCEEDED,
    ERR_PROBE_NOT_DUE, ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_string, req_int, req_enum, req_date, base_fields, base_fields_append_only,
    paginate, sort_created, touch, parse_date,
)
from response import success_object, success_list
from services import (
    SESSION_OUTCOMES, EXIT_KINDS,
    serialize_plan, serialize_probe, serialize_session, serialize_referral,
    resolve_student, resolve_plan, plans_of_student, probes_of_plan,
    sessions_of_plan, ledger_adjust, propose_movement, pin_aimline_params,
    compute_aimline, compute_slope_decision, compute_fidelity_pct,
    create_referral_with_cascade, has_open_referral,
)
from clock import today_date

bp = Blueprint("plans", __name__)


def _check_plan_ownership(user_id, role, plan):
    """PRD §2.1: for InterventionistRole, X-User-ID is the acting Interventionist's
    id; resources referencing an interventionist compare their FK to it."""
    if role == "InterventionistRole" and plan["interventionist_id"] != user_id:
        raise err(ERR_INSUFFICIENT_PERMISSIONS, 403,
                  "Interventionist may only act on plans assigned to them")


def _check_plan_occ(body, plan):
    expected = body.get("expected_plan_version")
    if expected is None:
        raise err(ERR_INVALID_REQUEST, 400, "Missing required field: expected_plan_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        if isinstance(expected, float) and expected.is_integer():
            expected = int(expected)
        else:
            raise err(ERR_INVALID_REQUEST, 400, "expected_plan_version must be an integer")
    if expected != plan["version"]:
        raise err(ERR_STALE_VERSION, 412,
                  "expected_plan_version does not match current plan version")


def _check_student_occ(body, student):
    expected = body.get("expected_student_version")
    if expected is None:
        raise err(ERR_INVALID_REQUEST, 400, "Missing required field: expected_student_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        if isinstance(expected, float) and expected.is_integer():
            expected = int(expected)
        else:
            raise err(ERR_INVALID_REQUEST, 400, "expected_student_version must be an integer")
    if expected != student["version"]:
        raise err(ERR_STALE_VERSION, 412,
                  "expected_student_version does not match current student version")


# ---------- Plan creation ----------

@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans")
def create_plan(districtId, schoolId, studentId):
    require_role("TeamLead", "DistrictCoordinator")
    body = get_json_body()
    check_unknown_fields(body, {"catalog_entry_id", "interventionist_id", "expected_student_version"})
    require_fields(body, ["catalog_entry_id", "interventionist_id", "expected_student_version"])
    catalog_entry_id = req_string(body, "catalog_entry_id")
    interventionist_id = req_string(body, "interventionist_id")
    student = resolve_student(districtId, schoolId, studentId)
    # Body-FK existence (validation pipeline stage 4, PRD §2.5).
    catalog = DB.catalog_entries.get(catalog_entry_id)
    if catalog is None or catalog["district_id"] != districtId:
        raise err(ERR_CATALOG_NOT_FOUND, 404, "catalog_entry_id does not exist (within district)")
    iv = DB.interventionists.get(interventionist_id)
    if iv is None or iv["school_id"] != schoolId:
        raise err(ERR_INTERVENTIONIST_NOT_FOUND, 404, "interventionist_id does not exist (within school)")
    _check_student_occ(body, student)
    # Plan-to-catalog matching (PRD §3.5).
    if (not catalog["is_active"]
            or catalog["subject"] not in iv["subjects"]
            or not (catalog["grade_min"] <= student["grade_level"] <= catalog["grade_max"])
            or catalog["tier_target"] != student["current_tier"]):
        raise err(ERR_CATALOG_MISMATCH, 422,
                  "Catalog entry inactive, subject not served by interventionist, "
                  "grade out of range, or tier_target != student.current_tier")
    weekly_cost = catalog["session_minutes"] * catalog["sessions_per_week"]
    # Inclusive capacity check (PRD §2.8): landing exactly on capacity is allowed.
    if iv["committed_minutes_per_week"] + weekly_cost > iv["weekly_minute_capacity"]:
        raise err(ERR_CAPACITY_EXCEEDED, 422,
                  "Plan weekly_minute_cost would exceed interventionist capacity")
    today = today_date()
    interval_days = 7 if catalog["probe_frequency"] == "WEEKLY" else 14
    p = base_fields()
    p.update({
        "student_id": studentId,
        "catalog_entry_id": catalog_entry_id,
        "interventionist_id": interventionist_id,
        "tier_at_start": student["current_tier"],
        "started_on": today.isoformat(),
        "weekly_minute_cost": weekly_cost,
        "probe_due_on": (today + timedelta(days=interval_days)).isoformat(),
        "fidelity_pct": 100,
        "status": "ACTIVE",
        "_session_minutes": catalog["session_minutes"],
        "_probe_frequency": catalog["probe_frequency"],
    })
    pin_aimline_params(p, student, catalog)
    DB.plans[p["id"]] = p
    ledger_adjust(iv, weekly_cost)
    touch(student)
    return success_object(serialize_plan(p), status=201)


def _list_plans(studentId):
    status_filter = request.args.get("status")
    items = plans_of_student(studentId)
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_plan(p) for p in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans")
def list_plans(districtId, schoolId, studentId):
    require_role(*ALL_ROLES)
    resolve_student(districtId, schoolId, studentId)
    return _list_plans(studentId)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>")
def get_plan(districtId, schoolId, studentId, planId):
    require_role(*ALL_ROLES)
    p = resolve_plan(districtId, schoolId, studentId, planId)
    return success_object(serialize_plan(p))


# ---------- Plan lifecycle actions ----------

@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>/pause")
def pause_plan(districtId, schoolId, studentId, planId):
    user_id, role = require_role("InterventionistRole", "TeamLead")
    body = get_json_body()
    check_unknown_fields(body, {"expected_plan_version"})
    p = resolve_plan(districtId, schoolId, studentId, planId)
    _check_plan_ownership(user_id, role, p)
    _check_plan_occ(body, p)
    if p["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, 409, "Only an ACTIVE plan can be paused")
    student = DB.students[studentId]
    if student["current_tier"] != p["tier_at_start"]:
        raise err(ERR_INVALID_STATE, 409,
                  "Student current_tier no longer matches plan tier_at_start")
    p["status"] = "PAUSED"
    iv = DB.interventionists.get(p["interventionist_id"])
    if iv is not None:
        ledger_adjust(iv, -p["weekly_minute_cost"])
    touch(p)
    return success_object(serialize_plan(p))


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>/resume")
def resume_plan(districtId, schoolId, studentId, planId):
    user_id, role = require_role("InterventionistRole", "TeamLead")
    body = get_json_body()
    check_unknown_fields(body, {"expected_plan_version"})
    p = resolve_plan(districtId, schoolId, studentId, planId)
    _check_plan_ownership(user_id, role, p)
    _check_plan_occ(body, p)
    if p["status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, 409, "Only a PAUSED plan can be resumed")
    iv = DB.interventionists.get(p["interventionist_id"])
    if iv is not None:
        # Capacity re-check on resume (PRD §2.8): headroom may have filled.
        if iv["committed_minutes_per_week"] + p["weekly_minute_cost"] > iv["weekly_minute_capacity"]:
            raise err(ERR_CAPACITY_EXCEEDED, 422,
                      "Interventionist no longer has headroom for this plan")
    p["status"] = "ACTIVE"
    if iv is not None:
        ledger_adjust(iv, p["weekly_minute_cost"])
    touch(p)
    return success_object(serialize_plan(p))


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>/exit")
def exit_plan(districtId, schoolId, studentId, planId):
    require_role("TeamLead")
    body = get_json_body()
    check_unknown_fields(body, {"expected_plan_version", "exit_kind"})
    require_fields(body, ["expected_plan_version", "exit_kind"])
    exit_kind = req_enum(body, "exit_kind", EXIT_KINDS)
    p = resolve_plan(districtId, schoolId, studentId, planId)
    _check_plan_occ(body, p)
    if p["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, 409, "Only an ACTIVE plan can be exited")
    student = DB.students[studentId]
    district = DB.districts[districtId]
    probes = probes_of_plan(planId)
    if exit_kind == "EXIT_RESPONSIVE":
        # Evidence bar (PRD §3.8): latest slope_decision RESPONSIVE and >= 4 probes.
        if len(probes) < 4 or probes[-1]["slope_decision"] != "RESPONSIVE":
            raise err(ERR_INVALID_STATE, 409,
                      "EXIT_RESPONSIVE requires >= 4 probes and latest slope_decision RESPONSIVE")
    else:  # EXIT_NO_PROGRESS
        last4 = probes[-4:]
        if len(last4) < 4 or any(pr["slope_decision"] != "NON_RESPONSIVE" for pr in last4):
            raise err(ERR_INVALID_STATE, 409,
                      "EXIT_NO_PROGRESS requires the latest 4 probes all NON_RESPONSIVE")
        if student["weeks_at_tier3_unresponsive"] >= district["sped_referral_min_weeks"]:
            raise err(ERR_INVALID_STATE, 409,
                      "Student at the referral threshold must use the referral flow")
    iv = DB.interventionists.get(p["interventionist_id"])
    if iv is not None:
        ledger_adjust(iv, -p["weekly_minute_cost"])
    p["status"] = exit_kind
    touch(p)
    if exit_kind == "EXIT_RESPONSIVE":
        # Auto-propose a step-down movement (PRD §3.8).
        to_tier = "TIER_1" if p["tier_at_start"] == "TIER_2" else "TIER_2"
        propose_movement(student, to_tier, "Auto-proposed on responsive plan exit")
    return success_object(serialize_plan(p))


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>/cancel")
def cancel_plan(districtId, schoolId, studentId, planId):
    require_role("TeamLead")
    body = get_json_body()
    check_unknown_fields(body, {"expected_plan_version"})
    p = resolve_plan(districtId, schoolId, studentId, planId)
    _check_plan_occ(body, p)
    if p["status"] == "ACTIVE":
        # An ACTIVE plan may be cancelled only while no probe exists (PRD §3.8).
        if probes_of_plan(planId):
            raise err(ERR_INVALID_STATE, 409,
                      "An ACTIVE plan with recorded probes cannot be cancelled")
        iv = DB.interventionists.get(p["interventionist_id"])
        if iv is not None:
            ledger_adjust(iv, -p["weekly_minute_cost"])
    elif p["status"] == "PAUSED":
        # Minutes were already released at pause time; no further adjustment.
        pass
    else:
        raise err(ERR_INVALID_STATE, 409, "Only ACTIVE or PAUSED plans can be cancelled")
    p["status"] = "CANCELLED"
    touch(p)
    return success_object(serialize_plan(p))


# ---------- Progress probes ----------

@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>/probes")
def create_probe(districtId, schoolId, studentId, planId):
    user_id, role = require_role("InterventionistRole", "Teacher")
    body = get_json_body()
    check_unknown_fields(body, {"administered_on", "score"})
    require_fields(body, ["administered_on", "score"])
    administered_on = req_date(body, "administered_on")
    score = req_int(body, "score")
    p = resolve_plan(districtId, schoolId, studentId, planId)
    _check_plan_ownership(user_id, role, p)
    # State precedes business: non-ACTIVE plan surfaces ERR_INVALID_STATE (PRD §2.5).
    if p["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, 409, "Probes may only be recorded on an ACTIVE plan")
    if today_date() < parse_date(p["probe_due_on"]):
        raise err(ERR_PROBE_NOT_DUE, 422, "Probe attempted before plan.probe_due_on")
    student = DB.students[studentId]
    district = DB.districts[districtId]
    k = len(probes_of_plan(planId)) + 1
    pr = base_fields_append_only()
    pr.update({
        "plan_id": planId,
        "administered_on": administered_on,
        "score": score,
        "aimline_score": compute_aimline(p, k),
        "slope_decision": None,
    })
    DB.probes[pr["id"]] = pr
    pr["slope_decision"] = compute_slope_decision(p)
    # Unresponsiveness counter (PRD §3.6).
    if pr["slope_decision"] == "RESPONSIVE":
        if student["weeks_at_tier3_unresponsive"] != 0:
            student["weeks_at_tier3_unresponsive"] = 0
            touch(student)
    else:
        if p["tier_at_start"] == "TIER_3":
            student["weeks_at_tier3_unresponsive"] += 1
            touch(student)
    # Advance probe cadence; probe_due_on changes every probe -> plan mutation.
    interval_days = 7 if p["_probe_frequency"] == "WEEKLY" else 14
    p["probe_due_on"] = (parse_date(p["probe_due_on"]) + timedelta(days=interval_days)).isoformat()
    touch(p)
    # Auto-referral cascade (PRD §3.6).
    if (p["tier_at_start"] == "TIER_3"
            and pr["slope_decision"] == "NON_RESPONSIVE"
            and student["weeks_at_tier3_unresponsive"] >= district["sped_referral_min_weeks"]
            and not has_open_referral(studentId)):
        create_referral_with_cascade(student, p)
    return success_object(serialize_probe(pr), status=201)


def _list_probes(planId):
    items = probes_of_plan(planId)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_probe(pr) for pr in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>/probes")
def list_probes(districtId, schoolId, studentId, planId):
    require_role(*ALL_ROLES)
    resolve_plan(districtId, schoolId, studentId, planId)
    return _list_probes(planId)


# ---------- Intervention sessions (fidelity) ----------

@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>/sessions")
def create_session(districtId, schoolId, studentId, planId):
    user_id, role = require_role("InterventionistRole")
    body = get_json_body()
    check_unknown_fields(body, {"scheduled_on", "minutes", "outcome"})
    require_fields(body, ["scheduled_on", "minutes", "outcome"])
    scheduled_on = req_date(body, "scheduled_on")
    minutes = req_int(body, "minutes")
    outcome = req_enum(body, "outcome", SESSION_OUTCOMES)
    p = resolve_plan(districtId, schoolId, studentId, planId)
    _check_plan_ownership(user_id, role, p)
    if p["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, 409, "Sessions may only be recorded on an ACTIVE plan")
    if minutes != p["_session_minutes"]:
        raise err(ERR_INVALID_REQUEST, 400,
                  "minutes must equal the catalog session_minutes pinned at plan activation")
    se = base_fields_append_only()
    se.update({
        "plan_id": planId,
        "scheduled_on": scheduled_on,
        "minutes": minutes,
        "outcome": outcome,
    })
    DB.sessions[se["id"]] = se
    new_fidelity = compute_fidelity_pct(p)
    if new_fidelity != p["fidelity_pct"]:
        p["fidelity_pct"] = new_fidelity
        touch(p)
    return success_object(serialize_session(se), status=201)


def _list_sessions(planId):
    outcome_filter = request.args.get("outcome")
    items = sessions_of_plan(planId)
    if outcome_filter is not None:
        items = [se for se in items if se["outcome"] == outcome_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_session(se) for se in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>/plans/<planId>/sessions")
def list_sessions(districtId, schoolId, studentId, planId):
    require_role(*ALL_ROLES)
    resolve_plan(districtId, schoolId, studentId, planId)
    return _list_sessions(planId)


# ---------- Flat aliases ----------

@bp.get("/plans/<planId>")
def get_plan_flat(planId):
    require_role(*ALL_ROLES)
    p = DB.plans.get(planId)
    if p is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "planId does not exist")
    return success_object(serialize_plan(p))


@bp.get("/students/<id>/plans")
def list_plans_flat(id):
    require_role(*ALL_ROLES)
    st = DB.students.get(id)
    if st is None:
        raise err(ERR_STUDENT_NOT_FOUND, 404, "student id does not exist")
    return _list_plans(id)


@bp.get("/plans/<id>/probes")
def list_probes_flat(id):
    require_role(*ALL_ROLES)
    p = DB.plans.get(id)
    if p is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "plan id does not exist")
    return _list_probes(id)


@bp.get("/plans/<id>/sessions")
def list_sessions_flat(id):
    require_role(*ALL_ROLES)
    p = DB.plans.get(id)
    if p is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "plan id does not exist")
    return _list_sessions(id)


@bp.get("/plans/<id>/sped-referrals")
def list_referrals_for_plan_flat(id):
    require_role(*ALL_ROLES)
    p = DB.plans.get(id)
    if p is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "plan id does not exist")
    items = sort_created(
        r for r in DB.sped_referrals.values() if r["triggered_plan_id"] == id
    )
    page, limit, offset, total = paginate(items)
    return success_list([serialize_referral(r) for r in page], limit, offset, total)


@bp.get("/probes/<probeId>")
def get_probe_flat(probeId):
    require_role(*ALL_ROLES)
    pr = DB.probes.get(probeId)
    if pr is None:
        raise err(ERR_INVALID_REQUEST, 404, "probeId does not exist")
    return success_object(serialize_probe(pr))


@bp.get("/sessions/<sessionId>")
def get_session_flat(sessionId):
    require_role(*ALL_ROLES)
    se = DB.sessions.get(sessionId)
    if se is None:
        raise err(ERR_INVALID_REQUEST, 404, "sessionId does not exist")
    return success_object(serialize_session(se))
