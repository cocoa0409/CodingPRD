"""Pharmacist reviews — get/approve/reject/request-change/resume."""

from __future__ import annotations

from flask import Blueprint, g, request

from db import (
    append_audit_log,
    db,
    serialize,
    stamp_update,
)
from errors import err
from lookups import get_review
from middleware import current_actor, require_roles
from response import success_object
from services.cascades import evaluate_prescription_archive, refund_if_paid
from services.calculations import MAX_REVISIONS
from validate import occ_check, optional_field, require_field, require_json

bp = Blueprint("reviews", __name__)


def _require_acting_pharmacist_active(pid: str) -> dict:
    actor = db.pharmacists.get(g.user_id)
    if not actor or actor.get("platform_id") != pid:
        raise err("ERR_PHARMACIST_NOT_ACTIVE", "Acting pharmacist not on platform.")
    if actor.get("qualification_status") != "ACTIVE":
        raise err("ERR_PHARMACIST_NOT_ACTIVE", "Acting pharmacist must be ACTIVE.")
    return actor


def _require_assigned_to(review: dict):
    if review.get("assigned_pharmacist_id") != g.user_id:
        raise err("ERR_REVIEWER_MISMATCH", "Reviewer mismatch.")


@bp.get("/pharma-platforms/<pid>/orders/<order_id>/pharmacist-reviews/<review_id>")
@require_roles("PharmacistReReviewer", "PlatformAdmin")
def get_review_route(pid: str, order_id: str, review_id: str):
    _, _, review = get_review(pid, order_id, review_id)
    return success_object(serialize(review)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/pharmacist-reviews/<review_id>/approve")
@require_roles("PharmacistReReviewer")
def approve_review(pid: str, order_id: str, review_id: str):
    platform, order, review = get_review(pid, order_id, review_id)
    body = require_json(request.get_json(silent=True))
    occ_check(body, review)
    if review.get("status") != "IN_REVIEW":
        raise err("ERR_REVIEW_NOT_IN_REVIEW", "Review must be IN_REVIEW.")

    interaction = body.get("interaction_check_passed")
    dosage = body.get("dosage_rationality_passed")
    if not isinstance(interaction, bool) or not isinstance(dosage, bool):
        raise err(
            "ERR_INVALID_REQUEST",
            "interaction_check_passed and dosage_rationality_passed must be booleans.",
        )
    if not (interaction and dosage):
        raise err("ERR_REVIEW_CHECKS_FAILED", "Both checks must be true to approve.")

    _require_assigned_to(review)
    # Segregation of duties
    if order.get("prescription_id"):
        rx = db.prescriptions.get(order["prescription_id"])
        if rx and rx.get("reviewer_pharmacist_id") == g.user_id:
            raise err(
                "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                "Acting pharmacist cannot be the prescription reviewer.",
            )
    _require_acting_pharmacist_active(pid)

    review["interaction_check_passed"] = interaction
    review["dosage_rationality_passed"] = dosage
    review["decision_notes"] = optional_field(body, "decision_notes", kind=str, default=review.get("decision_notes"))
    review["status"] = "APPROVED"
    stamp_update(review, platform)

    # Cascade: order PHARMACIST_REVIEWING → APPROVED
    order["dispensing_status"] = "APPROVED"
    stamp_update(order, platform)

    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="PHARMACIST_REVIEW",
        subject_id=review["id"],
        action="PHARMACIST_REVIEW_APPROVED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"review_id": review["id"], "version": review["version"]},
    )
    return success_object(serialize(review)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/pharmacist-reviews/<review_id>/reject")
@require_roles("PharmacistReReviewer")
def reject_review(pid: str, order_id: str, review_id: str):
    platform, order, review = get_review(pid, order_id, review_id)
    body = require_json(request.get_json(silent=True))
    occ_check(body, review)
    if review.get("status") != "IN_REVIEW":
        raise err("ERR_REVIEW_NOT_IN_REVIEW", "Review must be IN_REVIEW.")
    notes = require_field(body, "decision_notes", kind=str)
    if len(notes) < 10:
        raise err("ERR_REVIEW_NOTES_TOO_SHORT", "decision_notes must be at least 10 characters.")
    _require_assigned_to(review)

    review["decision_notes"] = notes
    review["status"] = "REJECTED"
    stamp_update(review, platform)

    order["dispensing_status"] = "REJECTED"
    stamp_update(order, platform)
    refund_if_paid(platform, order)

    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="PHARMACIST_REVIEW",
        subject_id=review["id"],
        action="PHARMACIST_REVIEW_REJECTED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"review_id": review["id"], "version": review["version"]},
    )
    evaluate_prescription_archive(platform, order.get("prescription_id"))
    return success_object(serialize(review)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/pharmacist-reviews/<review_id>/request-change")
@require_roles("PharmacistReReviewer")
def request_change_review(pid: str, order_id: str, review_id: str):
    platform, order, review = get_review(pid, order_id, review_id)
    body = require_json(request.get_json(silent=True))
    occ_check(body, review)
    if review.get("status") != "IN_REVIEW":
        raise err("ERR_REVIEW_NOT_IN_REVIEW", "Review must be IN_REVIEW.")
    notes = require_field(body, "decision_notes", kind=str)
    if len(notes) < 10:
        raise err("ERR_REVIEW_NOTES_TOO_SHORT", "decision_notes must be at least 10 characters.")
    if int(review.get("revision_count") or 0) >= MAX_REVISIONS:
        raise err("ERR_REVIEW_MAX_REVISIONS", f"revision_count >= {MAX_REVISIONS}.")
    _require_assigned_to(review)

    review["decision_notes"] = notes
    review["status"] = "REQUEST_CHANGE"
    stamp_update(review, platform)

    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="PHARMACIST_REVIEW",
        subject_id=review["id"],
        action="PHARMACIST_REVIEW_REQUEST_CHANGE",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"review_id": review["id"], "version": review["version"]},
    )
    return success_object(serialize(review)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/pharmacist-reviews/<review_id>/resume")
@require_roles("PharmacistReReviewer")
def resume_review(pid: str, order_id: str, review_id: str):
    platform, order, review = get_review(pid, order_id, review_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, review)
    if review.get("status") != "REQUEST_CHANGE":
        raise err("ERR_REVIEW_NOT_IN_REQUEST_CHANGE", "Review must be REQUEST_CHANGE.")
    _require_assigned_to(review)

    review["status"] = "IN_REVIEW"
    review["revision_count"] = int(review.get("revision_count") or 0) + 1
    stamp_update(review, platform)
    return success_object(serialize(review)), 200
