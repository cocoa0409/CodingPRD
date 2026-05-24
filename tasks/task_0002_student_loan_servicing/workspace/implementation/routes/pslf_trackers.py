"""PSLFTracker endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import current_role, current_user_id, require_roles
from response import success, success_list
from routes._common import (
    get_field,
    must_get,
    parse_json_body,
)
from services import loan_ops, serializer

bp = Blueprint("pslf_trackers", __name__)


@bp.post("/v1/pslf-trackers")
@require_roles({"LoanServicer", "PSLFAdjudicator"})
def create_tracker():
    body = parse_json_body()
    borrower_id = get_field(body, "borrower_id")
    must_get(db.borrowers, borrower_id, "Borrower")
    # At most one per borrower
    existing = serializer.tracker_for_borrower(borrower_id)
    if existing:
        raise APIError(ERR_INVALID_STATE, "PSLFTracker already exists for borrower")

    tid = db.new_id()
    now = db.now_iso()
    tracker = {
        "id": tid,
        "borrower_id": borrower_id,
        "qualifying_payment_count": 0,
        "required_payment_count": 120,
        "status": "TRACKING",
        "last_recount_on": db.get_clock_date(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.pslf_trackers[tid] = tracker
    return success(serializer.serialize_tracker(tracker), status=201)


@bp.post("/v1/pslf-trackers/<tracker_id>/recount")
@require_roles({"LoanServicer", "PSLFAdjudicator"})
def recount(tracker_id):
    tracker = must_get(db.pslf_trackers, tracker_id, "PSLFTracker")
    if tracker["status"] in {"FORGIVEN", "DENIED"}:
        # Idempotent: leave terminal trackers alone
        return success(serializer.serialize_tracker(tracker), status=200)
    loan_ops.recount_pslf_tracker(tracker)
    return success(serializer.serialize_tracker(tracker), status=200)


@bp.post("/v1/pslf-trackers/<tracker_id>/deny")
@require_roles({"PSLFAdjudicator"})
def deny(tracker_id):
    tracker = must_get(db.pslf_trackers, tracker_id, "PSLFTracker")
    if tracker["status"] != "TRACKING":
        raise APIError(ERR_INVALID_STATE, "Tracker not in TRACKING state")
    tracker["status"] = "DENIED"
    serializer.bump_tracker(tracker)
    return success(serializer.serialize_tracker(tracker), status=200)


@bp.get("/v1/pslf-trackers/<tracker_id>")
@require_roles({"LoanServicer", "PSLFAdjudicator", "Borrower"})
def get_tracker(tracker_id):
    tracker = must_get(db.pslf_trackers, tracker_id, "PSLFTracker")
    if current_role() == "Borrower" and current_user_id() != tracker["borrower_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this tracker")
    return success(serializer.serialize_tracker(tracker), status=200)


@bp.post("/v1/_pslf-trackers/<tracker_id>/force-state")
@require_roles({"PSLFAdjudicator"})
def force_state(tracker_id):
    tracker = must_get(db.pslf_trackers, tracker_id, "PSLFTracker")
    body = parse_json_body()
    qpc = get_field(body, "qualifying_payment_count")
    status = get_field(body, "status")
    if not isinstance(qpc, int) or isinstance(qpc, bool) or qpc < 0:
        raise APIError(ERR_INVALID_REQUEST, "qualifying_payment_count must be int >= 0")
    if status not in {"TRACKING", "ELIGIBLE_FOR_FORGIVENESS"}:
        raise APIError(ERR_INVALID_REQUEST, "status must be TRACKING or ELIGIBLE_FOR_FORGIVENESS")
    tracker["qualifying_payment_count"] = qpc
    tracker["status"] = status
    tracker["last_recount_on"] = db.get_clock_date()
    serializer.bump_tracker(tracker)
    return success(serializer.serialize_tracker(tracker), status=200)
