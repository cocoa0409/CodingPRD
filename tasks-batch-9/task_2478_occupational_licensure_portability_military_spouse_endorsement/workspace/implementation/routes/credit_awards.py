"""Military training credit awards and their compensating revocation (PRD §3.7)."""
from flask import Blueprint

import clock
import db
import response
import serializers
import validators as v
from constants import (
    ALL_ROLES, CREDIT_AWARD_STATUSES, REVIEWABLE_STATUSES, ROLE_ANALYST,
    ROLE_APPLICANT,
)
from errors import (
    ERR_APPLICATION_NOT_REVIEWABLE, ERR_CREDIT_AWARD_ALREADY_REVOKED,
    ERR_TRAINING_RECORD_ALREADY_CREDITED,
    ERR_TRAINING_RECORD_APPLICANT_MISMATCH, ERR_TRAINING_RECORD_UNVERIFIED, fail,
)
from middleware import authenticate
from services import calculations, lookups

bp = Blueprint("credit_awards", __name__)


def _require_reviewable(application):
    if application["status"] not in REVIEWABLE_STATUSES:
        fail(ERR_APPLICATION_NOT_REVIEWABLE,
             "The application is in status %s, which this operation does not "
             "permit." % application["status"])


@bp.post("/licensure/credit-awards")
def create_credit_award():
    authenticate([ROLE_ANALYST])
    body = v.body()
    application_id = v.f_string(body, "application_id")
    training_record_id = v.f_string(body, "training_record_id")

    application = lookups.application(application_id)
    record = lookups.training_record(training_record_id)

    _require_reviewable(application)

    if record["applicant_id"] != application["applicant_id"]:
        fail(ERR_TRAINING_RECORD_APPLICANT_MISMATCH,
             "The training record belongs to a different applicant.")
    if not record["verified"]:
        fail(ERR_TRAINING_RECORD_UNVERIFIED,
             "Only a verified training record may be credited.")
    for existing in db.credit_awards.values():
        if (existing["application_id"] == application["id"]
                and existing["training_record_id"] == record["id"]
                and existing["status"] == "AWARDED"):
            fail(ERR_TRAINING_RECORD_ALREADY_CREDITED,
                 "This training record has already been credited to this "
                 "application.")

    row = db.make_row({
        "application_id": application["id"],
        "training_record_id": record["id"],
        "awarded_hours": calculations.awarded_hours_for(record),
        "status": "AWARDED",
        "revoked_at": None,
    })
    db.credit_awards[row["id"]] = row

    profession = db.professions[application["profession_id"]]
    calculations.recompute_requirement_hours(application, profession)
    db.touch(application)
    return response.object_response(serializers.credit_award(row), 201)


@bp.get("/licensure/credit-awards/<award_id>")
def read_credit_award(award_id):
    user_id, role = authenticate(ALL_ROLES)
    row = lookups.credit_award(award_id)
    application = db.applications[row["application_id"]]
    lookups.require_applicant_ownership(role, user_id,
                                        application["applicant_id"])
    return response.object_response(serializers.credit_award(row))


@bp.get("/licensure/credit-awards")
def list_credit_awards():
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    application_id = response.query_string("application_id")
    training_record_id = response.query_string("training_record_id")
    status = response.query_enum("status", CREDIT_AWARD_STATUSES)
    rows = []
    for row in db.credit_awards.values():
        if application_id is not None and row["application_id"] != application_id:
            continue
        if (training_record_id is not None
                and row["training_record_id"] != training_record_id):
            continue
        if status is not None and row["status"] != status:
            continue
        if role == ROLE_APPLICANT:
            application = db.applications.get(row["application_id"])
            if application is None or application["applicant_id"] != user_id:
                continue
        rows.append(row)
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.credit_award)


@bp.post("/licensure/credit-awards/<award_id>/revoke")
def revoke_credit_award(award_id):
    authenticate([ROLE_ANALYST])
    row = lookups.credit_award(award_id)
    application = db.applications[row["application_id"]]
    _require_reviewable(application)

    if row["status"] != "AWARDED":
        fail(ERR_CREDIT_AWARD_ALREADY_REVOKED,
             "This credit award has already been revoked.")

    row["status"] = "REVOKED"
    row["revoked_at"] = clock.now()
    db.touch(row)

    profession = db.professions[application["profession_id"]]
    calculations.recompute_requirement_hours(application, profession)
    db.touch(application)
    return response.object_response(serializers.credit_award(row))
