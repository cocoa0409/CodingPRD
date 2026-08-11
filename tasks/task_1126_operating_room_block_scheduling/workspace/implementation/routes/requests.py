"""ReallocationRequest endpoints."""

from flask import Blueprint, request as freq

from db import db
from errors import (
    ApiError,
    ERR_CASE_NOT_FOUND,
    ERR_CASE_NOT_SCHEDULABLE,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_REQUEST_NOT_FOUND,
    ERR_REQUEST_NOT_PENDING,
    ERR_SLOT_NOT_FOUND,
    ERR_SLOT_NOT_OPEN,
)
from middleware import get_auth, require_roles, get_json_body
from response import success_object, paginate
from serializers import request_json
from services import new_common, touch, turnover_for

bp = Blueprint("requests", __name__)

REQUEST_STATUSES = {"PENDING", "APPROVED", "REJECTED", "WITHDRAWN", "EXPIRED"}


@bp.route("/reallocation-requests", methods=["POST"])
def create_request():
    auth = require_roles("Surgeon")
    body = get_json_body()
    slot_id = body.get("slot_id")
    case_id = body.get("case_id")

    # ownership (priority 3): the referenced case must be the caller's own
    case = db.cases.get(case_id) if isinstance(case_id, str) else None
    if case is not None and case["surgeon_id"] != auth.user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            403,
            "reallocation requests require ownership of the underlying case",
        )
    # existence (priority 4): body FKs in declared order (slot_id, case_id)
    if isinstance(slot_id, str) and slot_id not in db.slots:
        raise ApiError(ERR_SLOT_NOT_FOUND, 404, "open-time slot not found")
    if isinstance(case_id, str) and case_id not in db.cases:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "case not found")
    # shape
    if not isinstance(slot_id, str) or not slot_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "slot_id is required")
    if not isinstance(case_id, str) or not case_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "case_id is required")

    slot = db.slots[slot_id]
    # state: slot OPEN; case POSTED or BUMPED
    if slot["status"] != "OPEN":
        raise ApiError(
            ERR_SLOT_NOT_OPEN, 409, "reallocation request requires slot status OPEN"
        )
    if case["status"] not in ("POSTED", "BUMPED"):
        raise ApiError(
            ERR_CASE_NOT_SCHEDULABLE,
            409,
            "reallocation eligibility requires case status POSTED or BUMPED",
        )

    room = db.rooms[slot["or_id"]]
    needed = case["predicted_duration_minutes"] + turnover_for(
        case["procedure_class"], room
    )
    rec = new_common()
    rec.update(
        {
            "slot_id": slot_id,
            "surgeon_id": case["surgeon_id"],
            "case_id": case_id,
            "needed_minutes": needed,
            "status": "PENDING",
        }
    )
    db.requests[rec["id"]] = rec
    return success_object(request_json(rec), 201)


@bp.route("/reallocation-requests", methods=["GET"])
def list_requests():
    get_auth()
    items = list(db.requests.values())
    slot_id = freq.args.get("slot_id")
    if slot_id is not None:
        items = [r for r in items if r["slot_id"] == slot_id]
    surgeon_id = freq.args.get("surgeon_id")
    if surgeon_id is not None:
        items = [r for r in items if r["surgeon_id"] == surgeon_id]
    case_id = freq.args.get("case_id")
    if case_id is not None:
        items = [r for r in items if r["case_id"] == case_id]
    st = freq.args.get("status")
    if st is not None:
        if st not in REQUEST_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [r for r in items if r["status"] == st]
    out = [request_json(r) for r in items]
    out.sort(key=lambda r: (r["created_at"],))
    return paginate(out)


@bp.route("/reallocation-requests/<requestId>", methods=["GET"])
def get_request(requestId):
    get_auth()
    rec = db.requests.get(requestId)
    if rec is None:
        raise ApiError(ERR_REQUEST_NOT_FOUND, 404, "reallocation request not found")
    return success_object(request_json(rec))


@bp.route("/reallocation-requests/<requestId>/withdraw", methods=["POST"])
def withdraw_request(requestId):
    auth = require_roles("Surgeon")
    rec = db.requests.get(requestId)
    if rec is None:
        raise ApiError(ERR_REQUEST_NOT_FOUND, 404, "reallocation request not found")
    if rec["surgeon_id"] != auth.user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            403,
            "a surgeon may only withdraw their own requests",
        )
    if rec["status"] != "PENDING":
        raise ApiError(
            ERR_REQUEST_NOT_PENDING, 409, "withdraw requires request status PENDING"
        )
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success_object(request_json(rec))
