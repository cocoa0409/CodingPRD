"""Prescriber disputes and the upheld cascade."""

from flask import Blueprint

from db import db, make_row, sort_rows, touch
from errors import ApiError
from middleware import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_PRESCRIBER,
    identity,
    lookup,
    paginate,
    parse_body,
    parse_pagination,
    parse_query,
    require_owner,
    require_prescriber_link,
    require_role,
)
from response import list_response, object_response
from services.events import append_event
from services.workflow import uphold_dispute

bp = Blueprint("disputes", __name__)

DISPUTE_REASONS = ("NOT_MY_PATIENT", "PARAMETERS_ALTERED", "NEVER_ISSUED")
DISPUTE_STATUSES = ("OPEN", "UPHELD", "DISMISSED")
RESOLUTIONS = ("UPHELD", "DISMISSED")


@bp.post("/prescriber-disputes")
def file_prescriber_dispute():
    user_id, role = identity()
    body = parse_body(
        {
            "prescription_id": {"type": "uuid", "required": True},
            "prescriber_id": {"type": "uuid", "required": True},
            "dispute_reason": {"type": "enum", "values": DISPUTE_REASONS, "required": True},
            "expected_prescription_version": {"type": "int", "required": True},
        }
    )
    require_role(role, [ROLE_PRESCRIBER, ROLE_ADMIN])
    prescription = lookup("prescription", body["prescription_id"])
    prescriber = lookup("prescriber", body["prescriber_id"])
    require_owner(role, user_id, prescriber["id"], ROLE_PRESCRIBER)
    require_prescriber_link(role, user_id, prescription["prescriber_id"])
    if body["expected_prescription_version"] != prescription["version"]:
        raise ApiError("ERR_STALE_PRESCRIPTION_VERSION")
    row = make_row(
        {
            "prescription_id": body["prescription_id"],
            "prescriber_id": body["prescriber_id"],
            "dispute_reason": body["dispute_reason"],
            "resolution": None,
            "resolved_by_user_id": None,
            "status": "OPEN",
        }
    )
    db.prescriber_disputes[row["id"]] = row
    append_event(
        prescription["id"], "DISPUTE_FILED", "PrescriberDispute", row["id"], (role, user_id)
    )
    return object_response(row, 201)


@bp.get("/prescriber-disputes/<dispute_id>")
def get_prescriber_dispute(dispute_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_PRESCRIBER])
    dispute = lookup("dispute", dispute_id)
    require_owner(role, user_id, dispute["prescriber_id"], ROLE_PRESCRIBER)
    return object_response(dispute)


@bp.get("/prescriber-disputes")
def list_prescriber_disputes():
    user_id, role = identity()
    filters = parse_query(
        {
            "prescription_id": {"type": "string"},
            "prescriber_id": {"type": "string"},
            "status": {"type": "enum", "values": DISPUTE_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_PRESCRIBER])
    rows = list(db.prescriber_disputes.values())
    if role == ROLE_PRESCRIBER:
        rows = [r for r in rows if r["prescriber_id"] == user_id]
    for field in ("prescription_id", "prescriber_id", "status"):
        if filters[field]:
            rows = [r for r in rows if r[field] == filters[field]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/prescriber-disputes/<dispute_id>/resolve")
def resolve_prescriber_dispute(dispute_id):
    user_id, role = identity()
    body = parse_body({"resolution": {"type": "enum", "values": RESOLUTIONS, "required": True}})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    dispute = lookup("dispute", dispute_id)
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    actor = (role, user_id)
    dispute["status"] = body["resolution"]
    dispute["resolution"] = body["resolution"]
    dispute["resolved_by_user_id"] = user_id
    touch(dispute)
    if body["resolution"] == "UPHELD":
        prescription = db.prescriptions.get(dispute["prescription_id"])
        if prescription is not None:
            uphold_dispute(prescription, actor)
    append_event(
        dispute["prescription_id"], "DISPUTE_RESOLVED", "PrescriberDispute", dispute["id"], actor
    )
    return object_response(dispute)
