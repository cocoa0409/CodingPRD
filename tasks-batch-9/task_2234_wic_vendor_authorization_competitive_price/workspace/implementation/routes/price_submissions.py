"""Shelf price submission endpoints (PRD §3.3)."""

from flask import Blueprint

import clock
import config as C
import envelope
import models
import services
import validators
from auth import authenticate, check_vendor_scope
from errors import ApiError
from routes.common import body_fk, listing, need
from store import db, ordered

bp = Blueprint("price_submissions", __name__)

READ_ROLES = (C.ROLE_ANALYST, C.ROLE_SUPERVISOR, C.ROLE_VENDOR_OPERATOR)


def _window_open(cycle):
    now = clock.now()
    return (
        cycle["status"] == "OPEN"
        and cycle["submission_open_at"] <= now < cycle["submission_due_at"]
    )


@bp.post("/price-submissions")
def create_submission():
    caller = authenticate(C.ROLE_VENDOR_OPERATOR)
    payload = validators.body()
    raw_vendor = payload.get("vendor_id")
    if isinstance(raw_vendor, str):
        check_vendor_scope(caller, raw_vendor)

    vendor = body_fk(payload, "vendor_id", db.vendors, "ERR_VENDOR_NOT_FOUND")
    item = body_fk(payload, "food_item_id", db.food_items, "ERR_FOOD_ITEM_NOT_FOUND")
    cycle = body_fk(payload, "price_cycle_id", db.price_cycles, "ERR_PRICE_CYCLE_NOT_FOUND")

    vendor_id = validators.req_string(payload, "vendor_id")
    item_id = validators.req_string(payload, "food_item_id")
    cycle_id = validators.req_string(payload, "price_cycle_id")
    price = validators.req_int(payload, "shelf_price_cents", minimum=1)

    if services.disqualification_live(vendor):
        raise ApiError("ERR_VENDOR_DISQUALIFIED")
    if not _window_open(cycle):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED")
    for existing in db.price_submissions.values():
        if (
            existing["vendor_id"] == vendor_id
            and existing["food_item_id"] == item_id
            and existing["price_cycle_id"] == cycle_id
            and existing["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")
        ):
            raise ApiError("ERR_DUPLICATE_PRICE_SUBMISSION")

    record = models.price_submission(
        vendor_id=vendor_id,
        food_item_id=item_id,
        price_cycle_id=cycle_id,
        shelf_price_cents=price,
    )
    db.price_submissions[record["id"]] = record
    return envelope.success(record, 201)


@bp.get("/price-submissions/<entity_id>")
def read_submission(entity_id):
    caller = authenticate(*READ_ROLES)
    submission = need(db.price_submissions, entity_id, "ERR_PRICE_SUBMISSION_NOT_FOUND")
    check_vendor_scope(caller, submission["vendor_id"])
    return envelope.success(submission)


@bp.get("/price-submissions")
def list_submissions():
    authenticate(*READ_ROLES)
    return listing(
        ordered(db.price_submissions),
        {
            "vendor_id": "vendor_id",
            "food_item_id": "food_item_id",
            "price_cycle_id": "price_cycle_id",
            "status": "status",
        },
    )


@bp.post("/price-submissions/<entity_id>/review")
def review_submission(entity_id):
    caller = authenticate(C.ROLE_ANALYST)
    submission = need(db.price_submissions, entity_id, "ERR_PRICE_SUBMISSION_NOT_FOUND")
    payload = validators.body()
    decision = validators.req_enum(payload, "decision", ["ACCEPT", "REJECT"])
    reason = validators.opt_enum(payload, "review_reason", C.REVIEW_REASONS)
    if decision == "REJECT" and reason is None:
        raise validators.invalid("Field 'review_reason' is required when rejecting.")
    if submission["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE")

    services.update(
        submission,
        status="ACCEPTED" if decision == "ACCEPT" else "REJECTED",
        review_reason=reason if decision == "REJECT" else None,
        reviewed_by_user_id=caller.user_id,
        reviewed_at=clock.now(),
    )
    vendor = db.vendors.get(submission["vendor_id"])
    if vendor is not None:
        services.refresh_completeness(vendor)
    return envelope.success(submission)


@bp.post("/price-submissions/<entity_id>/revise")
def revise_submission(entity_id):
    caller = authenticate(C.ROLE_VENDOR_OPERATOR)
    submission = need(db.price_submissions, entity_id, "ERR_PRICE_SUBMISSION_NOT_FOUND")
    check_vendor_scope(caller, submission["vendor_id"])
    payload = validators.body()
    price = validators.req_int(payload, "shelf_price_cents", minimum=1)
    if submission["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE")
    cycle = db.price_cycles.get(submission["price_cycle_id"])
    if cycle is None or not _window_open(cycle):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED")
    if submission["revision_count"] >= C.MAX_SUBMISSION_REVISIONS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")

    services.update(
        submission,
        status="SUBMITTED",
        shelf_price_cents=price,
        revision_count=submission["revision_count"] + 1,
        review_reason=None,
        reviewed_by_user_id=None,
        reviewed_at=None,
    )
    return envelope.success(submission)
