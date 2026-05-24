"""Essay submission routes."""

from flask import Blueprint, request

import db
import errors
import response as resp
import util
from middleware import require_auth
from routes._helpers import get_json_body, require_field
from services.serializers import serialize_essay


bp = Blueprint("essays", __name__)


def _count_words(body: str) -> int:
    return len(body.split())  # whitespace-separated tokens per scaffold §1.1


# --------------------------------------------------------------------------- #
# POST /essay-submissions  (Applicant)
# --------------------------------------------------------------------------- #

@bp.route("/essay-submissions", methods=["POST"])
@require_auth(["Applicant"])
def create_essay():
    body = get_json_body()
    application_id = require_field(body, "application_id", kind="string")
    prompt_code = require_field(body, "prompt_code", kind="string")
    essay_body = require_field(body, "body", kind="string")

    # FK resolution
    application = db.applications.get(application_id)
    if application is None:
        errors.raise_error(errors.ERR_FK_NOT_FOUND, "Application not found.")

    # Ownership
    user_id = request.headers.get("X-User-ID")
    if application["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only create essays for their own applications.")

    # Uniqueness: one essay per application
    for existing in db.essay_submissions.values():
        if existing["application_id"] == application_id:
            errors.raise_error(errors.ERR_DUPLICATE_RESOURCE,
                               "An essay already exists for this application.")

    word_count = _count_words(essay_body)
    if not (1 <= word_count <= 650):
        errors.raise_error(errors.ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE,
                           "Essay word_count must be in 1..650 inclusive.")

    row = {
        "application_id": application_id,
        "prompt_code": prompt_code,
        "body": essay_body,
        "word_count": word_count,
        "locked": False,
    }
    util.stamp_create(row)
    db.essay_submissions[row["id"]] = row
    return resp.success_object(serialize_essay(row), http_status=201)


# --------------------------------------------------------------------------- #
# PATCH /essay-submissions/{id}  (Applicant)
# --------------------------------------------------------------------------- #

@bp.route("/essay-submissions/<essay_id>", methods=["PATCH"])
@require_auth(["Applicant"])
def patch_essay(essay_id):
    row = db.essay_submissions.get(essay_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Essay not found.")

    # Ownership via application
    application = db.applications.get(row["application_id"])
    user_id = request.headers.get("X-User-ID")
    if application is None or application["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only edit essays for their own applications.")

    # State: only while locked == false
    if row["locked"]:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Essay is locked; the application has already been submitted.")

    body = get_json_body()
    if "prompt_code" in body:
        if not isinstance(body["prompt_code"], str):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'prompt_code' must be a string.")
        row["prompt_code"] = body["prompt_code"]
    if "body" in body:
        if not isinstance(body["body"], str):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Field 'body' must be a string.")
        row["body"] = body["body"]
        row["word_count"] = _count_words(body["body"])
        if not (1 <= row["word_count"] <= 650):
            errors.raise_error(errors.ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE,
                               "Essay word_count must be in 1..650 inclusive.")

    util.stamp_update(row)
    return resp.success_object(serialize_essay(row))
