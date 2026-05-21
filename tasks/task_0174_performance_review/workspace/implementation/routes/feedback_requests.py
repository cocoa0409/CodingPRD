"""FeedbackRequest endpoints (PRD §3.4) — append-only ledger semantics."""

from flask import Blueprint, g as flask_g

import config
from db import new_id, store, utcnow_iso
from errors import raise_err
from middleware import require_role
from response import ok
from services.audit import log_event
from services.serializers import feedback_view

from . import _helpers as H

bp = Blueprint("feedback_requests", __name__)


@bp.route(
    "/cycles/<cycle_id>/review-cases/<review_case_id>/feedback-requests",
    methods=["POST"],
)
@require_role("Manager", "HRBP")
def create_feedback(cycle_id, review_case_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        body = H.get_body()
        reviewer_id = H.require_str(
            H.require_field(body, "reviewer_employee_id"),
            "reviewer_employee_id",
        )
        relation = H.require_enum(
            H.require_field(body, "relation"), "relation", config.FEEDBACK_RELATIONS,
        )

        H.require_cycle_open(cycle)

        reviewer = store.employees.get(reviewer_id)
        if not reviewer:
            raise_err("ERR_REFERENCE_NOT_FOUND",
                      f"reviewer_employee_id '{reviewer_id}' not found.")

        if reviewer_id == rc["subject_employee_id"]:
            raise_err("ERR_SELF_FEEDBACK_FORBIDDEN",
                      "Self-feedback is forbidden.")

        fr = {
            "id": new_id(),
            "created_at": utcnow_iso(),
            "review_case_id": rc["id"],
            "reviewer_employee_id": reviewer_id,
            "relation": relation,
            "status": "PENDING",
            "narrative": None,
            "submitted_at": None,
        }
        store.feedback_requests[fr["id"]] = fr
        log_event("FeedbackRequest", fr["id"], "feedback_request.create", payload=body)
        return ok(feedback_view(fr), status=201)


@bp.route(
    "/cycles/<cycle_id>/review-cases/<review_case_id>/feedback-requests/<feedback_request_id>/submit",
    methods=["POST"],
)
@require_role("Reviewer")
def submit_feedback(cycle_id, review_case_id, feedback_request_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        fr = H.get_feedback_or_404(rc["id"], feedback_request_id)
        body = H.get_body()
        narrative = H.require_str(
            H.require_field(body, "narrative"), "narrative",
        )

        if fr["status"] != "PENDING":
            raise_err("ERR_INVALID_STATE", f"FeedbackRequest is in {fr['status']}, not PENDING.")

        if flask_g.user_id != fr["reviewer_employee_id"]:
            raise_err("ERR_ROLE_FORBIDDEN",
                      "Only the designated reviewer may submit this feedback.")

        if rc["status"] not in ("DRAFT", "RETURNED"):
            raise_err("ERR_INVALID_STATE",
                      f"Parent ReviewCase is in {rc['status']}, not DRAFT/RETURNED.")

        if not (50 <= len(narrative) <= 5000):
            raise_err("ERR_VALIDATION",
                      "narrative length must be in [50, 5000].")

        fr["narrative"] = narrative
        fr["status"] = "SUBMITTED"
        fr["submitted_at"] = utcnow_iso()
        rc["peer_feedback_count"] = int(rc.get("peer_feedback_count", 0)) + 1
        H.bump(rc)
        log_event("FeedbackRequest", fr["id"], "feedback_request.submit", payload=body)
        return ok(feedback_view(fr))


@bp.route(
    "/cycles/<cycle_id>/review-cases/<review_case_id>/feedback-requests/<feedback_request_id>/decline",
    methods=["POST"],
)
@require_role("Reviewer")
def decline_feedback(cycle_id, review_case_id, feedback_request_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        rc = H.get_review_case_or_404(cycle_id, review_case_id)
        fr = H.get_feedback_or_404(rc["id"], feedback_request_id)
        if fr["status"] != "PENDING":
            raise_err("ERR_INVALID_STATE", f"FeedbackRequest is in {fr['status']}, not PENDING.")
        if flask_g.user_id != fr["reviewer_employee_id"]:
            raise_err("ERR_ROLE_FORBIDDEN",
                      "Only the designated reviewer may decline this feedback.")
        fr["status"] = "DECLINED"
        log_event("FeedbackRequest", fr["id"], "feedback_request.decline", payload={})
        return ok(feedback_view(fr))
