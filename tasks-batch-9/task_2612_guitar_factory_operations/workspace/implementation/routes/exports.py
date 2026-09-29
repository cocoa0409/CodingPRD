"""Export clearance: the customs declaration and the release gate (PRD 3.9)."""

import re

from flask import Blueprint

import auth
import calc
import validate as v
from constants import SHIPMENT_STATUSES
from envelope import object_response, paginate
from errors import ApiError
from serialize import shipment_view
from store import ORDERS, SHIPMENTS, new_record, touch

bp = Blueprint("exports", __name__)

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
NON_TERMINAL = ("DOCS_PENDING", "DOCS_ATTACHED", "DOCS_REJECTED", "RELEASED")


def _shipment(shipment_id):
    return v.fetch(SHIPMENTS, shipment_id, "ERR_EXPORT_SHIPMENT_NOT_FOUND")


def _price(shipment, order):
    """Steps one to five of the declaration, re-run on every attach."""
    goods = order.get("binding_quote_total_cents") or 0
    doc_fee, insurance, declared = calc.price_declaration(
        goods, shipment["cites_permit_required"])
    shipment["goods_value_cents"] = goods
    shipment["doc_fee_cents"] = doc_fee
    shipment["insurance_cents"] = insurance
    shipment["declared_value_cents"] = declared


@bp.post("/export-shipments")
def create_shipment():
    auth.require(auth.COMPLIANCE_OFFICER)
    body = v.body()
    order_id = v.get_id(body, "build_order_id")
    destination = v.get_str(body, "destination_country_code", min_len=2,
                            max_len=2)
    if not COUNTRY_RE.match(destination):
        v.bad("destination_country_code must be two uppercase letters")
    order = v.fetch(ORDERS, order_id, "ERR_BUILD_ORDER_NOT_FOUND")
    open_file = [s for s in SHIPMENTS.values()
                 if s["build_order_id"] == order["id"]
                 and s["status"] in NON_TERMINAL]
    if open_file:
        raise ApiError("ERR_DUPLICATE_CODE",
                       "an export file is already open for this instrument")
    rec = new_record(SHIPMENTS, {
        "build_order_id": order["id"],
        "destination_country_code": destination,
        "cites_permit_required": order["cites_permit_required"],
        "required_cites_appendix": order["strictest_cites_appendix"],
        "cites_permit_number": None,
        "goods_value_cents": 0,
        "doc_fee_cents": 0,
        "insurance_cents": 0,
        "declared_value_cents": 0,
        "released_by_user_id": None,
        "status": "DOCS_PENDING",
    })
    _price(rec, order)
    return object_response(shipment_view(rec), 201)


@bp.get("/export-shipments/<shipment_id>")
def read_shipment(shipment_id):
    auth.require_staff()
    return object_response(shipment_view(_shipment(shipment_id)))


@bp.get("/export-shipments")
def list_shipments():
    auth.require_staff()
    rows = v.apply_filters(list(SHIPMENTS.values()), [
        ("build_order_id", v.filter_value("build_order_id")),
        ("destination_country_code", v.filter_value(
            "destination_country_code")),
        ("status", v.filter_enum("status", SHIPMENT_STATUSES)),
        ("cites_permit_required", v.filter_bool("cites_permit_required")),
    ])
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows, shipment_view)


@bp.post("/export-shipments/<shipment_id>/attach-docs")
def attach_docs(shipment_id):
    auth.require(auth.COMPLIANCE_OFFICER)
    body = v.body()
    permit = v.get_str(body, "cites_permit_number", required=False, min_len=1,
                       max_len=40)
    rec = _shipment(shipment_id)
    if rec["status"] not in ("DOCS_PENDING", "DOCS_REJECTED"):
        raise ApiError("ERR_SHIPMENT_STATE_INVALID",
                       "documents attach from DOCS_PENDING or DOCS_REJECTED")
    if rec["cites_permit_required"] and permit is None:
        raise ApiError("ERR_CITES_PERMIT_MISSING",
                       "this shipment needs a re-export permit number")
    if permit is not None:
        rec["cites_permit_number"] = permit
    order = ORDERS.get(rec["build_order_id"])
    if order is not None:
        _price(rec, order)
    rec["status"] = "DOCS_ATTACHED"
    touch(rec)
    return object_response(shipment_view(rec))


@bp.post("/export-shipments/<shipment_id>/reject-docs")
def reject_docs(shipment_id):
    auth.require(auth.COMPLIANCE_OFFICER)
    body = v.body()
    v.get_str(body, "reason", min_len=1)
    rec = _shipment(shipment_id)
    if rec["status"] != "DOCS_ATTACHED":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID",
                       "only an attached file may be rejected")
    rec["status"] = "DOCS_REJECTED"
    touch(rec)
    return object_response(shipment_view(rec))


@bp.post("/export-shipments/<shipment_id>/release")
def release_shipment(shipment_id):
    user_id, _role = auth.require(auth.COMPLIANCE_OFFICER)
    rec = _shipment(shipment_id)
    if rec["status"] != "DOCS_ATTACHED":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID",
                       "only an attached file may be released")
    order = ORDERS.get(rec["build_order_id"])
    if order is None or order["build_stage"] != "SERIALIZED":
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "an unfinished instrument cannot be exported")
    lots = calc.contributing_lots(order)
    for lot in lots:
        if lot["cites_appendix"] == "NONE":
            continue
        if lot["permit_status"] != "VERIFIED" or lot["status"] != "RELEASED":
            raise ApiError("ERR_CITES_PERMIT_UNVERIFIED",
                           "a contributing lot's permit is not verified")
    for lot in lots:
        if lot["attested_by_user_id"] is not None \
                and lot["attested_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the attesting officer may not release the wood")
    if order["deposit_applied_cents"] < calc.min_settle_cents(order):
        raise ApiError("ERR_DEPOSIT_INSUFFICIENT",
                       "the settlement is below twenty percent of the quote")
    rec["status"] = "RELEASED"
    rec["released_by_user_id"] = user_id
    touch(rec)
    if order["commercial_status"] == "INVOICED":
        order["commercial_status"] = "CLOSED"
        touch(order)
    return object_response(shipment_view(rec))


@bp.post("/export-shipments/<shipment_id>/depart")
def depart_shipment(shipment_id):
    auth.require(auth.COMPLIANCE_OFFICER)
    rec = _shipment(shipment_id)
    if rec["status"] != "RELEASED":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID",
                       "only a released shipment may depart")
    rec["status"] = "EXPORTED"
    touch(rec)
    return object_response(shipment_view(rec))
