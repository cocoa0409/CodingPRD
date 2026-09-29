"""RecallEvent endpoints (PRD 3.9)."""

from flask import Blueprint

import calc
import cascade
import lookup
import response
import serialize
import store
import validate
from auth import authorize
from errors import fail
from routes._common import paged
from store import db, mark_dirty, now

bp = Blueprint("recalls", __name__)


@bp.post("/recall-events")
@authorize("SafetyDirector")
def create_recall_event():
    data = validate.body()

    product = None
    if validate.present(data, "product_id"):
        product = lookup.product(data["product_id"])

    validate.req_id(data, "product_id")
    remedy_type = validate.req_enum(data, "remedy_type", calc.REMEDY_TYPES)
    affected_revision_ids = validate.req_str_array(data, "affected_revision_ids")
    hazard_description = validate.req_str(data, "hazard_description")

    # step 49
    for existing in lookup.where(db.recall_events, product_id=product["id"]):
        if existing["status"] in ("DRAFT", "ANNOUNCED", "IN_PROGRESS"):
            fail("ERR_RECALL_ALREADY_OPEN", "a live recall already exists for this model")

    recall = store.base_record()
    recall.update(
        {
            "product_id": product["id"],
            "remedy_type": remedy_type,
            "affected_revision_ids": list(affected_revision_ids),
            "hazard_description": hazard_description,
            "status": "DRAFT",
            "announced_at": None,
            "exposure_units_shipped_basis": None,
            "exposure_units_registered_basis": None,
            "notification_coverage_pct": None,
            "units_remedied": 0,
            "units_outstanding": 0,
            "closed_at": None,
        }
    )
    db.recall_events[recall["id"]] = recall
    store.register_new(recall)
    return response.created(recall, serialize.recall_event)


@bp.get("/recall-events/<recall_id>")
@authorize("SafetyDirector", "ComplianceOfficer", "Consumer")
def get_recall_event(recall_id):
    recall = lookup.recall_event(recall_id)
    return response.obj(recall, serialize.recall_event)


@bp.get("/recall-events")
@authorize("SafetyDirector", "ComplianceOfficer")
def list_recall_events():
    spec = {"product_id": "product_id", "status": "status", "remedy_type": "remedy_type"}
    return paged(lookup.rows(db.recall_events), spec, serialize.recall_event)


@bp.post("/recall-events/<recall_id>/announce")
@authorize("SafetyDirector")
def announce_recall_event(recall_id):
    recall = lookup.recall_event(recall_id)

    # step 21
    if recall["status"] != "DRAFT":
        fail("ERR_RECALL_STATE_INVALID", "status must be DRAFT to announce")

    product = db.products[recall["product_id"]]
    if product["market_status"] not in ("RETAIL_RELEASED", "STOP_SHIP"):
        fail(
            "ERR_PRODUCT_STATE_INVALID",
            "market_status must be RETAIL_RELEASED or STOP_SHIP to announce a recall",
        )

    # step 50
    if not cascade.in_scope_lots(recall):
        fail("ERR_RECALL_SCOPE_EMPTY", "the recall scope contains no shipped lots")

    cascade.announce_recall(recall)
    return response.obj(recall, serialize.recall_event)


@bp.post("/recall-events/<recall_id>/notify")
@authorize("SafetyDirector", "ComplianceOfficer")
def notify_recall_event(recall_id):
    recall = lookup.recall_event(recall_id)

    if recall["status"] != "ANNOUNCED":
        fail("ERR_RECALL_STATE_INVALID", "status must be ANNOUNCED to notify")

    recall["status"] = "IN_PROGRESS"
    mark_dirty(recall)

    for registration in lookup.where(db.consumer_registrations, recall_event_id=recall["id"]):
        if registration["registration_status"] != "REGISTERED":
            continue
        registration["registration_status"] = "NOTIFIED"
        registration["notified_at"] = now()
        mark_dirty(registration)

    return response.obj(recall, serialize.recall_event)


@bp.post("/recall-events/<recall_id>/close")
@authorize("SafetyDirector")
def close_recall_event(recall_id):
    recall = lookup.recall_event(recall_id)

    if recall["status"] != "IN_PROGRESS":
        fail("ERR_RECALL_STATE_INVALID", "status must be IN_PROGRESS to close")

    outstanding = recall["units_outstanding"] or 0
    window_elapsed = recall["announced_at"] is not None and now() >= calc.add_days(
        recall["announced_at"], calc.MAX_RECALL_WINDOW_DAYS
    )
    if outstanding != 0 and not window_elapsed:
        fail("ERR_RECALL_UNITS_OUTSTANDING", "remedies are still outstanding")

    recall["status"] = "CLOSED"
    recall["closed_at"] = now()
    mark_dirty(recall)
    return response.obj(recall, serialize.recall_event)
