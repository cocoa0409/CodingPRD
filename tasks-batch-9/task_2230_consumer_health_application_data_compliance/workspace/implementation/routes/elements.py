"""Data elements and their CHD classification (PRD 3.2)."""

from flask import Blueprint

import db
import response
import validators as V
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services import posture
from services.calc import derivation_hops, reclassify_product
from services.cascade import reinstate_element, retire_element
from validators import F, no_body, parse, supplied

bp = Blueprint("elements", __name__, url_prefix="/health-data/data-elements")

TABLE = "data_elements"

_CREATE = {
    "app_product_id": F("string"),
    "element_key": F("string"),
    "display_name": F("string"),
    "source_kind": F("enum", members=V.SOURCE_KINDS),
    "health_signal_kind": F("enum", members=V.HEALTH_SIGNAL_KINDS),
    "derived_from_element_id": F("string", required=False, nullable=True),
    "hipaa_flow_only": F("bool", required=False),
}

_PATCH = {
    "display_name": F("string", required=False),
    "source_kind": F("enum", required=False, members=V.SOURCE_KINDS),
    "health_signal_kind": F("enum", required=False, members=V.HEALTH_SIGNAL_KINDS),
    "derived_from_element_id": F("string", required=False, nullable=True),
    "hipaa_flow_only": F("bool", required=False),
}


def _derivation_consistent(source_kind, parent_id):
    """Precedence check 19."""
    if source_kind == "DERIVED_INFERENCE" and parent_id is None:
        fail("ERR_DERIVATION_SOURCE_REQUIRED")
    if parent_id is not None and source_kind != "DERIVED_INFERENCE":
        fail("ERR_DERIVATION_SOURCE_REQUIRED")


@bp.post("")
def create_element():
    require("DataSteward")
    body = parse("DataElement", _CREATE)

    # check 5: foreign keys in declared order.
    product = load("app_products", body["app_product_id"])
    parent_id = body.get("derived_from_element_id")
    parent = load(TABLE, parent_id) if parent_id is not None else None

    # check 6: same-product references only.
    if parent is not None and parent.get("app_product_id") != product["id"]:
        fail("ERR_CROSS_PRODUCT_REFERENCE")

    # check 17: element_key uniqueness across ACTIVE and RETIRED rows.
    for other in db.rows_of(TABLE):
        if other.get("app_product_id") == product["id"] \
                and other.get("element_key") == body["element_key"] \
                and other.get("status") in ("ACTIVE", "RETIRED"):
            fail("ERR_DUPLICATE_ELEMENT_KEY")

    # checks 19, 20, 21.
    _derivation_consistent(body["source_kind"], parent_id)
    depth = derivation_hops(parent_id)

    row = db.new_row(TABLE, {
        "app_product_id": product["id"],
        "element_key": body["element_key"],
        "display_name": body["display_name"],
        "source_kind": body["source_kind"],
        "health_signal_kind": body["health_signal_kind"],
        "derived_from_element_id": parent_id,
        "hipaa_flow_only": bool(body.get("hipaa_flow_only", False)),
        "inference_depth": depth,
        "chd_classification": "NON_CHD",
        "status": "ACTIVE",
        "retired_reason": None,
    })
    reclassify_product(product["id"])
    posture.recount_elements(product)
    row["version"] = 1
    row["updated_at"] = row["created_at"]
    return response.created(db.serialize(row))


@bp.get("")
def list_elements():
    require(STAFF)
    rows = filter_rows(TABLE, {
        "app_product_id": "app_product_id",
        "derived_from_element_id": "derived_from_element_id",
        "status": "status",
    })
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_element(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.patch("/<row_id>")
def patch_element(row_id):
    require("DataSteward")
    row = load(TABLE, row_id)
    body = supplied("DataElement", _PATCH)

    parent_id = body["derived_from_element_id"] if "derived_from_element_id" in body \
        else row.get("derived_from_element_id")
    if "derived_from_element_id" in body and parent_id is not None:
        load(TABLE, parent_id)

    source_kind = body.get("source_kind", row.get("source_kind"))
    _derivation_consistent(source_kind, parent_id)
    derivation_hops(parent_id, row["id"])

    for key, value in body.items():
        row[key] = value
    db.touch(row)
    reclassify_product(row["app_product_id"])
    posture.recount_regulated_elements(posture.product_of_element(row))
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/retire")
def retire(row_id):
    require("DataSteward")
    row = load(TABLE, row_id)
    body = parse("DataElement", {"retired_reason": F("string")},
                 extra_allowed=("retired_reason",))
    check_state(row, TABLE, ("ACTIVE",), specific="ERR_ELEMENT_RETIRED", field="status")
    retire_element(row, body["retired_reason"])
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/reinstate")
def reinstate(row_id):
    require("DataSteward")
    row = load(TABLE, row_id)
    no_body("DataElement")
    check_state(row, TABLE, ("RETIRED",), field="status")
    parent_id = row.get("derived_from_element_id")
    if parent_id is not None:
        parent = db.get(TABLE, parent_id)
        if parent is None or parent.get("status") != "ACTIVE":
            fail("ERR_ELEMENT_PARENT_RETIRED")
    reinstate_element(row)
    return response.ok(db.serialize(row))
