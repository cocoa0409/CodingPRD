"""WaterQualityComplaint endpoints: create (with cluster rule), list, get, link, close."""
from flask import Blueprint, request

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_COMPLAINT_NOT_CLOSABLE,
    ERR_COMPLAINT_NOT_FOUND,
    ERR_COMPLAINT_NOT_LINKABLE,
    ERR_FLUSH_SEQUENCE_NOT_FOUND,
    ERR_HYDRANT_NOT_FOUND,
    ERR_LINKED_SEQUENCE_NOT_COMPLETED,
    ERR_LINK_HYDRANT_MISMATCH,
    ERR_SEQUENCE_NOT_PLANNED,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from serializers import complaint_view
from services import evaluate_complaint_cluster
from validation import F, paginate, validate_body

bp = Blueprint("complaints", __name__)


def get_complaint_or_404(complaint_id):
    c = db.store.complaints.get(complaint_id)
    if c is None:
        raise not_found(ERR_COMPLAINT_NOT_FOUND, "WaterQualityComplaint")
    return c


@bp.post("/complaints")
def create_complaint():
    user_id, role = auth()
    body = validate_body([
        F("hydrant_id", "str"),
        F("category", "enum", arg={"DISCOLORED_WATER", "ODOR", "TASTE", "PRESSURE"}),
        F("description", "str", required=False, default=""),
    ])
    require_role(role, {"FieldOperator"})
    if body["hydrant_id"] not in db.store.hydrants:
        raise not_found(ERR_HYDRANT_NOT_FOUND, "Hydrant")
    complaint = new_base()
    complaint.update({
        "hydrant_id": body["hydrant_id"],
        "category": body["category"],
        "description": body["description"],
        "status": "OPEN",
        "flush_sequence_id": None,
    })
    db.store.complaints[complaint["id"]] = complaint
    # complaint_cluster calculation runs after inserting the new complaint
    evaluate_complaint_cluster(complaint)
    return success_object(complaint_view(complaint), code=201)


@bp.get("/complaints")
def list_complaints():
    auth_any()
    items = list(db.store.complaints.values())
    for field in ("hydrant_id", "flush_sequence_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [c for c in items if c[field] == value]
    page, meta = paginate(items)
    return success_list([complaint_view(c) for c in page], meta)


@bp.get("/complaints/<complaint_id>")
def get_complaint(complaint_id):
    auth_any()
    return success_object(complaint_view(get_complaint_or_404(complaint_id)))


@bp.post("/complaints/<complaint_id>/link")
def link_complaint(complaint_id):
    user_id, role = auth()
    body = validate_body([F("flush_sequence_id", "str")])
    require_role(role, {"FieldOperator"})
    complaint = get_complaint_or_404(complaint_id)
    sequence = db.store.flush_sequences.get(body["flush_sequence_id"])
    if sequence is None:
        raise not_found(ERR_FLUSH_SEQUENCE_NOT_FOUND, "FlushSequence")
    if complaint["status"] != "OPEN":
        raise ApiError(ERR_COMPLAINT_NOT_LINKABLE, "Complaint must be OPEN to link", 409)
    if sequence["status"] != "PLANNED":
        raise ApiError(ERR_SEQUENCE_NOT_PLANNED, "Target sequence must be PLANNED", 409)
    if sequence["hydrant_id"] != complaint["hydrant_id"]:
        raise ApiError(
            ERR_LINK_HYDRANT_MISMATCH,
            "Complaint and target sequence reference different hydrants",
            422,
        )
    complaint["status"] = "LINKED"
    complaint["flush_sequence_id"] = sequence["id"]
    touch(complaint)
    return success_object(complaint_view(complaint))


@bp.post("/complaints/<complaint_id>/close")
def close_complaint(complaint_id):
    user_id, role = auth()
    body = validate_body([F("outcome", "enum", arg={"RESOLVED", "DISMISSED"})])
    require_role(role, {"UtilitySupervisor"})
    complaint = get_complaint_or_404(complaint_id)
    if body["outcome"] == "RESOLVED":
        # Requires LINKED with its linked sequence COMPLETED
        if complaint["status"] in ("RESOLVED", "DISMISSED"):
            raise ApiError(
                ERR_COMPLAINT_NOT_CLOSABLE,
                "Complaint is already in a terminal state",
                409,
            )
        linked = (
            db.store.flush_sequences.get(complaint["flush_sequence_id"])
            if complaint["flush_sequence_id"] else None
        )
        if complaint["status"] != "LINKED" or linked is None or linked["status"] != "COMPLETED":
            raise ApiError(
                ERR_LINKED_SEQUENCE_NOT_COMPLETED,
                "Manual RESOLVED close requires the linked sequence COMPLETED",
                409,
            )
        complaint["status"] = "RESOLVED"
    else:
        # DISMISSED only from OPEN
        if complaint["status"] != "OPEN":
            raise ApiError(
                ERR_COMPLAINT_NOT_CLOSABLE,
                "DISMISSED close is only valid from OPEN",
                409,
            )
        complaint["status"] = "DISMISSED"
    touch(complaint)
    return success_object(complaint_view(complaint))
