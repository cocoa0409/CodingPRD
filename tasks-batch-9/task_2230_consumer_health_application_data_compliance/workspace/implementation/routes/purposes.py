"""Processing purposes and their consent posture (PRD 3.2)."""

from flask import Blueprint

import db
import response
import validators as V
from errors import fail
from middleware import STAFF, require
from routes.common import filter_rows, load
from validators import F, parse

bp = Blueprint("purposes", __name__, url_prefix="/health-data/processing-purposes")

TABLE = "processing_purposes"

SEPARATE_CONSENT_KINDS = ("ADVERTISING", "RESEARCH", "SALE")
DISCLOSURE_ACTIVITIES = ("SHARE", "SELL")


def derive_purpose(purpose_kind, activity_kind):
    """consent_posture_derivation STEP 1."""
    return {
        "consent_axis": activity_kind,
        "requires_separate_consent": (activity_kind in DISCLOSURE_ACTIVITIES
                                      or purpose_kind in SEPARATE_CONSENT_KINDS),
        "third_party_disclosure_required": activity_kind in DISCLOSURE_ACTIVITIES,
    }


@bp.post("")
def create_purpose():
    require("DataSteward")
    body = parse("ProcessingPurpose", {
        "app_product_id": F("string"),
        "purpose_key": F("string"),
        "description_text": F("string"),
        "purpose_kind": F("enum", members=V.PURPOSE_KINDS),
        "activity_kind": F("enum", members=V.ACTIVITY_KINDS),
    })
    product = load("app_products", body["app_product_id"])

    for other in db.rows_of(TABLE):
        if other.get("app_product_id") == product["id"] \
                and other.get("purpose_key") == body["purpose_key"]:
            fail("ERR_DUPLICATE_PURPOSE_KEY")

    fields = {
        "app_product_id": product["id"],
        "purpose_key": body["purpose_key"],
        "description_text": body["description_text"],
        "purpose_kind": body["purpose_kind"],
        "activity_kind": body["activity_kind"],
    }
    fields.update(derive_purpose(body["purpose_kind"], body["activity_kind"]))
    row = db.new_row(TABLE, fields)
    return response.created(db.serialize(row))


@bp.get("")
def list_purposes():
    require(STAFF)
    rows = filter_rows(TABLE, {"app_product_id": "app_product_id",
                               "activity_kind": "activity_kind"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_purpose(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))
