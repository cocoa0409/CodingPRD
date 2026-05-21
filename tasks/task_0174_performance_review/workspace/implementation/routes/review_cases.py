"""ReviewCase endpoints + state transitions (PRD §3.3)."""

from flask import Blueprint, request

import config
from db import store
from errors import raise_err
from middleware import require_role
from response import ok, paginate
from services.audit import log_event
from services.calculations import weighted_goal_score
from services.serializers import review_case_view

from . import _helpers as H

bp = Blueprint("review_cases", __name__)


def _recompute_score(rc):
    goals = [g for g in store.goals.values() if g["review_case_id"] == rc["id"]]
    rc["weighted_goal_score"] = weighted_goal_score(goals)


@bp.route("/cycles/<cycle_id>/review-cases", methods=["POST"])
@require_role("HRBP", "Manager")
def create_review_case(cycle_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        body = H.get_body()
        subject_id = H.require_str(
            H.require_field(body, "subject_employee_id"),
            "subject_employee_id",
        )

        H.require_cycle_open(cycle)

        subject = store.employees.get(subject_id)
        if not subject:
            raise_err("ERR_REFERENCE_NOT_FOUND",
                      f"subject_employee_id '{subject_id}' not found.")
        if subject["status"] not in config.LIVE_EMPLOYEE_STATUSES:
            raise_err("ERR_REFERENCE_NOT_FOUND",
                      "subject_employee_id must reference an ACTIVE or ON_PIP employee.")

        # Uniqueness per (cycle_id, subject_employee_id)
        for rc in store.review_cases.values():
            if rc["cycle_id"] == cycle_id and rc["subject_employee_id"] == subject_id:
                raise_err("ERR_INVALID_STATE",
                          "A ReviewCase already exists for this (cycle, subject).")

        rc = H.new_entity({
            "cycle_id": cycle_id,
            "subject_employee_id": subject_id,
            "manager_employee_id": subject.get("manager_employee_id"),
            "status": "DRAFT",
            "manager_rating": None,
            "final_rating": None,
            "weighted_goal_score": 0,
            "peer_feedback_count": 0,
            "revision_count": 0,
        })
        store.review_cases[rc["id"]] = rc
        log_event("ReviewCase", rc["id"], "review_case.create", payload=body)
        return ok(review_case_view(rc), status=201)


@bp.route("/cycles/<cycle_id>/review-cases", methods=["GET"])
@require_role("HRBP", "Manager", "Approver")
def list_review_cases(cycle_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        status = request.args.get("status")
        subject_id = request.args.get("subject_employee_id")
        limit, offset = H.pagination_params()
        items = [rc for rc in store.review_cases.values() if rc["cycle_id"] == cycle_id]
        if status is not None:
            if status not in config.REVIEW_CASE_STATUSES:
                raise_err("ERR_VALIDATION", "Invalid status filter.")
            items = [rc for rc in items if rc["status"] == status]
        if subject_id is not None:
            items = [rc for rc in items if rc["subject_employee_id"] == subject_id]
        items.sort(key=lambda rc: rc["created_at"])
        sliced, page_meta = paginate(items, limit, offset)
        return ok([review_case_view(rc) for rc in sliced], pagination=page_meta)


@bp.route("/cycles/<cycle_id>/review-cases/<review_case_id>", methods=["GET"])
@require_role("HRBP", "Manager", "Approver", "Reviewer")
def read_review_case(cycle_id, review_case_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        return ok(review_case_view(rc))


@bp.route("/cycles/<cycle_id>/review-cases/<review_case_id>", methods=["PATCH"])
@require_role("Manager")
def patch_review_case(cycle_id, review_case_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        body = H.get_body()
        supplied_version = body.get("version")
        H.require_cycle_open(cycle)

        new_rating = None
        if "manager_rating" in body and body["manager_rating"] is not None:
            new_rating = H.require_enum(body["manager_rating"], "manager_rating", config.RATING_SET)

        H.check_version(rc, supplied_version)

        if new_rating is not None:
            rc["manager_rating"] = new_rating
            H.bump(rc)
        log_event("ReviewCase", rc["id"], "review_case.patch", payload=body)
        return ok(review_case_view(rc))


@bp.route("/cycles/<cycle_id>/review-cases/<review_case_id>/submit", methods=["POST"])
@require_role("Manager")
def submit_review_case(cycle_id, review_case_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        H.require_cycle_open(cycle)
        if rc["status"] != "DRAFT":
            raise_err("ERR_INVALID_STATE", f"ReviewCase is in {rc['status']}, not DRAFT.")

        if not rc.get("manager_rating"):
            raise_err("ERR_INVALID_STATE", "manager_rating is required to submit.")

        goals = [g for g in store.goals.values() if g["review_case_id"] == rc["id"]]
        # Goal weight closure (priority 80): sum == 100
        weight_sum = sum(int(g["weight"]) for g in goals)
        if weight_sum != 100:
            raise_err(
                "ERR_GOAL_WEIGHTS_INVALID",
                "Sum of goal weights must equal 100 at submit.",
            )
        # Every goal must have self_score and manager_score in [1,5]
        for g in goals:
            if g.get("self_score") is None or g.get("manager_score") is None:
                raise_err(
                    "ERR_GOAL_WEIGHTS_INVALID",
                    "Every goal must have self_score and manager_score set.",
                )

        # Peer feedback floor (priority 81)
        if int(rc.get("peer_feedback_count", 0)) < 2:
            raise_err("ERR_PEER_FEEDBACK_INSUFFICIENT",
                      "At least two SUBMITTED feedback requests are required.")

        _recompute_score(rc)
        rc["status"] = "SUBMITTED"
        H.bump(rc)
        log_event("ReviewCase", rc["id"], "review_case.submit", payload={})
        return ok(review_case_view(rc))


@bp.route("/cycles/<cycle_id>/review-cases/<review_case_id>/return", methods=["POST"])
@require_role("HRBP")
def return_review_case(cycle_id, review_case_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        H.require_cycle_open(cycle)
        if rc["status"] != "SUBMITTED":
            raise_err("ERR_INVALID_STATE", f"ReviewCase is in {rc['status']}, not SUBMITTED.")
        # Revision cap (priority 82): revision_count < 3 at return
        if int(rc.get("revision_count", 0)) >= 3:
            raise_err("ERR_REVISION_LIMIT", "ReviewCase has reached the revision cap of 3.")

        rc["revision_count"] = int(rc.get("revision_count", 0)) + 1
        rc["status"] = "RETURNED"
        H.bump(rc)
        log_event("ReviewCase", rc["id"], "review_case.return", payload={})
        return ok(review_case_view(rc))


@bp.route("/cycles/<cycle_id>/review-cases/<review_case_id>/reopen", methods=["POST"])
@require_role("Manager")
def reopen_review_case(cycle_id, review_case_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        H.require_cycle_open(cycle)
        if rc["status"] != "RETURNED":
            raise_err("ERR_INVALID_STATE", f"ReviewCase is in {rc['status']}, not RETURNED.")
        rc["status"] = "DRAFT"
        H.bump(rc)
        log_event("ReviewCase", rc["id"], "review_case.reopen", payload={})
        return ok(review_case_view(rc))
