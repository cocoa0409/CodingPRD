"""OnboardingCase endpoints (PRD §3.2, §3.6, §3.9) and case sub-resources."""

import copy
from datetime import datetime, time as dtime, timedelta, timezone

from flask import Blueprint, request

import calc
from auth import require_roles, ALL_ROLES
from db import store, clock
from errors import (ApiError, ERR_CASE_NOT_FOUND, ERR_ROLE_PROFILE_NOT_FOUND,
                    ERR_EMPLOYEE_NOT_FOUND, ERR_NEW_HIRE_NOT_FOUND,
                    ERR_ROLE_PROFILE_NOT_PUBLISHED, ERR_EMPLOYEE_NOT_ACTIVE,
                    ERR_DUPLICATE_ACTIVE_CASE, ERR_DUAL_ROLE_ASSIGNMENT,
                    ERR_START_DATE_IN_PAST, ERR_INVALID_CASE_PHASE,
                    ERR_CASE_TERMINAL, ERR_REQUIRED_TASKS_INCOMPLETE,
                    ERR_NOT_RESOURCE_OWNER, ERR_SESSION_NOT_FOUND,
                    ERR_SESSION_NOT_BOOKABLE, ERR_SESSION_FULL,
                    ERR_ALREADY_BOOKED, ERR_NO_BOOKING_TO_CANCEL,
                    ERR_STALE_VERSION)
from helpers import (new_record, touch, get_or_404, children, find_one,
                     ser_case, ser_task, ser_clearance, ser_order,
                     ser_checkin, ser_training, ser_cycle, ser_handoff,
                     ser_survey, sort_created, sort_indexed,
                     session_booked_count)
from sweep import (TERMINAL_PHASES, refresh_health, reeval_day_one_gate,
                   withdraw_case)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_int, as_date, as_enum, as_version, bad, fmt_dt)

bp = Blueprint("cases", __name__)

BENEFITS_TIERS = ("STANDARD", "PLUS", "PREMIUM")
PHASES = ("PRE_BOARDING", "CLEARANCE_IN_PROGRESS", "PROVISIONING",
          "DAY_ONE_READY", "IN_PROGRESS", "PROBATION", "COMPLETED",
          "WITHDRAWN", "REVOKED", "SEPARATED")
BOOKABLE_PHASES = ("PROVISIONING", "DAY_ONE_READY")


def _case_or_404(cid):
    return get_or_404("cases", cid, ERR_CASE_NOT_FOUND, "OnboardingCase")


def _generate_children(case, prof):
    """Generative creation: tasks, trainings, check-ins, probation cycle 1 —
    all from the pinned profile template."""
    start = case["_start_d"]
    cid = case["id"]
    for idx, t in enumerate(prof["preboarding_tasks"]):
        due = datetime.combine(start, dtime(23, 59, 59), tzinfo=timezone.utc)
        new_record("tasks", {
            "case_id": cid, "task_kind": t["task_kind"], "title": t["title"],
            "is_required": t["is_required"], "status": "PENDING",
            "document_ref": None, "note": None, "review_note": None,
            "reject_count": 0, "due_at": fmt_dt(due), "sort_index": idx,
            "_due_dt": due,
        })
    for idx, m in enumerate(prof["training_modules"]):
        due = datetime.combine(start + timedelta(days=m["due_offset_days"]),
                               dtime(23, 59, 59), tzinfo=timezone.utc)
        new_record("trainings", {
            "case_id": cid, "module_code": m["module_code"],
            "due_at": fmt_dt(due), "status": "ASSIGNED", "score": None,
            "completed_at": None, "completed_late": False, "sort_index": idx,
            "_due_dt": due, "_completed_dt": None,
        })
    for idx, slot in enumerate(calc.checkin_cadence(case)):
        new_record("checkins", {
            "case_id": cid, "owner_employee_id": slot["owner_employee_id"],
            "kind": slot["kind"], "scheduled_at": fmt_dt(slot["_sched_dt"]),
            "status": "SCHEDULED", "productivity_rating": None, "notes": None,
            "completed_at": None, "sort_index": idx,
            "_sched_dt": slot["_sched_dt"], "_completed_dt": None,
        })
    eval_due = datetime.combine(start + timedelta(days=prof["probation_days"]),
                                dtime(17, 0, 0), tzinfo=timezone.utc)
    new_record("cycles", {
        "case_id": cid, "cycle_index": 1, "evaluation_due_at": fmt_dt(eval_due),
        "status": "ACTIVE", "outcome_rating": None, "notes": None,
        "evaluated_at": None, "_eval_due_dt": eval_due, "_evaluated_dt": None,
    })


@bp.post("/api/onboarding-cases")
def create_case():
    require_roles("HRAdmin")
    body = get_body()
    # Stage 3: request shape
    new_hire_id = as_str(req_present(body, "new_hire_id"), "new_hire_id")
    role_profile_id = as_str(req_present(body, "role_profile_id"),
                             "role_profile_id")
    manager_id = as_str(req_present(body, "manager_id"), "manager_id")
    buddy_id = as_str(req_present(body, "buddy_id"), "buddy_id")
    start_d = as_date(req_present(body, "start_date"), "start_date")
    base_salary = as_int(req_present(body, "base_salary_cents"),
                         "base_salary_cents")
    signing_bonus = as_int(body.get("signing_bonus_cents", 0),
                           "signing_bonus_cents")
    relocation = as_int(body.get("relocation_stipend_cents", 0),
                        "relocation_stipend_cents")
    benefits_tier = as_enum(req_present(body, "benefits_tier"),
                            "benefits_tier", BENEFITS_TIERS)
    # Stage 4: existence of body-referenced ids (PRD order)
    profile = get_or_404("role_profiles", role_profile_id,
                         ERR_ROLE_PROFILE_NOT_FOUND, "RoleProfile")
    new_hire = get_or_404("new_hires", new_hire_id, ERR_NEW_HIRE_NOT_FOUND,
                          "NewHire")
    manager = get_or_404("employees", manager_id, ERR_EMPLOYEE_NOT_FOUND,
                         "Employee")
    buddy = get_or_404("employees", buddy_id, ERR_EMPLOYEE_NOT_FOUND,
                       "Employee")
    # Stage 8: referential usability
    if profile["status"] != "PUBLISHED":
        raise ApiError(ERR_ROLE_PROFILE_NOT_PUBLISHED, 409,
                       "RoleProfile must be PUBLISHED")
    if manager["employment_status"] != "ACTIVE":
        raise ApiError(ERR_EMPLOYEE_NOT_ACTIVE, 409,
                       "manager_id employee is not ACTIVE")
    if buddy["employment_status"] != "ACTIVE":
        raise ApiError(ERR_EMPLOYEE_NOT_ACTIVE, 409,
                       "buddy_id employee is not ACTIVE")
    for other in store["cases"].values():
        if other["new_hire_id"] == new_hire_id and \
                other["phase"] not in TERMINAL_PHASES:
            raise ApiError(ERR_DUPLICATE_ACTIVE_CASE, 409,
                           "New hire already has a non-terminal case")
    # Stage 9: dual-role constraint
    if manager_id == buddy_id:
        raise ApiError(ERR_DUAL_ROLE_ASSIGNMENT, 422,
                       "manager_id and buddy_id must differ")
    # Stage 10: temporal sanity — start_date must not precede the logical date
    if start_d < clock.current.date():
        raise ApiError(ERR_START_DATE_IN_PAST, 409,
                       "start_date precedes the current logical date")

    case = new_record("cases", {
        "new_hire_id": new_hire_id,
        "role_profile_id": role_profile_id,
        "pinned_profile_version": profile["published_version"],
        "manager_id": manager_id,
        "buddy_id": buddy_id,
        "start_date": start_d.isoformat(),
        "base_salary_cents": base_salary,
        "signing_bonus_cents": signing_bonus,
        "relocation_stipend_cents": relocation,
        "benefits_tier": benefits_tier,
        "phase": "PRE_BOARDING",
        "health": "ON_TRACK",
        "health_score": 100,
        "orientation_session_id": None,
        "orientation_rsvp": "NONE",
        "manager_reassignment_required": False,
        "_start_d": start_d,
        "_profile": copy.deepcopy({k: profile[k] for k in (
            "preboarding_tasks", "training_modules", "equipment_items",
            "access_grants", "probation_days", "max_probation_extensions",
            "extension_days", "buddy_checkin_interval_days",
            "buddy_checkin_count", "manager_checkin_offsets_days",
            "provisioning_sla_hours")}),
    })
    _generate_children(case, case["_profile"])
    return success(ser_case(case), 201)


@bp.get("/api/onboarding-cases")
def list_cases():
    require_roles(*ALL_ROLES)
    limit, offset = page_params()
    q = request.args
    records = list(store["cases"].values())
    for f in ("new_hire_id", "role_profile_id", "manager_id", "buddy_id",
              "orientation_session_id"):
        if f in q and q.get(f) is not None:
            records = [c for c in records if c.get(f) == q[f]]
    if "phase" in q and q.get("phase") is not None:
        if q["phase"] not in PHASES:
            bad(f"phase must be one of {sorted(PHASES)}")
        records = [c for c in records if c["phase"] == q["phase"]]
    if "health" in q and q.get("health") is not None:
        if q["health"] not in ("ON_TRACK", "AT_RISK"):
            bad("health must be one of AT_RISK, ON_TRACK")
        records = [c for c in records if c["health"] == q["health"]]
    records = sort_created(records)
    return paged([ser_case(c) for c in records], limit, offset)


@bp.get("/api/onboarding-cases/<cid>")
def get_case(cid):
    require_roles(*ALL_ROLES)
    case = _case_or_404(cid)
    refresh_health(case)
    return success(ser_case(case))


@bp.get("/api/onboarding-cases/<cid>/summary")
def case_summary(cid):
    require_roles(*ALL_ROLES)
    case = _case_or_404(cid)
    refresh_health(case)
    open_handoffs = sum(1 for h in children("handoffs", cid)
                        if h["status"] in ("DRAFT", "TRANSMITTED"))
    return success({
        "health_score": case["health_score"],
        "health": case["health"],
        "phase": case["phase"],
        "estimated_ttp_days": calc.estimated_ttp_days(case),
        "actual_ttp_days": calc.actual_ttp_days(case),
        "open_handoff_count": open_handoffs,
    })


@bp.post("/api/onboarding-cases/<cid>/submit-for-clearance")
def submit_for_clearance(cid):
    uid, _ = require_roles("HRAdmin")
    case = _case_or_404(cid)
    # Stage 6: phase gate (terminal lockdown first)
    if case["phase"] in TERMINAL_PHASES:
        raise ApiError(ERR_CASE_TERMINAL, 409, "Case is terminal")
    if case["phase"] != "PRE_BOARDING":
        raise ApiError(ERR_INVALID_CASE_PHASE, 409,
                       "submit-for-clearance requires phase PRE_BOARDING")
    # Stage 7: compliance gate — every required task APPROVED or WAIVED
    for t in children("tasks", cid):
        if t["is_required"] and t["status"] not in ("APPROVED", "WAIVED"):
            raise ApiError(ERR_REQUIRED_TASKS_INCOMPLETE, 409,
                           "Required tasks must be APPROVED or WAIVED")
    new_record("clearances", {
        "case_id": cid, "status": "IN_PROGRESS",
        "background_status": "PENDING", "reference_status": "PENDING",
        "initiated_by_user_id": uid, "adjudicated_by_user_id": None,
        "adjudication_rationale": None, "override_clear": False,
    })
    case["phase"] = "CLEARANCE_IN_PROGRESS"
    touch(case)
    return success(ser_case(case))


@bp.post("/api/onboarding-cases/<cid>/withdraw")
def withdraw(cid):
    require_roles("HRAdmin")
    case = _case_or_404(cid)
    if case["phase"] in TERMINAL_PHASES:
        raise ApiError(ERR_CASE_TERMINAL, 409, "Case is terminal")
    if case["phase"] not in ("PRE_BOARDING", "CLEARANCE_IN_PROGRESS",
                             "PROVISIONING", "DAY_ONE_READY"):
        raise ApiError(ERR_INVALID_CASE_PHASE, 409,
                       "withdraw requires a pre-day-one phase")
    withdraw_case(case)
    return success(ser_case(case))


@bp.post("/api/onboarding-cases/<cid>/reassign-manager")
def reassign_manager(cid):
    require_roles("HRAdmin")
    body = get_body()
    new_manager_id = as_str(req_present(body, "new_manager_id"),
                            "new_manager_id")
    case = _case_or_404(cid)
    new_manager = get_or_404("employees", new_manager_id,
                             ERR_EMPLOYEE_NOT_FOUND, "Employee")
    if case["phase"] in TERMINAL_PHASES:
        raise ApiError(ERR_CASE_TERMINAL, 409, "Case is terminal")
    if new_manager["employment_status"] != "ACTIVE":
        raise ApiError(ERR_EMPLOYEE_NOT_ACTIVE, 409,
                       "new_manager_id employee is not ACTIVE")
    if new_manager_id == case["buddy_id"]:
        raise ApiError(ERR_DUAL_ROLE_ASSIGNMENT, 422,
                       "new_manager_id must differ from buddy_id")

    case["manager_id"] = new_manager_id
    case["manager_reassignment_required"] = False
    # Regenerate future MANAGER milestones for the new owner: cancel the old
    # manager's live MANAGER check-ins, then re-run the cadence for slots
    # still in the future of the logical clock.
    now = clock.current
    for ci in children("checkins", cid):
        if ci["kind"] == "MANAGER" and ci["status"] in ("SCHEDULED", "MISSED"):
            ci["status"] = "CANCELLED"
            touch(ci)
    max_sort = max((c["sort_index"] for c in children("checkins", cid)),
                   default=-1)
    prof = case["_profile"]
    start = case["_start_d"]
    idx = max_sort + 1
    for m in sorted(prof["manager_checkin_offsets_days"]):
        d = calc.shift_off_weekend(start + timedelta(days=m))
        sched = datetime.combine(d, dtime(9, 0, 0), tzinfo=timezone.utc)
        if sched <= now:
            continue
        new_record("checkins", {
            "case_id": cid, "owner_employee_id": new_manager_id,
            "kind": "MANAGER", "scheduled_at": fmt_dt(sched),
            "status": "SCHEDULED", "productivity_rating": None, "notes": None,
            "completed_at": None, "sort_index": idx,
            "_sched_dt": sched, "_completed_dt": None,
        })
        idx += 1
    touch(case)
    refresh_health(case)
    return success(ser_case(case))


@bp.post("/api/onboarding-cases/<cid>/orientation-booking")
def book_orientation(cid):
    uid, role = require_roles("HRAdmin", "NewHire")
    body = get_body()
    session_id = as_str(req_present(body, "session_id"), "session_id")
    case = _case_or_404(cid)
    session = get_or_404("sessions", session_id, ERR_SESSION_NOT_FOUND,
                         "OrientationSession")
    # Stage 5: ownership for the NewHire caller
    if role == "NewHire" and case["new_hire_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "NewHire may only book its own case")
    # Stage 6: state gates — case lockdown/phase, session bookable, rsvp
    if case["phase"] in TERMINAL_PHASES:
        raise ApiError(ERR_CASE_TERMINAL, 409, "Case is terminal")
    if case["phase"] not in BOOKABLE_PHASES:
        raise ApiError(ERR_INVALID_CASE_PHASE, 409,
                       "Case phase does not permit orientation booking")
    if session["status"] in ("CANCELLED", "CONDUCTED"):
        raise ApiError(ERR_SESSION_NOT_BOOKABLE, 409,
                       "Session is not bookable")
    if case["orientation_rsvp"] not in ("NONE", "SESSION_CANCELLED"):
        raise ApiError(ERR_ALREADY_BOOKED, 409,
                       "Case already holds a booking")
    # Stage 9: capacity constraint
    if session_booked_count(session) >= session["capacity"]:
        raise ApiError(ERR_SESSION_FULL, 409, "Session is at capacity")
    case["orientation_session_id"] = session["id"]
    case["orientation_rsvp"] = "BOOKED"
    if session_booked_count(session) >= session["capacity"] and \
            session["status"] == "SCHEDULED":
        session["status"] = "FULL"
    touch(session)
    touch(case)
    reeval_day_one_gate(case)
    return success(ser_case(case))


@bp.post("/api/onboarding-cases/<cid>/orientation-booking/cancel")
def cancel_orientation_booking(cid):
    uid, role = require_roles("HRAdmin", "NewHire")
    case = _case_or_404(cid)
    if role == "NewHire" and case["new_hire_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "NewHire may only cancel its own case booking")
    if case["phase"] in TERMINAL_PHASES:
        raise ApiError(ERR_CASE_TERMINAL, 409, "Case is terminal")
    if case["orientation_rsvp"] != "BOOKED":
        raise ApiError(ERR_NO_BOOKING_TO_CANCEL, 409,
                       "Case holds no BOOKED orientation booking")
    session = store["sessions"].get(case["orientation_session_id"])
    case["orientation_rsvp"] = "NONE"
    case["orientation_session_id"] = None
    if session is not None:
        if session["status"] == "FULL" and \
                session_booked_count(session) < session["capacity"]:
            session["status"] = "SCHEDULED"
        touch(session)
    touch(case)
    reeval_day_one_gate(case)
    return success(ser_case(case))


# ------------------------------------------------- case sub-resource lists ----

@bp.get("/api/onboarding-cases/<cid>/tasks")
def case_tasks(cid):
    require_roles(*ALL_ROLES)
    _case_or_404(cid)
    limit, offset = page_params()
    records = sort_indexed(children("tasks", cid))
    return paged([ser_task(t) for t in records], limit, offset)


@bp.get("/api/onboarding-cases/<cid>/clearance-cases")
def case_clearances(cid):
    require_roles(*ALL_ROLES)
    _case_or_404(cid)
    limit, offset = page_params()
    records = sort_created(children("clearances", cid))
    return paged([ser_clearance(c) for c in records], limit, offset)


@bp.get("/api/onboarding-cases/<cid>/provisioning-orders")
def case_orders(cid):
    require_roles(*ALL_ROLES)
    _case_or_404(cid)
    limit, offset = page_params()
    records = sort_created(children("orders", cid))
    return paged([ser_order(o) for o in records], limit, offset)


@bp.get("/api/onboarding-cases/<cid>/check-ins")
def case_checkins(cid):
    require_roles(*ALL_ROLES)
    _case_or_404(cid)
    limit, offset = page_params()
    records = sort_indexed(children("checkins", cid))
    return paged([ser_checkin(c) for c in records], limit, offset)


@bp.get("/api/onboarding-cases/<cid>/training-assignments")
def case_trainings(cid):
    require_roles(*ALL_ROLES)
    _case_or_404(cid)
    limit, offset = page_params()
    records = sort_indexed(children("trainings", cid))
    return paged([ser_training(t) for t in records], limit, offset)


@bp.get("/api/onboarding-cases/<cid>/probation-cycles")
def case_cycles(cid):
    require_roles(*ALL_ROLES)
    _case_or_404(cid)
    limit, offset = page_params()
    records = sorted(children("cycles", cid),
                     key=lambda c: (c["cycle_index"], c["_seq"]))
    return paged([ser_cycle(c) for c in records], limit, offset)


@bp.get("/api/onboarding-cases/<cid>/payroll-handoffs")
def case_handoffs(cid):
    require_roles(*ALL_ROLES)
    _case_or_404(cid)
    limit, offset = page_params()
    records = sort_created(children("handoffs", cid))
    return paged([ser_handoff(h) for h in records], limit, offset)


@bp.get("/api/onboarding-cases/<cid>/surveys")
def case_surveys(cid):
    require_roles(*ALL_ROLES)
    _case_or_404(cid)
    limit, offset = page_params()
    records = sort_created(children("surveys", cid))
    return paged([ser_survey(s) for s in records], limit, offset)


# --------------------------------------------------------- payroll create ----

@bp.post("/api/onboarding-cases/<cid>/payroll-handoffs")
def create_handoff(cid):
    require_roles("HRAdmin")
    body = get_body()
    expected = as_version(req_present(body, "expected_case_version"),
                          "expected_case_version")
    fp_start = as_date(req_present(body, "first_period_start_date"),
                       "first_period_start_date")
    fp_end = as_date(req_present(body, "first_period_end_date"),
                     "first_period_end_date")
    if fp_end < fp_start:
        bad("first_period_end_date must be on or after first_period_start_date")
    case = _case_or_404(cid)
    # Stage 6: terminal lockdown, then phase gate
    if case["phase"] in TERMINAL_PHASES:
        raise ApiError(ERR_CASE_TERMINAL, 409, "Case is terminal")
    if case["phase"] not in ("DAY_ONE_READY", "IN_PROGRESS", "PROBATION"):
        raise ApiError(ERR_INVALID_CASE_PHASE, 409,
                       "Case phase does not permit handoff creation")
    # Stage 9: optimistic concurrency on the case version
    if expected != case["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_case_version does not match the case version")
    # Create-with-supersede: prior non-terminal handoffs become SUPERSEDED
    for h in children("handoffs", cid):
        if h["status"] in ("DRAFT", "TRANSMITTED"):
            h["status"] = "SUPERSEDED"
            touch(h)
    window_end = datetime.combine(case["_start_d"] + timedelta(days=30),
                                  dtime(23, 59, 59), tzinfo=timezone.utc)
    gross = calc.first_period_gross_cents(case, fp_start, fp_end)
    rec = new_record("handoffs", {
        "case_id": cid, "status": "DRAFT",
        "base_salary_cents": case["base_salary_cents"],
        "signing_bonus_cents": case["signing_bonus_cents"],
        "relocation_stipend_cents": case["relocation_stipend_cents"],
        "benefits_tier": case["benefits_tier"],
        "start_date": case["start_date"],
        "first_period_start_date": fp_start.isoformat(),
        "first_period_end_date": fp_end.isoformat(),
        "first_period_gross_cents": gross,
        "transmitted_at": None, "acknowledged_at": None,
        "benefits_window_end": fmt_dt(window_end),
        "benefits_window_breached": False,
        "rejection_reason": None,
        "_transmitted_dt": None, "_ack_dt": None, "_window_end_dt": window_end,
    })
    touch(case)
    return success(ser_handoff(rec), 201)
