"""Property identification endpoints (PRD 3.5)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain

bp = Blueprint("identifications", __name__)


def _rows_on_file(exchange_file_id):
    return [r for r in db.sorted_rows(db.identifications)
            if r["exchange_file_id"] == exchange_file_id]


def _active_rows(exchange_file_id):
    return [r for r in _rows_on_file(exchange_file_id) if r["status"] == "ACTIVE"]


@bp.post("/property-identifications")
def create_identification():
    middleware.actor([C.QI])
    payload = middleware.body_or_400()
    exchange_file_id = middleware.req_str(payload, "exchange_file_id")
    property_id = middleware.req_str(payload, "property_id")
    fair_market_value_cents = middleware.req_int(payload, "fair_market_value_cents", 1)

    exchange_file = domain.require("exchange_file", exchange_file_id)
    prop = domain.require("property", property_id)

    if exchange_file["status"] not in ("OPEN", "IDENTIFIED"):
        raise ApiError("ERR_EXCHANGE_FILE_INVALID_STATE")
    now = clock.now()
    if now > exchange_file["identification_deadline"]:
        raise ApiError("ERR_IDENTIFICATION_WINDOW_CLOSED")

    active = _active_rows(exchange_file["id"])
    if not calc.identification_rule_ok(
            exchange_file["identification_rule"],
            [r["fair_market_value_cents"] for r in active],
            fair_market_value_cents,
            exchange_file["relinquished_sale_price_cents"]):
        raise ApiError("ERR_IDENTIFICATION_RULE_VIOLATION")

    for row in active:
        if row["property_id"] == prop["id"]:
            raise ApiError("ERR_DUPLICATE_IDENTIFICATION")

    sequence_no = len(_rows_on_file(exchange_file["id"])) + 1
    row = db.new_row(db.identifications, {
        "exchange_file_id": exchange_file["id"],
        "property_id": prop["id"],
        "fair_market_value_cents": fair_market_value_cents,
        "identified_at": now,
        "sequence_no": sequence_no,
        "status": "ACTIVE",
    })

    if exchange_file["status"] == "OPEN":
        exchange_file["status"] = "IDENTIFIED"
        db.touch(exchange_file)
    return created_response(db.serialize(row))


@bp.get("/property-identifications/<identification_id>")
def get_identification(identification_id):
    return read_one("identification", C.READ_EXCHANGE_SIDE, identification_id)


@bp.get("/property-identifications")
def list_identifications():
    return listing(db.identifications, C.READ_EXCHANGE_SIDE,
                   str_filters=("exchange_file_id", "property_id", "status"))


@bp.post("/property-identifications/<identification_id>/revoke")
def revoke_identification(identification_id):
    middleware.actor([C.QI])
    payload = middleware.body_or_400()
    middleware.opt_str(payload, "reason")

    row = domain.require("identification", identification_id)
    exchange_file = db.exchange_files[row["exchange_file_id"]]

    if row["status"] != "ACTIVE" or exchange_file["status"] != "IDENTIFIED":
        raise ApiError("ERR_IDENTIFICATION_INVALID_STATE")
    if clock.now() > exchange_file["identification_deadline"]:
        raise ApiError("ERR_IDENTIFICATION_WINDOW_CLOSED")

    row["status"] = "REVOKED"
    db.touch(row)
    if not _active_rows(exchange_file["id"]):
        exchange_file["status"] = "OPEN"
        db.touch(exchange_file)
    return object_response(db.serialize(row))
