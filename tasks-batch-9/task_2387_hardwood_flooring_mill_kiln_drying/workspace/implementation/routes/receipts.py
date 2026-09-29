"""The receiving deck: green lumber intake (PRD 3.2)."""

from flask import Blueprint

from db import db, insert, touch
from errors import ApiError
from middleware import ALL_ROLES, MILL_ADMIN, PROCUREMENT_CLERK, authorize
from response import array_response, object_response, paginate
from serializers import serialize, serialize_many
from services import lookup
from validation import (body_json, pagination, query_enum, query_str, req_decimal,
                        req_enum, req_int, req_ref, req_str)

bp = Blueprint("receipts", __name__)

RECEIPT_GRADES = ("FAS", "SELECT", "NO1_COMMON", "NO2_COMMON")
RECEIPT_STATUSES = ("RECEIVED", "ACCEPTED", "ALLOCATED", "CONSUMED", "REJECTED")


@bp.post("/mill/green-receipts")
@authorize(PROCUREMENT_CLERK, MILL_ADMIN)
def create_green_receipt():
    body = body_json()
    species_profile_id = req_ref(body, "species_profile_id")
    supplier_name = req_str(body, "supplier_name")
    received_board_feet = req_int(body, "received_board_feet")
    receipt_grade = req_enum(body, "receipt_grade", RECEIPT_GRADES)
    moisture_pct_at_receipt = req_decimal(body, "moisture_pct_at_receipt")

    lookup.species_profile(species_profile_id)

    record = insert(db.green_receipts, {
        "species_profile_id": species_profile_id,
        "supplier_name": supplier_name,
        "received_board_feet": received_board_feet,
        "receipt_grade": receipt_grade,
        "moisture_pct_at_receipt": moisture_pct_at_receipt,
        "accepted_board_feet": 0,
        "kiln_charge_id": None,
        "rejection_reason": None,
        "status": "RECEIVED",
    })
    return object_response(serialize("green_receipt", record), 201)


@bp.get("/mill/green-receipts/<green_receipt_id>")
@authorize(*ALL_ROLES)
def get_green_receipt(green_receipt_id):
    return object_response(serialize("green_receipt", lookup.green_receipt(green_receipt_id)))


@bp.get("/mill/green-receipts")
@authorize(*ALL_ROLES)
def list_green_receipts():
    limit, offset = pagination()
    species_profile_id = query_str("species_profile_id")
    kiln_charge_id = query_str("kiln_charge_id")
    status = query_enum("status", RECEIPT_STATUSES)
    rows = lookup.filtered(db.green_receipts, [
        ("species_profile_id", species_profile_id),
        ("kiln_charge_id", kiln_charge_id),
        ("status", status),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("green_receipt", page), limit, offset, total)


@bp.post("/mill/green-receipts/<green_receipt_id>/accept")
@authorize(PROCUREMENT_CLERK, MILL_ADMIN)
def accept_green_receipt(green_receipt_id):
    body = body_json()
    accepted_board_feet = req_int(body, "accepted_board_feet")
    receipt = lookup.green_receipt(green_receipt_id)

    if receipt["status"] != "RECEIVED":
        raise ApiError("ERR_RECEIPT_STATE_INVALID")
    if accepted_board_feet > int(receipt["received_board_feet"]):
        raise ApiError("ERR_ACCEPTED_BF_EXCEEDS_RECEIVED")

    receipt["accepted_board_feet"] = accepted_board_feet
    receipt["status"] = "ACCEPTED"
    touch(receipt)
    return object_response(serialize("green_receipt", receipt))


@bp.post("/mill/green-receipts/<green_receipt_id>/reject")
@authorize(PROCUREMENT_CLERK, MILL_ADMIN)
def reject_green_receipt(green_receipt_id):
    body = body_json()
    rejection_reason = req_str(body, "rejection_reason")
    receipt = lookup.green_receipt(green_receipt_id)

    if receipt["status"] != "RECEIVED":
        raise ApiError("ERR_RECEIPT_STATE_INVALID")

    receipt["rejection_reason"] = rejection_reason
    receipt["accepted_board_feet"] = 0
    receipt["status"] = "REJECTED"
    touch(receipt)
    return object_response(serialize("green_receipt", receipt))
