"""Warranty complaints, the remedy window and contractor discipline (PRD 3.9)."""

from flask import Blueprint

import clock
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

bp = Blueprint("complaints", __name__)

READ_ROLES = middleware.STAFF_ROLES
READ_ONE_ROLES = middleware.STAFF_ROLES + (middleware.APPLICANT, middleware.CONTRACTOR)


@bp.post(API_PREFIX + "/complaints")
@middleware.roles(middleware.APPLICANT, middleware.REHAB_SPECIALIST)
def file_complaint():
    body = validation.json_body()
    contractor = validation.body_fk(
        body, "contractor_id", db.contractors, errors.ERR_CONTRACTOR_NOT_FOUND
    )
    validation.field_id(body, "contractor_id")
    application = validation.body_fk(
        body, "application_id", db.applications, errors.ERR_APPLICATION_NOT_FOUND
    )
    validation.field_id(body, "application_id")
    defect_category = validation.field_enum(body, "defect_category", C.DEFECT_CATEGORIES)
    description = validation.field_str(body, "description")

    warranty_expires_at = application["warranty_expires_at"]
    if warranty_expires_at is None or clock.now() > warranty_expires_at:
        fail(errors.ERR_WARRANTY_EXPIRED)

    snapshot = domain.contractor_snapshot(contractor)

    row = db.new_row()
    row.update(
        {
            "contractor_id": contractor["id"],
            "application_id": application["id"],
            "defect_category": defect_category,
            "description": description,
            "filed_at": clock.now(),
            "warranty_expires_at": warranty_expires_at,
            "remedy_deadline_at": None,
            "status": "FILED",
            "sanction_level": None,
            "resolved_at": None,
        }
    )
    db.complaints[row["id"]] = row

    domain.rescore_contractor(contractor, snapshot)

    return response.object_response(serializers.complaint(row), 201)


@bp.post(API_PREFIX + "/complaints/<complaint_id>/notify")
@middleware.roles(middleware.PROGRAM_MANAGER)
def notify_contractor(complaint_id):
    row = validation.path_row(db.complaints, complaint_id, errors.ERR_COMPLAINT_NOT_FOUND)
    if row["status"] != "FILED":
        fail(errors.ERR_INVALID_STATE, "Only a newly filed complaint may be notified.")

    row["status"] = "CONTRACTOR_NOTIFIED"
    row["remedy_deadline_at"] = clock.add_days(clock.now(), C.REMEDY_WINDOW_DAYS)
    db.touch(row)
    return response.object_response(serializers.complaint(row))


@bp.post(API_PREFIX + "/complaints/<complaint_id>/resolve")
@middleware.roles(middleware.PROGRAM_MANAGER)
def resolve_complaint(complaint_id):
    row = validation.path_row(db.complaints, complaint_id, errors.ERR_COMPLAINT_NOT_FOUND)
    body = validation.json_body()
    resolution = validation.field_enum(body, "resolution", C.COMPLAINT_RESOLUTIONS)
    validation.field_str(body, "resolution_note", required=False, default=None)

    if row["status"] != "CONTRACTOR_NOTIFIED":
        fail(errors.ERR_INVALID_STATE, "Only a notified complaint may be resolved.")
    if resolution == "ESCALATED":
        deadline = row["remedy_deadline_at"]
        if deadline is None or clock.now() < deadline:
            fail(
                errors.ERR_INVALID_STATE,
                "The remedy window has not expired, so the complaint may not be escalated.",
            )

    contractor = db.contractors.get(row["contractor_id"])
    snapshot = domain.contractor_snapshot(contractor) if contractor else None

    row["status"] = resolution
    if resolution in ("REMEDIED", "DISMISSED"):
        row["resolved_at"] = clock.now()
    db.touch(row)

    if contractor is not None:
        domain.rescore_contractor(contractor, snapshot)

    return response.object_response(serializers.complaint(row))


@bp.post(API_PREFIX + "/complaints/<complaint_id>/sanction")
@middleware.roles(middleware.PROGRAM_MANAGER)
def sanction_contractor(complaint_id):
    row = validation.path_row(db.complaints, complaint_id, errors.ERR_COMPLAINT_NOT_FOUND)
    body = validation.json_body()
    sanction_level = validation.field_enum(body, "sanction_level", C.SANCTION_LEVELS)
    validation.field_str(body, "sanction_note", required=False, default=None)

    if row["status"] != "ESCALATED":
        fail(errors.ERR_INVALID_STATE, "Only an escalated complaint may be sanctioned.")

    row["status"] = "SANCTIONED"
    row["sanction_level"] = sanction_level
    row["resolved_at"] = clock.now()
    db.touch(row)

    contractor = db.contractors.get(row["contractor_id"])
    if contractor is not None:
        contractor["sanction_count"] += 1
        contractor["approved_list_status"] = C.SANCTION_TO_STANDING[sanction_level]
        db.touch(contractor)
        if sanction_level in ("SUSPENSION", "REMOVAL"):
            domain.withdraw_live_bids(contractor)

    return response.object_response(serializers.complaint(row))


@bp.get(API_PREFIX + "/complaints/<complaint_id>")
@middleware.roles(*READ_ONE_ROLES)
def read_complaint(complaint_id):
    middleware.scope_complaint(complaint_id)
    row = validation.path_row(db.complaints, complaint_id, errors.ERR_COMPLAINT_NOT_FOUND)
    return response.object_response(serializers.complaint(row))


@bp.get(API_PREFIX + "/complaints")
@middleware.roles(*READ_ROLES)
def list_complaints():
    contractor_id = validation.filter_str("contractor_id")
    application_id = validation.filter_str("application_id")
    status = validation.filter_enum("status", C.COMPLAINT_STATUSES)
    rows = []
    for row in db.complaints.values():
        if contractor_id is not None and row["contractor_id"] != contractor_id:
            continue
        if application_id is not None and row["application_id"] != application_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paging.collection(rows, serializers.complaint)
