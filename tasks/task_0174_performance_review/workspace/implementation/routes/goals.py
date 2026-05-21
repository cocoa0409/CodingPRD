"""Goal endpoints — children of ReviewCase (PRD §3.3)."""

from flask import Blueprint, g as flask_g

import config
from db import store
from errors import raise_err
from middleware import require_role
from response import ok
from services.audit import log_event
from services.calculations import weighted_goal_score
from services.serializers import goal_view

from . import _helpers as H

bp = Blueprint("goals", __name__)


def _recompute_parent(rc):
    goals = [g for g in store.goals.values() if g["review_case_id"] == rc["id"]]
    rc["weighted_goal_score"] = weighted_goal_score(goals)
    H.bump(rc)


@bp.route("/cycles/<cycle_id>/review-cases/<review_case_id>/goals", methods=["POST"])
@require_role("Manager")
def create_goal(cycle_id, review_case_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        H.require_cycle_open(cycle)
        if rc["status"] not in ("DRAFT", "RETURNED"):
            raise_err("ERR_INVALID_STATE", f"ReviewCase is in {rc['status']}, not DRAFT/RETURNED.")
        body = H.get_body()
        title = H.require_str(H.require_field(body, "title"), "title", 1, 500)
        weight = H.require_int(H.require_field(body, "weight"), "weight", 1, 100)
        self_score = body.get("self_score")
        if self_score is not None:
            self_score = H.require_int(self_score, "self_score", 1, 5)
        manager_score = body.get("manager_score")
        if manager_score is not None:
            manager_score = H.require_int(manager_score, "manager_score", 1, 5)

        goal = H.new_entity({
            "review_case_id": rc["id"],
            "title": title,
            "weight": weight,
            "self_score": self_score,
            "manager_score": manager_score,
        })
        store.goals[goal["id"]] = goal
        _recompute_parent(rc)
        log_event("Goal", goal["id"], "goal.create", payload=body)
        return ok(goal_view(goal), status=201)


@bp.route("/cycles/<cycle_id>/review-cases/<review_case_id>/goals/<goal_id>", methods=["PATCH"])
@require_role("Manager", "Reviewer")
def patch_goal(cycle_id, review_case_id, goal_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        goal = H.get_goal_or_404(rc["id"], goal_id)
        H.require_cycle_open(cycle)
        if rc["status"] not in ("DRAFT", "RETURNED"):
            raise_err("ERR_INVALID_STATE", f"ReviewCase is in {rc['status']}, not DRAFT/RETURNED.")

        body = H.get_body()
        supplied_version = body.get("version")

        role = flask_g.user_role
        # Reviewer constraint: only the self_score of own subject case
        if role == "Reviewer":
            allowed_keys = {"self_score", "version"}
            unknown = set(body.keys()) - allowed_keys
            if unknown:
                raise_err("ERR_ROLE_FORBIDDEN", "Reviewers may only edit self_score.")
            if rc["subject_employee_id"] != flask_g.user_id:
                raise_err("ERR_ROLE_FORBIDDEN",
                          "Reviewer may only edit goals on their own subject case.")

        new_title = None
        if "title" in body and body["title"] is not None:
            new_title = H.require_str(body["title"], "title", 1, 500)

        new_weight = None
        if "weight" in body and body["weight"] is not None:
            new_weight = H.require_int(body["weight"], "weight", 1, 100)

        new_self = "__unset__"
        if "self_score" in body:
            v = body["self_score"]
            if v is None:
                new_self = None
            else:
                new_self = H.require_int(v, "self_score", 1, 5)

        new_manager = "__unset__"
        if "manager_score" in body:
            v = body["manager_score"]
            if v is None:
                new_manager = None
            else:
                new_manager = H.require_int(v, "manager_score", 1, 5)

        H.check_version(goal, supplied_version)

        recompute = False
        if new_title is not None:
            goal["title"] = new_title
        if new_weight is not None:
            if int(goal.get("weight", 0)) != new_weight:
                recompute = True  # weight affects score
            goal["weight"] = new_weight
        if new_self != "__unset__":
            goal["self_score"] = new_self
        if new_manager != "__unset__":
            if goal.get("manager_score") != new_manager:
                recompute = True
            goal["manager_score"] = new_manager

        # Only bump goal version if something changed
        H.bump(goal)

        if recompute:
            _recompute_parent(rc)
        else:
            H.bump(rc)  # PATCH on child still touches parent timestamp/version

        log_event("Goal", goal["id"], "goal.patch", payload=body)
        return ok(goal_view(goal))


@bp.route("/cycles/<cycle_id>/review-cases/<review_case_id>/goals/<goal_id>", methods=["DELETE"])
@require_role("Manager")
def delete_goal(cycle_id, review_case_id, goal_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        goal = H.get_goal_or_404(rc["id"], goal_id)
        H.require_cycle_open(cycle)
        if rc["status"] not in ("DRAFT", "RETURNED"):
            raise_err("ERR_INVALID_STATE", f"ReviewCase is in {rc['status']}, not DRAFT/RETURNED.")
        del store.goals[goal_id]
        _recompute_parent(rc)
        log_event("Goal", goal_id, "goal.delete", payload={})
        # 204 No Content per scaffold
        from flask import make_response
        resp = make_response("", 204)
        return resp
