"""ConsumerRegistration endpoints (PRD 3.7, 3.9)."""

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

bp = Blueprint("consumers", __name__)


@bp.post("/consumer-registrations")
@authorize("Consumer", "ComplianceOfficer")
def create_consumer_registration():
    data = validate.body()

    lot = None
    if validate.present(data, "production_lot_id"):
        lot = lookup.production_lot(data["production_lot_id"])

    validate.req_id(data, "production_lot_id")
    consumer_email = validate.req_str(data, "consumer_email")
    purchase_channel = validate.req_enum(data, "purchase_channel", calc.PURCHASE_CHANNELS)
    purchase_date = validate.req_instant(data, "purchase_date")
    serial_suffix = validate.req_str(data, "serial_suffix")

    # step 9
    validate.check_not_future(purchase_date, "purchase_date")

    # step 44
    if lot["status"] not in ("RELEASED", "QUARANTINED"):
        fail("ERR_LOT_NOT_SHIPPABLE", "the lot has not shipped")

    hold_flag = lot["status"] == "QUARANTINED"
    registration = store.base_record()
    registration.update(
        {
            "production_lot_id": lot["id"],
            "recall_event_id": None,
            "consumer_email": consumer_email,
            "purchase_channel": purchase_channel,
            "purchase_date": purchase_date,
            "serial_suffix": serial_suffix,
            "registration_status": "REGISTERED",
            "hold_flag": hold_flag,
            "notified_at": None,
            "acknowledged_at": None,
            "remedy_choice": None,
        }
    )
    db.consumer_registrations[registration["id"]] = registration
    store.register_new(registration)

    if hold_flag:
        product = db.products.get(lot["product_id"])
        if product is not None:
            cascade.recompute_held_registration_count(product)
    return response.created(registration, serialize.consumer_registration)


@bp.get("/consumer-registrations/<registration_id>")
@authorize("Consumer", "ComplianceOfficer", "SafetyDirector")
def get_consumer_registration(registration_id):
    registration = lookup.consumer_registration(registration_id)
    return response.obj(registration, serialize.consumer_registration)


@bp.get("/consumer-registrations")
@authorize("ComplianceOfficer", "SafetyDirector")
def list_consumer_registrations():
    spec = {
        "production_lot_id": "production_lot_id",
        "recall_event_id": "recall_event_id",
        "registration_status": "registration_status",
        "hold_flag": "hold_flag",
    }
    return paged(
        lookup.rows(db.consumer_registrations), spec, serialize.consumer_registration
    )


@bp.post("/consumer-registrations/<registration_id>/acknowledge")
@authorize("Consumer", "ComplianceOfficer")
def acknowledge_consumer_registration(registration_id):
    registration = lookup.consumer_registration(registration_id)
    data = validate.body()
    remedy_choice = validate.req_enum(data, "remedy_choice", calc.REMEDY_TYPES)

    # step 22
    if registration["registration_status"] != "NOTIFIED":
        fail("ERR_REGISTRATION_NOT_NOTIFIED", "registration_status must be NOTIFIED")

    recall = None
    if registration["recall_event_id"]:
        recall = db.recall_events.get(registration["recall_event_id"])
    # step 52
    if recall is None or remedy_choice != recall["remedy_type"]:
        fail("ERR_REMEDY_CHOICE_MISMATCH", "remedy_choice must match the recall remedy_type")

    registration["registration_status"] = "ACKNOWLEDGED"
    registration["acknowledged_at"] = now()
    registration["remedy_choice"] = remedy_choice
    mark_dirty(registration)

    recall["units_remedied"] = (recall["units_remedied"] or 0) + 1
    recall["units_outstanding"] = (recall["units_outstanding"] or 0) - 1
    mark_dirty(recall)
    return response.obj(registration, serialize.consumer_registration)
