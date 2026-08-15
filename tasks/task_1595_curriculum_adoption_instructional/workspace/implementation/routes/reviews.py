"""TeacherReview withdraw endpoint (PRD §3.3)."""

from flask import Blueprint

import serializers
from db import bump, refresh, store
from errors import insufficient_permissions, invalid_state
from middleware import auth_context, get_or_404, require_roles
from response import success_object
from services.calculations import recompute_provisional

bp = Blueprint("reviews", __name__)


@bp.route("/reviews/<reviewId>/withdraw", methods=["POST"])
def withdraw_review(reviewId):
    user_id, role = auth_context()
    require_roles(role, ("Teacher",))
    review = get_or_404(store.reviews, reviewId, "TeacherReview")
    # Tier 2 user-level ownership: only the recorded teacher may withdraw.
    if user_id != review["teacher_user_id"]:
        raise insufficient_permissions(
            "only the review's owning teacher may withdraw it")
    if review["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED review may be withdrawn")
    pilot = store.pilots.get(review["pilot_id"])
    if pilot is None or pilot["status"] != "ACTIVE":
        raise invalid_state("the review's pilot must still be ACTIVE")
    review["status"] = "WITHDRAWN"
    bump(review)
    material = store.materials.get(pilot["material_id"])
    if material is not None:
        recompute_provisional(material)
        refresh(material)
    refresh(pilot)
    return success_object(serializers.review(review))
