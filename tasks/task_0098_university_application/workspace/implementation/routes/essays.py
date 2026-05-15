"""Essay routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.errors import raise_error
from core.response import success_object
from core.store import store
from services.engine import (
    check_version,
    get_application,
    get_essay,
    recompute_essay_score,
)
from services.serializers import application_out, essay_out

bp = Blueprint("essays", __name__)


def _validate_body(body_text):
    if not isinstance(body_text, str):
        raise_error("ERR_ESSAY_LENGTH", "body must be a string.")
    if len(body_text) < 250 or len(body_text) > 6500:
        raise_error("ERR_ESSAY_LENGTH")


@bp.post("/applications/<application_id>/essays")
@require_roles("Applicant")
def create_essay(application_id: str):
    app = get_application(application_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    if app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")
    prompt = body.get("prompt_code")
    if not isinstance(prompt, str) or not prompt:
        raise_error("ERR_VALIDATION", "prompt_code is required.")
    text = body.get("body")
    _validate_body(text)
    # Create essay record (no version/updated_at per spec — id + created_at only).
    stamp = store.stamp_create(with_version=False)
    rec = {
        "id": stamp["id"],
        "created_at": stamp["created_at"],
        "application_id": app["id"],
        "prompt_code": prompt,
        "body": text,
        "word_count": 0,
        "customization_score": None,
    }
    store.essays[rec["id"]] = rec
    recompute_essay_score(rec)
    # Link onto application
    app["essay_id"] = rec["id"]
    store.bump(app)
    return success_object(essay_out(rec), 201)


@bp.patch("/essays/<essay_id>")
@require_roles("Applicant")
def patch_essay(essay_id: str):
    essay = get_essay(essay_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    app = store.applications.get(essay["application_id"])
    if app is None or app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")
    # Essays don't carry a version field — but accept and ignore it if provided per spec note.
    # (Spec says only id + created_at present on essays; version OCC doesn't apply here.)
    if "body" in body and body["body"] is not None:
        _validate_body(body["body"])
        essay["body"] = body["body"]
    if "prompt_code" in body and body["prompt_code"] is not None:
        if not isinstance(body["prompt_code"], str) or not body["prompt_code"]:
            raise_error("ERR_VALIDATION", "prompt_code must be a non-empty string.")
        essay["prompt_code"] = body["prompt_code"]
    recompute_essay_score(essay)
    return success_object(essay_out(essay), 200)


@bp.get("/essays/<essay_id>")
@require_roles("Applicant", "AdmissionsOfficer", "PlatformAdmin")
def read_essay(essay_id: str):
    essay = get_essay(essay_id)
    return success_object(essay_out(essay), 200)
