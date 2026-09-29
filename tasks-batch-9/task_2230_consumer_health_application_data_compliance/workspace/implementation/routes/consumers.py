"""Consumers (PRD 3.5, 3.6)."""

import uuid

from flask import Blueprint

import db
import response
import validators as V
from errors import fail
from middleware import STAFF, STAFF_AND_CONSUMER, require
from routes.common import filter_rows, load
from validators import F, parse

bp = Blueprint("consumers", __name__, url_prefix="/health-data/consumers")

TABLE = "consumers"


def mint_token():
    return "vtok_" + uuid.uuid4().hex


@bp.post("")
def create_consumer():
    require("PlatformAdmin")
    body = parse("Consumer", {
        "app_product_id": F("string"),
        "external_ref": F("string"),
        "residency_state_code": F("enum", members=V.STATE_CODES),
        "age_band": F("enum", members=V.AGE_BANDS),
    })
    product = load("app_products", body["app_product_id"])

    for other in db.rows_of(TABLE):
        if other.get("app_product_id") == product["id"] \
                and other.get("external_ref") == body["external_ref"]:
            fail("ERR_DUPLICATE_CONSUMER_REF")

    row = db.new_row(TABLE, {
        "app_product_id": product["id"],
        "external_ref": body["external_ref"],
        "residency_state_code": body["residency_state_code"],
        "age_band": body["age_band"],
        "verification_token": mint_token(),
        "deletion_completed_count": 0,
    })
    return response.created(db.serialize(row))


@bp.get("")
def list_consumers():
    require(STAFF)
    rows = filter_rows(TABLE, {"app_product_id": "app_product_id"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_consumer(row_id):
    require(STAFF_AND_CONSUMER)
    return response.ok(db.serialize(load(TABLE, row_id)))
