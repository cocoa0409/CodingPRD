"""Recommender routes."""

from flask import Blueprint, request

import db
import errors
import response as resp
import util
from middleware import require_auth
from routes._helpers import get_json_body, require_field
from services import applicants as applicants_service
from services.serializers import serialize_recommender


bp = Blueprint("recommenders", __name__)


VALID_RELATIONSHIPS = frozenset({"TEACHER", "COUNSELOR", "OTHER"})


# --------------------------------------------------------------------------- #
# POST /recommenders (Applicant)
# --------------------------------------------------------------------------- #

@bp.route("/recommenders", methods=["POST"])
@require_auth(["Applicant"])
def create_recommender():
    body = get_json_body()
    applicant_id = require_field(body, "applicant_id", kind="string")
    email = require_field(body, "email", kind="string")
    full_name = require_field(body, "full_name", kind="string")
    relationship = require_field(body, "relationship", kind="string")

    if relationship not in VALID_RELATIONSHIPS:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'relationship' must be one of TEACHER/COUNSELOR/OTHER.")
    if not email.strip() or not full_name.strip():
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Fields 'email' and 'full_name' must not be empty.")

    # FK resolution
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        errors.raise_error(errors.ERR_FK_NOT_FOUND,
                           "Applicant referenced by 'applicant_id' does not exist.")

    # Ownership
    user_id = request.headers.get("X-User-ID")
    if user_id != applicant_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only invite recommenders for themselves.")

    email_normalized = email.strip().lower()
    # Uniqueness: (applicant_id, email) is unique
    for existing in db.recommenders.values():
        if existing["applicant_id"] == applicant_id and existing["email"] == email_normalized:
            errors.raise_error(errors.ERR_DUPLICATE_RESOURCE,
                               "This applicant already invited this email.")

    row = {
        "applicant_id": applicant_id,
        "email": email_normalized,
        "full_name": full_name,
        "relationship": relationship,
        "invite_status": "INVITED",
    }
    util.stamp_create(row)
    db.recommenders[row["id"]] = row
    # Re-evaluate applicant readiness now that they have at least one recommender
    applicants_service.recompute_profile_status(applicant_id)
    return resp.success_object(serialize_recommender(row), http_status=201)


# --------------------------------------------------------------------------- #
# GET /recommenders/{id}
# --------------------------------------------------------------------------- #

@bp.route("/recommenders/<rec_id>", methods=["GET"])
@require_auth(["Applicant", "Recommender", "PlatformAdmin"])
def get_recommender(rec_id):
    row = db.recommenders.get(rec_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND,
                           "Recommender not found.")
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role == "Applicant" and row["applicant_id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Applicants can only read their own recommender rows.")
    if role == "Recommender" and row["id"] != user_id:
        errors.raise_error(errors.ERR_NOT_RESOURCE_OWNER,
                           "Recommenders can only read their own record.")
    return resp.success_object(serialize_recommender(row))


# --------------------------------------------------------------------------- #
# POST /recommenders/{id}/accept (public)
# --------------------------------------------------------------------------- #

@bp.route("/recommenders/<rec_id>/accept", methods=["POST"])
@require_auth(["Anonymous"])
def accept_recommender(rec_id):
    row = db.recommenders.get(rec_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND,
                           "Recommender not found.")
    if row["invite_status"] != "INVITED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Recommender invitation is not in INVITED state.")
    row["invite_status"] = "ACCEPTED"
    util.stamp_update(row)
    return resp.success_object(serialize_recommender(row))


# --------------------------------------------------------------------------- #
# POST /recommenders/{id}/decline (public)
# --------------------------------------------------------------------------- #

@bp.route("/recommenders/<rec_id>/decline", methods=["POST"])
@require_auth(["Anonymous"])
def decline_recommender(rec_id):
    row = db.recommenders.get(rec_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND,
                           "Recommender not found.")
    if row["invite_status"] != "INVITED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Recommender invitation is not in INVITED state.")
    row["invite_status"] = "DECLINED"
    util.stamp_update(row)

    # Cascade: delete REQUESTED letters pointing at this recommender
    affected_applicants = set()
    to_delete = []
    for letter_id, letter in db.recommendation_letters.items():
        if letter["recommender_id"] == rec_id and letter["status"] == "REQUESTED":
            to_delete.append(letter_id)
            app = db.applications.get(letter["application_id"])
            if app is not None:
                affected_applicants.add(app["applicant_id"])
    for lid in to_delete:
        del db.recommendation_letters[lid]

    # Per PRD §3.1: "The profile may also flip back from READY to DRAFT if
    # a recommender declines their invitation and the deletion of the
    # resulting requested letters leaves the applicant with no remaining
    # recommender rows". The applicant who owns this declining recommender
    # is always a candidate for re-evaluation, even when the cascade did
    # not delete any letters (e.g. no REQUESTED letters yet). The
    # readiness predicate in applicants.recompute_profile_status() already
    # excludes DECLINED recommender rows from the "remaining recommenders"
    # count, so the flip happens correctly when this is the last
    # non-declined row.
    affected_applicants.add(row["applicant_id"])
    for aid in affected_applicants:
        applicants_service.recompute_profile_status(aid)

    return resp.success_object(serialize_recommender(row))
