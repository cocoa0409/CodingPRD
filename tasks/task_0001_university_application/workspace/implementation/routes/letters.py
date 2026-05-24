"""Recommendation letter routes."""

from flask import Blueprint, request

import db
import errors
import response as resp
import util
from middleware import require_auth
from routes._helpers import get_json_body, require_field
from services.serializers import serialize_letter


bp = Blueprint("letters", __name__)


RECOMMENDER_CAPACITY = 5


# --------------------------------------------------------------------------- #
# POST /recommendation-letters  (Applicant)
# --------------------------------------------------------------------------- #

@bp.route("/recommendation-letters", methods=["POST"])
@require_auth(["Applicant"])
def create_letter():
    body = get_json_body()
    application_id = require_field(body, "application_id", kind="string")
    recommender_id = require_field(body, "recommender_id", kind="string")

    # FK resolution
    application = db.applications.get(application_id)
    if application is None:
        errors.raise_error(errors.ERR_FK_NOT_FOUND, "Application not found.")
    recommender = db.recommenders.get(recommender_id)
    if recommender is None:
        errors.raise_error(errors.ERR_FK_NOT_FOUND, "Recommender not found.")

    user_id = request.headers.get("X-User-ID")
    if application["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only request letters for their own applications.")

    # Uniqueness: (application_id, recommender_id)
    for existing in db.recommendation_letters.values():
        if existing["application_id"] == application_id and existing["recommender_id"] == recommender_id:
            errors.raise_error(errors.ERR_DUPLICATE_RESOURCE,
                               "A letter already exists for this application and recommender.")

    row = {
        "application_id": application_id,
        "recommender_id": recommender_id,
        "status": "REQUESTED",
        "body": None,
        "submitted_at": None,
    }
    util.stamp_create(row)
    db.recommendation_letters[row["id"]] = row
    return resp.success_object(serialize_letter(row), http_status=201)


# --------------------------------------------------------------------------- #
# POST /recommendation-letters/{id}/start  (Recommender)
# --------------------------------------------------------------------------- #

@bp.route("/recommendation-letters/<letter_id>/start", methods=["POST"])
@require_auth(["Recommender"])
def start_letter(letter_id):
    row = db.recommendation_letters.get(letter_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Letter not found.")

    user_id = request.headers.get("X-User-ID")
    if row["recommender_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Recommenders can only act on their own letters.")

    if row["status"] != "REQUESTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Letter is not in REQUESTED state.")

    recommender = db.recommenders.get(row["recommender_id"])
    if recommender is None or recommender["invite_status"] != "ACCEPTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Recommender has not accepted the invitation.")

    application = db.applications.get(row["application_id"])
    if application is None or application["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Owning application is not in DRAFT state.")

    # Priority 20: recommender capacity
    in_progress = sum(
        1 for l in db.recommendation_letters.values()
        if l["recommender_id"] == row["recommender_id"] and l["status"] == "IN_PROGRESS"
    )
    if in_progress + 1 > RECOMMENDER_CAPACITY:
        errors.raise_error(errors.ERR_RECOMMENDER_OVER_CAPACITY,
                           "Recommender already has 5 letters in IN_PROGRESS status.")

    row["status"] = "IN_PROGRESS"
    util.stamp_update(row)
    return resp.success_object(serialize_letter(row))


# --------------------------------------------------------------------------- #
# POST /recommendation-letters/{id}/submit  (Recommender)
# --------------------------------------------------------------------------- #

@bp.route("/recommendation-letters/<letter_id>/submit", methods=["POST"])
@require_auth(["Recommender"])
def submit_letter(letter_id):
    row = db.recommendation_letters.get(letter_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Letter not found.")

    user_id = request.headers.get("X-User-ID")
    if row["recommender_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Recommenders can only act on their own letters.")

    body = get_json_body()
    letter_body = require_field(body, "body", kind="string")
    if len(letter_body) < 200:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Letter body must be at least 200 characters.")

    if row["status"] != "IN_PROGRESS":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Letter is not in IN_PROGRESS state.")

    application = db.applications.get(row["application_id"])
    if application is None or application["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Owning application is not in DRAFT state.")

    row["status"] = "SUBMITTED"
    row["body"] = letter_body
    row["submitted_at"] = util.server_clock_dt()
    util.stamp_update(row)
    return resp.success_object(serialize_letter(row))


# --------------------------------------------------------------------------- #
# POST /recommendation-letters/{id}/waive  (Applicant)
# --------------------------------------------------------------------------- #

@bp.route("/recommendation-letters/<letter_id>/waive", methods=["POST"])
@require_auth(["Applicant"])
def waive_letter(letter_id):
    row = db.recommendation_letters.get(letter_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "Letter not found.")

    application = db.applications.get(row["application_id"])
    user_id = request.headers.get("X-User-ID")
    if application is None or application["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only waive letters on their own applications.")

    if row["status"] not in ("REQUESTED", "IN_PROGRESS"):
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Letter is not in a waivable state.")
    if application["plan"] == "EARLY_DECISION":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Letters cannot be waived for Early Decision applications.")

    row["status"] = "WAIVED"
    util.stamp_update(row)
    return resp.success_object(serialize_letter(row))
