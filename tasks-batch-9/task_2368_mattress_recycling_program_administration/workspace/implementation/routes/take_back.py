"""The retailer take-back-with-delivery obligation."""

from flask import Blueprint, g

import calc
import response
import services
from db import db
from errors import ApiError
from middleware import (ADMIN, AUDITOR, REGISTRANT, SITE_OPERATOR, auth,
                        get_delivery, get_registrant, get_site, own)
from util import (F, apply_filters, base_record, pagination, paginate, public,
                  sort_records, touch, validate_body)

bp = Blueprint("take_back", __name__)

READ_ROLES = [ADMIN, AUDITOR, REGISTRANT, SITE_OPERATOR]


def _delivery_ownership(delivery):
    if g.role == REGISTRANT:
        own(delivery["registrant_id"])
    elif g.role == SITE_OPERATOR:
        own(delivery["collection_site_id"])


@bp.post("/take-back-deliveries")
def create_delivery():
    auth([REGISTRANT])
    body = validate_body([
        F("registrant_id", "string"),
        F("collection_site_id", "string"),
        F("delivery_reference", "string"),
        F("units_delivered_new", "int", minimum=1),
        F("units_takeback_offered", "int", minimum=0),
    ])
    registrant = get_registrant(body["registrant_id"])
    site = get_site(body["collection_site_id"])
    own(registrant["id"])

    if body["units_takeback_offered"] < body["units_delivered_new"]:
        raise ApiError("ERR_TAKEBACK_OFFER_BELOW_DELIVERY")

    rec = base_record()
    rec.update({
        "registrant_id": registrant["id"],
        "collection_site_id": site["id"],
        "delivery_reference": body["delivery_reference"],
        "units_delivered_new": body["units_delivered_new"],
        "units_takeback_offered": body["units_takeback_offered"],
        "units_takeback_collected": None,
        "waiver_reference": None,
        "status": "SCHEDULED",
        "breach_units": 0,
        "breach_penalty_cents": 0,
    })
    db.take_back_deliveries[rec["id"]] = rec
    return response.obj(public(rec), 201)


@bp.get("/take-back-deliveries/<delivery_id>")
def read_delivery(delivery_id):
    auth(READ_ROLES)
    delivery = get_delivery(delivery_id)
    _delivery_ownership(delivery)
    return response.obj(public(delivery))


@bp.get("/take-back-deliveries")
def list_deliveries():
    auth(READ_ROLES)
    limit, offset = pagination()
    records = sort_records(list(db.take_back_deliveries.values()))
    records = apply_filters(records, [
        ("registrant_id", "registrant_id"),
        ("collection_site_id", "collection_site_id"),
        ("status", "status"),
    ])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/take-back-deliveries/<delivery_id>/complete-takeback")
def complete_takeback(delivery_id):
    auth([REGISTRANT])
    body = validate_body([F("units_takeback_collected", "int", minimum=0)])
    delivery = get_delivery(delivery_id)
    own(delivery["registrant_id"])

    if delivery["status"] != "SCHEDULED":
        raise ApiError("ERR_TAKEBACK_NOT_SCHEDULED")

    site = db.collection_sites[delivery["collection_site_id"]]
    if site["enrollment_status"] != "ENROLLED":
        raise ApiError("ERR_SITE_NOT_ENROLLED")

    collected = body["units_takeback_collected"]
    if collected > delivery["units_takeback_offered"]:
        raise ApiError("ERR_TAKEBACK_COLLECTED_ABOVE_OFFER")

    delivery["units_takeback_collected"] = collected
    if collected >= delivery["units_delivered_new"]:
        delivery["status"] = "OBLIGATION_MET"
        delivery["breach_units"] = 0
        delivery["breach_penalty_cents"] = 0
    else:
        breach_units = delivery["units_delivered_new"] - collected
        delivery["status"] = "OBLIGATION_BREACHED"
        delivery["breach_units"] = breach_units
        delivery["breach_penalty_cents"] = (breach_units
                                            * calc.TAKEBACK_BREACH_PENALTY_CENTS)
    touch(delivery)

    site["units_on_hand"] += collected
    site["units_reported_total"] += collected
    touch(site)

    if delivery["status"] == "OBLIGATION_BREACHED":
        registrant = db.registrants[delivery["registrant_id"]]
        services.refresh_registrant(registrant)
        touch(registrant)

    services.refresh_program_and_touch(db.state_programs[site["state_program_id"]])
    return response.obj(public(delivery))


@bp.post("/take-back-deliveries/<delivery_id>/waive")
def waive(delivery_id):
    auth([REGISTRANT])
    body = validate_body([F("waiver_reference", "string")])
    delivery = get_delivery(delivery_id)
    own(delivery["registrant_id"])

    if delivery["status"] != "SCHEDULED":
        raise ApiError("ERR_TAKEBACK_NOT_SCHEDULED")

    delivery["waiver_reference"] = body["waiver_reference"]
    delivery["units_takeback_collected"] = 0
    delivery["breach_units"] = 0
    delivery["breach_penalty_cents"] = 0
    delivery["status"] = "WAIVED"
    touch(delivery)
    return response.obj(public(delivery))
