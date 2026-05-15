"""Recommendation routes."""
from __future__ import annotations

from flask import Blueprint, g, request

from core.auth import require_roles
from core.clock import clock
from core.errors import raise_error
from core.response import success_object
from core.store import store
from services.calculations import whitespace_tokens
from services.engine import (
    auto_expire_recommendations,
    get_application,
    get_recommendation,
)
from services.serializers import recommendation_out
from services.time_utils import add_days, parse_iso

bp = Blueprint("recommendations", __name__)


@bp.post("/applications/<application_id>/recommendations")
@require_roles("Applicant")
def create_recommendation(application_id: str):
    app = get_application(application_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    email = body.get("recommender_email")
    if not isinstance(email, str) or not email:
        raise_error("ERR_VALIDATION", "recommender_email is required.")
    rec = store.stamp_create()
    rec.update(
        {
            "application_id": app["id"],
            "recommender_email": email,
            "status": "REQUESTED",
            "invitation_expires_at": add_days(rec["created_at"], 21),
            "letter_body": None,
            "letter_word_count": None,
        }
    )
    store.recommendations[rec["id"]] = rec
    return success_object(recommendation_out(rec), 201)


@bp.get("/recommendations/<rec_id>")
@require_roles("Applicant", "Recommender", "AdmissionsOfficer", "PlatformAdmin")
def read_recommendation(rec_id: str):
    auto_expire_recommendations()
    rec = get_recommendation(rec_id)
    # Recommender scope: X-User-ID must equal recommender_email.
    if g.user_role == "Recommender" and g.user_id != rec["recommender_email"]:
        raise_error("ERR_FORBIDDEN")
    return success_object(recommendation_out(rec), 200)


def _recommender_match(rec: dict) -> None:
    if g.user_id != rec["recommender_email"]:
        raise_error("ERR_FORBIDDEN")


@bp.post("/recommendations/<rec_id>/accept")
@require_roles("Recommender")
def accept_recommendation(rec_id: str):
    rec = get_recommendation(rec_id)
    _recommender_match(rec)
    auto_expire_recommendations()
    if rec["status"] != "REQUESTED":
        raise_error("ERR_INVALID_STATE")
    if parse_iso(clock.iso()) > parse_iso(rec["invitation_expires_at"]):
        raise_error("ERR_INVALID_STATE")
    app = store.applications.get(rec["application_id"])
    if app is None or app["status"] not in {"DRAFT", "SUBMITTED"}:
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "ACCEPTED"
    store.bump(rec)
    return success_object(recommendation_out(rec), 200)


@bp.post("/recommendations/<rec_id>/decline")
@require_roles("Recommender")
def decline_recommendation(rec_id: str):
    rec = get_recommendation(rec_id)
    _recommender_match(rec)
    auto_expire_recommendations()
    if rec["status"] != "REQUESTED":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "DECLINED"
    store.bump(rec)
    return success_object(recommendation_out(rec), 200)


@bp.post("/recommendations/<rec_id>/reassign")
@require_roles("Applicant")
def reassign_recommendation(rec_id: str):
    rec = get_recommendation(rec_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    new_email = body.get("recommender_email")
    if not isinstance(new_email, str) or not new_email:
        raise_error("ERR_VALIDATION", "recommender_email is required.")
    if rec["status"] != "DECLINED":
        raise_error("ERR_INVALID_STATE")
    app = store.applications.get(rec["application_id"])
    if app is None or app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "REQUESTED"
    rec["recommender_email"] = new_email
    rec["invitation_expires_at"] = add_days(clock.iso(), 21)
    store.bump(rec)
    return success_object(recommendation_out(rec), 200)


@bp.post("/recommendations/<rec_id>/submit-letter")
@require_roles("Recommender")
def submit_letter(rec_id: str):
    rec = get_recommendation(rec_id)
    _recommender_match(rec)
    auto_expire_recommendations()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    letter = body.get("letter_body")
    if not isinstance(letter, str) or not letter:
        raise_error("ERR_VALIDATION", "letter_body is required.")
    if rec["status"] != "ACCEPTED":
        raise_error("ERR_INVALID_STATE")
    app = store.applications.get(rec["application_id"])
    if app is None or app["status"] not in {"DRAFT", "SUBMITTED", "UNDER_REVIEW"}:
        raise_error("ERR_INVALID_STATE")

    word_count = len(whitespace_tokens(letter))
    rec["letter_body"] = letter
    rec["letter_word_count"] = word_count
    rec["status"] = "SUBMITTED"
    store.bump(rec)
    if word_count < 200:
        raise_error("ERR_WEAK_LETTER")
    return success_object(recommendation_out(rec), 200)
