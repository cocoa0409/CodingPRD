"""Care plan endpoints."""
import datetime as _dt
from flask import request

from clock import iso_now, now, parse_dt
from db import LOCK, get_db
from errors import APIError
from helpers import (new_entity, paginate, parse_pagination, require_body,
                     require_enum, require_field, touch)
from middleware import require_roles
from response import list_success, success
from services import audit, care_plan as cp_svc


TASK_TYPE = {"BATHING", "FEEDING", "TURNING", "MEDICATION", "VITALS"}
OUTCOME = {"COMPLETED", "REFUSED", "OMITTED"}


def _serialize(p):
    return dict(p)


def _serialize_te(t):
    return dict(t)


def register(app):

    @app.post("/elders/<eid>/care-plans")
    @require_roles("Supervisor")
    def create_plan(user_id, role, eid):
        body = require_body()
        based_on_assessment_id = require_field(body, "based_on_assessment_id", str)
        daily_tasks = require_field(body, "daily_tasks", list)
        # Validate daily_tasks shape
        for t in daily_tasks:
            if not isinstance(t, dict):
                raise APIError("ERR_VALIDATION", "daily_tasks entries must be objects", 422)
            tt = t.get("task_type")
            if tt not in TASK_TYPE:
                raise APIError("ERR_VALIDATION", "daily_tasks.task_type invalid", 422)
            fpd = t.get("frequency_per_day")
            if not isinstance(fpd, int) or isinstance(fpd, bool) or fpd < 1:
                raise APIError("ERR_VALIDATION", "daily_tasks.frequency_per_day must be int>=1", 422)
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            assessment = db.care_assessments.get(based_on_assessment_id)
            if assessment is None:
                raise APIError("ERR_FK_NOT_FOUND",
                               f"CareAssessment {based_on_assessment_id} not found", 404)
            if assessment.get("status") != "APPROVED":
                raise APIError("ERR_INVALID_STATE",
                               "based_on_assessment must be APPROVED", 409)
            plan = new_entity({
                "elder_id": eid,
                "based_on_assessment_id": based_on_assessment_id,
                "care_level_snapshot": None,
                "status": "DRAFT",
                "daily_tasks": daily_tasks,
                "review_cycle_days": None,
                "next_review_due_at": None,
                "activated_at": None,
            })
            db.care_plans[plan["id"]] = plan
            audit.log(role, user_id, "CarePlan", plan["id"],
                      "CREATE", None, "DRAFT")
            return success(_serialize(plan), status=201)

    @app.post("/care-plans/<pid>/activate")
    @require_roles("Supervisor")
    def activate_plan(user_id, role, pid):
        with LOCK:
            db = get_db()
            plan = db.care_plans.get(pid)
            if plan is None:
                raise APIError("ERR_NOT_FOUND", f"CarePlan {pid} not found", 404)
            cp_svc.activate(plan, user_id, role)
            return success(_serialize(plan))

    @app.post("/care-plans/<pid>/flag-review")
    @require_roles("Supervisor")
    def flag_review(user_id, role, pid):
        with LOCK:
            db = get_db()
            plan = db.care_plans.get(pid)
            if plan is None:
                raise APIError("ERR_NOT_FOUND", f"CarePlan {pid} not found", 404)
            cp_svc.flag_review(plan, user_id, role)
            return success(_serialize(plan))

    @app.post("/care-plans/<pid>/confirm-review")
    @require_roles("Supervisor")
    def confirm_review(user_id, role, pid):
        with LOCK:
            db = get_db()
            plan = db.care_plans.get(pid)
            if plan is None:
                raise APIError("ERR_NOT_FOUND", f"CarePlan {pid} not found", 404)
            cp_svc.confirm_review(plan, user_id, role)
            return success(_serialize(plan))

    @app.post("/care-plans/<pid>/supersede")
    @require_roles("Supervisor")
    def supersede_plan(user_id, role, pid):
        body = require_body()
        new_plan_id = require_field(body, "new_plan_id", str)
        with LOCK:
            db = get_db()
            plan = db.care_plans.get(pid)
            if plan is None:
                raise APIError("ERR_NOT_FOUND", f"CarePlan {pid} not found", 404)
            cp_svc.supersede(plan, new_plan_id, user_id, role)
            return success(_serialize(plan))

    @app.post("/care-plans/<pid>/task-executions")
    @require_roles("Caregiver")
    def record_task(user_id, role, pid):
        body = require_body()
        task_type = require_enum(body, "task_type", TASK_TYPE)
        scheduled_for_s = require_field(body, "scheduled_for", str)
        outcome = require_enum(body, "outcome", OUTCOME)
        notes = body.get("notes")
        # minutes_per_task is optional, but useful for a-la-carte billing
        minutes_per_task = body.get("minutes_per_task")
        if outcome != "COMPLETED" and not notes:
            raise APIError("ERR_VALIDATION", "notes required when outcome != COMPLETED", 422)
        try:
            scheduled_for_dt = parse_dt(scheduled_for_s)
        except Exception:
            raise APIError("ERR_VALIDATION", "scheduled_for must be ISO8601", 422)
        with LOCK:
            db = get_db()
            plan = db.care_plans.get(pid)
            if plan is None:
                raise APIError("ERR_NOT_FOUND", f"CarePlan {pid} not found", 404)
            if plan.get("status") != "ACTIVE":
                raise APIError("ERR_INVALID_STATE",
                               "CarePlan must be ACTIVE to record tasks", 409)
            # Record-window check (priority 18) +/- 4h
            current = now()
            delta = abs((current - scheduled_for_dt).total_seconds())
            if delta > 4 * 3600:
                raise APIError("ERR_TASK_RECORD_WINDOW",
                               "Task must be recorded within +/- 4h of scheduled_for", 422)
            te = new_entity({
                "care_plan_id": pid,
                "task_type": task_type,
                "scheduled_for": scheduled_for_s,
                "executed_at": iso_now(),
                "caregiver_id": user_id,
                "outcome": outcome,
                "notes": notes,
                "minutes_per_task": minutes_per_task,
            }, versioned=False)
            db.task_executions[te["id"]] = te
            return success(_serialize_te(te), status=201)

    @app.get("/care-plans/<pid>")
    @require_roles("Admin", "Supervisor", "Nurse", "Caregiver")
    def get_plan(user_id, role, pid):
        db = get_db()
        plan = db.care_plans.get(pid)
        if plan is None:
            raise APIError("ERR_NOT_FOUND", f"CarePlan {pid} not found", 404)
        return success(_serialize(plan))

    @app.get("/care-plans/<pid>/task-executions")
    @require_roles("Admin", "Supervisor", "Nurse", "Caregiver")
    def list_task_executions(user_id, role, pid):
        limit, offset = parse_pagination()
        type_f = request.args.get("task_type")
        outcome_f = request.args.get("outcome")
        db = get_db()
        if db.care_plans.get(pid) is None:
            raise APIError("ERR_NOT_FOUND", f"CarePlan {pid} not found", 404)
        items = [t for t in db.task_executions.values() if t["care_plan_id"] == pid]
        if type_f:
            items = [t for t in items if t["task_type"] == type_f]
        if outcome_f:
            items = [t for t in items if t["outcome"] == outcome_f]
        items.sort(key=lambda t: t["created_at"])
        page, total = paginate(items, limit, offset)
        return list_success([_serialize_te(t) for t in page], limit, offset, total)
