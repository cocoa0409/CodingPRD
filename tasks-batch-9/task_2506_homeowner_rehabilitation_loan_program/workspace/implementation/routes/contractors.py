"""Approved contractor list and the standing cascade (PRD 3.5, 3.9)."""

from flask import Blueprint

import db
import errors
import middleware
import paging
import response
import validation
from errors import fail
from routes import API_PREFIX
from services import domain, serializers
from services import constants as C

bp = Blueprint("contractors", __name__)

READ_ROLES = middleware.STAFF_ROLES
READ_ONE_ROLES = middleware.STAFF_ROLES + (middleware.CONTRACTOR,)

ALLOWED_STANDING_TRANSITIONS = (
    ("APPROVED", "PROBATION"),
    ("PROBATION", "APPROVED"),
    ("APPROVED", "SUSPENDED"),
    ("PROBATION", "SUSPENDED"),
    ("SUSPENDED", "APPROVED"),
    ("SUSPENDED", "REMOVED"),
)


@bp.post(API_PREFIX + "/contractors")
@middleware.roles(middleware.PROGRAM_MANAGER)
def create_contractor():
    body = validation.json_body()
    legal_name = validation.field_str(body, "legal_name")
    license_number = validation.field_str(body, "license_number")
    insurance_expires_on = validation.field_datetime(body, "insurance_expires_on")
    lead_safe = validation.field_bool(body, "lead_safe_certified", default=False)
    historic_qualified = validation.field_bool(body, "historic_qualified", default=False)

    for existing in db.contractors.values():
        if existing["license_number"] == license_number:
            fail(errors.ERR_INVALID_REQUEST, "Field 'license_number' must be unique.")

    row = db.new_row()
    row.update(
        {
            "legal_name": legal_name,
            "license_number": license_number,
            "insurance_expires_on": insurance_expires_on,
            "lead_safe_certified": lead_safe,
            "historic_qualified": historic_qualified,
            "approved_list_status": "APPROVED",
            "sanction_count": 0,
            "on_time_completion_count": 0,
        }
    )
    db.contractors[row["id"]] = row
    return response.object_response(serializers.contractor(row), 201)


@bp.post(API_PREFIX + "/contractors/<contractor_id>/status")
@middleware.roles(middleware.PROGRAM_MANAGER)
def change_status(contractor_id):
    row = validation.path_row(db.contractors, contractor_id, errors.ERR_CONTRACTOR_NOT_FOUND)
    body = validation.json_body()
    target = validation.field_enum(body, "approved_list_status", C.APPROVED_LIST_STATUSES)
    validation.field_str(body, "reason", required=False, default=None)

    current = row["approved_list_status"]
    if (current, target) not in ALLOWED_STANDING_TRANSITIONS:
        fail(
            errors.ERR_INVALID_STATE,
            "The approved-list transition %s -> %s is not defined." % (current, target),
        )
    if current == "PROBATION" and target == "APPROVED":
        if domain.performance_score(row) < C.PROBATION_SCORE_THRESHOLD:
            fail(
                errors.ERR_INVALID_STATE,
                "Restoration from probation requires a performance score of at least 50.",
            )

    row["approved_list_status"] = target
    db.touch(row)

    if target in ("SUSPENDED", "REMOVED"):
        domain.withdraw_live_bids(row)
    elif current == "SUSPENDED" and target == "APPROVED":
        domain.restore_withdrawn_bids(row)

    return response.object_response(serializers.contractor(row))


@bp.get(API_PREFIX + "/contractors/<contractor_id>")
@middleware.roles(*READ_ONE_ROLES)
def read_contractor(contractor_id):
    row = validation.path_row(db.contractors, contractor_id, errors.ERR_CONTRACTOR_NOT_FOUND)
    return response.object_response(serializers.contractor(row))


@bp.get(API_PREFIX + "/contractors")
@middleware.roles(*READ_ROLES)
def list_contractors():
    status = validation.filter_enum("approved_list_status", C.APPROVED_LIST_STATUSES)
    lead_safe = validation.filter_bool("lead_safe_certified")
    rows = []
    for row in db.contractors.values():
        if status is not None and row["approved_list_status"] != status:
            continue
        if lead_safe is not None and row["lead_safe_certified"] != lead_safe:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.contractor)
