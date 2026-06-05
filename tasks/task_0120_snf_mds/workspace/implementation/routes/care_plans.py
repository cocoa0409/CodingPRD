"""CarePlan and CarePlanGoal endpoints (PRD §3.7)."""
from flask import request

import db
import errors
import response
import serialize
import validation as V
from clock import now_iso
from gate import gate
from services import lookups
from services.transitions import _cascade_discontinue_goals


GOAL_STATUSES = {"OPEN", "IN_PROGRESS", "MET", "DISCONTINUED"}


def register(app):
    # ---- CarePlan creation / listing under an admission ----
    @app.route("/snf/admissions/<aid>/care-plans", methods=["POST"])
    def create_care_plan(aid):
        gate(["Physician", "MdsCoordinator"])
        lookups.get_admission(aid)
        body = V.get_body()
        interval = V.opt(body, "review_interval_days", 90)
        interval = V.as_int(interval, "review_interval_days", minimum=1)
        obj = {
            "admission_id": aid,
            "review_interval_days": interval,
            "last_reviewed_at": None,
            "open_goal_count": 0,
            "status": "DRAFT",
        }
        db.stamp_create(obj)
        db.care_plans[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/admissions/<aid>/care-plans", methods=["GET"])
    def list_care_plans(aid):
        gate(["Physician", "MdsCoordinator"])
        lookups.get_admission(aid)
        limit, offset = V.pagination(request.args)
        rows = lookups.care_plans_for_admission(aid)
        status = request.args.get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/care-plans/<cid>", methods=["GET"])
    def get_care_plan(cid):
        gate(["Physician", "MdsCoordinator"])
        obj = lookups.get_care_plan(cid)
        return response.success(serialize.public(obj), 200)

    # ---- Goals ----
    @app.route("/snf/care-plans/<cid>/goals", methods=["POST"])
    def add_goal(cid):
        gate(["Physician", "MdsCoordinator"])
        plan = lookups.get_care_plan(cid)
        body = V.get_body()
        description = V.as_str(V.require(body, "description"), "description")
        target_date = V.require(body, "target_date")
        V.as_datetime(target_date, "target_date")
        obj = {
            "care_plan_id": cid,
            "description": description,
            "target_date": target_date,
            "status": "OPEN",
        }
        db.stamp_create(obj)
        db.care_plan_goals[obj["id"]] = obj
        # Adding a goal recomputes the plan's open_goal_count (PRD §3.7).
        lookups.recompute_open_goal_count(cid)
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/care-plans/<cid>/goals", methods=["GET"])
    def list_goals(cid):
        gate(["Physician", "MdsCoordinator"])
        lookups.get_care_plan(cid)
        limit, offset = V.pagination(request.args)
        rows = lookups.goals_for_plan(cid)
        status = request.args.get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/goals/<gid>", methods=["PATCH"])
    def update_goal(gid):
        gate(["Physician", "MdsCoordinator"])
        goal = lookups.get_goal(gid)
        body = V.get_body()
        status = V.as_enum(V.require(body, "status"), "status", GOAL_STATUSES)
        goal["status"] = status
        db.touch(goal)
        # Updating a goal recomputes the parent plan's open_goal_count (PRD §3.7).
        lookups.recompute_open_goal_count(goal["care_plan_id"])
        return response.success(serialize.public(goal), 200)

    # ---- CarePlan lifecycle (Physician) ----
    @app.route("/snf/care-plans/<cid>/activate", methods=["POST"])
    def activate_care_plan(cid):
        gate(["Physician"])
        plan = lookups.get_care_plan(cid)
        if plan["status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "care plan is not DRAFT")
        adm = db.admissions.get(plan["admission_id"])
        if adm is None or adm["status"] not in ("ACTIVE", "NON_COVERED"):
            raise errors.err(errors.ERR_INVALID_STATE,
                             "parent admission is not ACTIVE or NON_COVERED")
        # At least one OPEN goal (priority 23).
        if plan.get("open_goal_count", 0) < 1:
            raise errors.err(errors.ERR_GOAL_REQUIRED, "care plan has no OPEN goal")
        plan["status"] = "ACTIVE"
        plan["last_reviewed_at"] = now_iso()
        db.touch(plan)
        return response.success(serialize.public(plan), 200)

    @app.route("/snf/care-plans/<cid>/begin-review", methods=["POST"])
    def begin_review(cid):
        gate(["Physician"])
        plan = lookups.get_care_plan(cid)
        if plan["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "care plan is not ACTIVE")
        plan["status"] = "UNDER_REVIEW"
        db.touch(plan)
        return response.success(serialize.public(plan), 200)

    @app.route("/snf/care-plans/<cid>/complete-review", methods=["POST"])
    def complete_review(cid):
        gate(["Physician"])
        plan = lookups.get_care_plan(cid)
        if plan["status"] != "UNDER_REVIEW":
            raise errors.err(errors.ERR_INVALID_STATE, "care plan is not UNDER_REVIEW")
        plan["status"] = "ACTIVE"
        plan["last_reviewed_at"] = now_iso()
        db.touch(plan)
        return response.success(serialize.public(plan), 200)

    @app.route("/snf/care-plans/<cid>/close", methods=["POST"])
    def close_care_plan(cid):
        gate(["Physician"])
        plan = lookups.get_care_plan(cid)
        if plan["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "care plan is not ACTIVE")
        plan["status"] = "CLOSED"
        db.touch(plan)
        _cascade_discontinue_goals(cid)
        return response.success(serialize.public(plan), 200)
