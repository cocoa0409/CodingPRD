"""Prescriber responses and the two-step verification sweep."""

from flask import Blueprint

from db import db, now, sort_rows, touch
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
    require_role,
)
from response import list_response, object_response
from services.events import append_event
from services.workflow import clear_pending_orders, deny_prescription, verification_sweep

bp = Blueprint("verification", __name__)

REQUEST_STATUSES = ("SENT", "CONFIRMED", "CORRECTED", "DENIED", "PASSIVE_TIMEOUT")
RESPONSE_TYPES = ("CONFIRMED", "CORRECTED", "DENIED")


@bp.get("/verification-requests/<request_id>")
def get_verification_request(request_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_PRESCRIBER])
    row = lookup("verification_request", request_id)
    require_owner(role, user_id, row["prescriber_id"], ROLE_PRESCRIBER)
    return object_response(row)


@bp.get("/verification-requests")
def list_verification_requests():
    user_id, role = identity()
    filters = parse_query(
        {
            "prescription_id": {"type": "string"},
            "prescriber_id": {"type": "string"},
            "status": {"type": "enum", "values": REQUEST_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_PRESCRIBER])
    rows = list(db.verification_requests.values())
    if role == ROLE_PRESCRIBER:
        rows = [r for r in rows if r["prescriber_id"] == user_id]
    if filters["prescription_id"]:
        rows = [r for r in rows if r["prescription_id"] == filters["prescription_id"]]
    if filters["prescriber_id"]:
        rows = [r for r in rows if r["prescriber_id"] == filters["prescriber_id"]]
    if filters["status"]:
        rows = [r for r in rows if r["status"] == filters["status"]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/verification-requests/<request_id>/respond")
def respond_to_verification_request(request_id):
    user_id, role = identity()
    body = parse_body(
        {
            "response_type": {"type": "enum", "values": RESPONSE_TYPES, "required": True},
            "corrected_od_sphere": {"type": "decimal", "places": 2},
            "corrected_os_sphere": {"type": "decimal", "places": 2},
            "note": {"type": "string"},
        }
    )
    if body["response_type"] == "CORRECTED" and (
        body["corrected_od_sphere"] is None or body["corrected_os_sphere"] is None
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "A CORRECTED response requires corrected_od_sphere and corrected_os_sphere.",
        )
    require_role(role, [ROLE_PRESCRIBER, ROLE_ADMIN])
    request_row = lookup("verification_request", request_id)
    require_owner(role, user_id, request_row["prescriber_id"], ROLE_PRESCRIBER)
    if request_row["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    deadline = request_row.get("passive_deadline_at")
    if deadline is not None and now() >= deadline:
        raise ApiError("ERR_VERIFICATION_WINDOW_CLOSED")

    prescription = db.prescriptions.get(request_row["prescription_id"])
    actor = (role, user_id)
    response_type = body["response_type"]
    request_row["status"] = response_type
    request_row["response_type"] = response_type
    touch(request_row)

    if response_type == "CONFIRMED":
        if prescription is not None:
            prescription["status"] = "VERIFIED_ACTIVE"
            touch(prescription)
            append_event(
                prescription["id"],
                "RESPONSE_RECEIVED",
                "VerificationRequest",
                request_row["id"],
                actor,
            )
            clear_pending_orders(prescription, "RESPONSE_RECEIVED", actor)
    elif response_type == "CORRECTED":
        if prescription is not None:
            prescription["status"] = "CORRECTION_PENDING"
            prescription["od_sphere"] = body["corrected_od_sphere"]
            prescription["os_sphere"] = body["corrected_os_sphere"]
            touch(prescription)
            append_event(
                prescription["id"],
                "RESPONSE_RECEIVED",
                "VerificationRequest",
                request_row["id"],
                actor,
                "parameters corrected",
            )
    else:  # DENIED
        if prescription is not None:
            deny_prescription(prescription, actor)
    return object_response(request_row)


@bp.post("/compliance/verification-sweep")
def run_verification_sweep():
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    return object_response(verification_sweep())
