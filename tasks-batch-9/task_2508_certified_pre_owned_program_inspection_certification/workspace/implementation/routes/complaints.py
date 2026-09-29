"""Customer complaints and the re-inspection clock (PRD 3.11)."""
from datetime import timedelta

from flask import Blueprint

import cascades as cas
import enums
import helpers as h
import serializers as ser
from db import db, new_id
from errors import ApiError

bp = Blueprint("complaints", __name__)

READ_ROLES = (
    "ProgramAdministrator",
    "ProgramAuditor",
    "DealerPrincipal",
    "CustomerAdvocate",
)
LIVE_STATUSES = ("ACTIVE", "UNDER_AUDIT")
REINSPECTION_DEADLINE_DAYS = 5


@bp.route("/complaints", methods=["POST"])
def file_complaint():
    h.authorize(("CustomerAdvocate",))
    body = h.body_dict()
    certification_id = h.f_string(body, "certification_id")
    customer_reference = h.f_string(body, "customer_reference")
    category = h.f_enum(body, "category", enums.COMPLAINT_CATEGORIES)
    description = h.f_string(body, "description")

    certification = db.certifications.get(certification_id)
    if certification is None:
        raise ApiError(
            "ERR_REFERENCED_ENTITY_NOT_FOUND", "certification_id does not resolve."
        )
    if certification["status"] not in LIVE_STATUSES:
        raise ApiError(
            "ERR_CERTIFICATION_NOT_ACTIVE",
            "A complaint may only be logged against a live certification.",
        )

    row = h.new_common(
        {
            "id": new_id(),
            "certification_id": certification_id,
            "customer_reference": customer_reference,
            "category": category,
            "description": description,
            "status": "OPEN",
            "filed_at": db.clock,
            "reinspection_deadline_at": db.clock
            + timedelta(days=REINSPECTION_DEADLINE_DAYS),
            "reinspection_ordered_at": None,
            "resolved_at": None,
        }
    )
    db.complaints[row["id"]] = row
    return h.object_response(ser.complaint(row), 201)


@bp.route("/certifications/<certification_id>/complaints", methods=["GET"])
def list_complaints(certification_id):
    h.authorize(READ_ROLES)
    status = h.q_enum("status", enums.COMPLAINT_STATUSES)
    category = h.q_enum("category", enums.COMPLAINT_CATEGORIES)
    limit, offset = h.pagination()
    if certification_id not in db.certifications:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND", "No certification with that id.")
    rows = cas.certification_complaints(certification_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    if category:
        rows = [r for r in rows if r["category"] == category]
    return h.paged(rows, limit, offset, ser.complaint)


@bp.route("/complaints/<complaint_id>", methods=["GET"])
def read_complaint(complaint_id):
    h.authorize(READ_ROLES)
    row = db.complaints.get(complaint_id)
    if row is None:
        raise ApiError("ERR_COMPLAINT_NOT_FOUND", "No complaint with that id.")
    return h.object_response(ser.complaint(row))
