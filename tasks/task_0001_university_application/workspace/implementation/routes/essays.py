"""Essay endpoints."""
from __future__ import annotations

import re
from flask import Blueprint, request, g

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
    ERR_FORBIDDEN_OWNER_MISMATCH, ERR_WORD_COUNT_MISMATCH,
)
from middleware import auth_required
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, get_body, require_fields, order_by_created_at,
)
from services import calculations
from services.common import new_common_fields, touch

bp = Blueprint("essays", __name__)

WORD_RE = re.compile(r"\S+")


def _word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def _check_word_count(declared: int, text: str):
    actual = _word_count(text)
    if abs(declared - actual) > 5:
        raise APIError(ERR_WORD_COUNT_MISMATCH, 422,
                       f"Declared word_count {declared} differs from server count {actual} by more than 5")


@bp.post("/essays")
def create_essay():
    auth_required({"Applicant"})()
    body = get_body()
    require_fields(body, ["application_id", "prompt_code", "word_count", "text"])
    app_id = body["application_id"]
    app = db.applications.get(app_id)
    if app is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    if g.user_id != app["applicant_id"]:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this application")
    prompt_code = body["prompt_code"]
    if not isinstance(prompt_code, str) or not prompt_code:
        raise APIError(ERR_INVALID_REQUEST, 400, "prompt_code must be non-empty string")
    # unique within application
    for e in db.essays.values():
        if e["application_id"] == app_id and e["prompt_code"] == prompt_code:
            raise APIError(ERR_INVALID_REQUEST, 400, "prompt_code must be unique within application")
    wc = body["word_count"]
    if not isinstance(wc, int) or isinstance(wc, bool) or wc < 1 or wc > 650:
        raise APIError(ERR_INVALID_REQUEST, 400, "word_count out of range")
    text = body["text"]
    if not isinstance(text, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "text must be string")
    _check_word_count(wc, text)
    completed = body.get("completed", False)
    if not isinstance(completed, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "completed must be boolean")

    common = new_common_fields()
    essay = {
        **common,
        "application_id": app_id,
        "prompt_code": prompt_code,
        "word_count": wc,
        "text": text,
        "completed": completed,
    }
    db.essays[essay["id"]] = essay
    # recompute if parent app in SUBMITTED / UNDER_REVIEW
    if app["status"] in {"SUBMITTED", "UNDER_REVIEW"}:
        calculations.recompute_application_composite(app)
    return ok_object(essay, http_status=201)


@bp.patch("/essays/<eid>")
def update_essay(eid):
    auth_required({"Applicant"})()
    essay = db.essays.get(eid)
    if essay is None:
        raise APIError(ERR_NOT_FOUND, 404, "Essay not found")
    app = db.applications.get(essay["application_id"])
    if g.user_id != app["applicant_id"]:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this essay")
    body = get_body()
    new_wc = essay["word_count"]
    new_text = essay["text"]
    new_completed = essay["completed"]
    if "word_count" in body:
        v = body["word_count"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 650:
            raise APIError(ERR_INVALID_REQUEST, 400, "word_count out of range")
        new_wc = v
    if "text" in body:
        if not isinstance(body["text"], str):
            raise APIError(ERR_INVALID_REQUEST, 400, "text must be string")
        new_text = body["text"]
    if "completed" in body:
        if not isinstance(body["completed"], bool):
            raise APIError(ERR_INVALID_REQUEST, 400, "completed must be boolean")
        new_completed = body["completed"]
    # word count check if either changed
    if "word_count" in body or "text" in body:
        _check_word_count(new_wc, new_text)
    essay["word_count"] = new_wc
    essay["text"] = new_text
    essay["completed"] = new_completed
    touch(essay)
    if app["status"] in {"SUBMITTED", "UNDER_REVIEW"}:
        calculations.recompute_application_composite(app)
    return ok_object(essay)


@bp.get("/essays/<eid>")
def read_essay(eid):
    auth_required({"Applicant", "AdmissionsOfficer", "PlatformAdmin"})()
    essay = db.essays.get(eid)
    if essay is None:
        raise APIError(ERR_NOT_FOUND, 404, "Essay not found")
    if g.user_role == "Applicant":
        app = db.applications.get(essay["application_id"])
        if app and g.user_id != app["applicant_id"]:
            raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this essay")
    return ok_object(essay)


@bp.get("/essays")
def list_essays():
    auth_required({"Applicant", "AdmissionsOfficer", "PlatformAdmin"})()
    application_id = request.args.get("application_id")
    limit, offset = parse_pagination()
    items = []
    for e in db.essays.values():
        if application_id and e["application_id"] != application_id:
            continue
        if g.user_role == "Applicant":
            app = db.applications.get(e["application_id"])
            if not app or app["applicant_id"] != g.user_id:
                continue
        items.append(e)
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(page, limit, offset, total)
