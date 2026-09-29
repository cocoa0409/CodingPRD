"""Depot spare parts and restocking with backorder promotion (PRD §3.6)."""
from flask import Blueprint

import calc
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint
from response import array_response, object_response, paginate

bp = Blueprint("spare_parts", __name__)

PART_CLASSES = ("DISPENSER", "POWER_MODULE", "CABLE_ASSEMBLY", "PAYMENT_TERMINAL")


@bp.post("/spare-parts")
@endpoint("NetworkOperator")
def create_spare_part():
    body = validation.json_body()
    part_number = validation.as_string(body, "part_number")
    part_class = validation.as_enum(body, "part_class", PART_CLASSES)
    lead_time_days = validation.as_int(body, "lead_time_days", minimum=0)

    for existing in db.spare_parts.values():
        if existing["part_number"] == part_number:
            raise err("ERR_PART_NUMBER_DUPLICATE", "part_number is already registered.")

    row = db.base_record()
    row.update({
        "part_number": part_number,
        "part_class": part_class,
        "on_hand_qty": 0,
        "lead_time_days": lead_time_days,
    })
    db.spare_parts[row["id"]] = row
    db.mark_fresh(row)
    return object_response(serialize.spare_part(row), 201)


@bp.get("/spare-parts")
@endpoint()
def list_spare_parts():
    limit, offset = validation.pagination()
    rows = db.sort_rows(list(db.spare_parts.values()))
    rows = validation.apply_filters(rows, validation.filters("part_class"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.spare_part(r) for r in page], limit, offset, total)


@bp.get("/spare-parts/<spare_part_id>")
@endpoint()
def get_spare_part(spare_part_id):
    return object_response(serialize.spare_part(lookup.spare_part(spare_part_id)))


@bp.post("/spare-parts/<spare_part_id>/restock")
@endpoint("NetworkOperator")
def restock(spare_part_id):
    part = lookup.spare_part(spare_part_id)
    body = validation.json_body()
    qty = validation.as_int(body, "qty", minimum=1)

    part["on_hand_qty"] = part["on_hand_qty"] + qty
    db.touch(part)

    # Promote backordered reservations oldest first, stopping at the first one the
    # newly available stock does not cover.
    available = calc.unencumbered_qty(part)
    for reservation in db.reservations_of_part(part["id"]):
        if reservation["state"] != "BACKORDERED":
            continue
        if reservation["qty"] > available:
            break
        reservation["state"] = "RESERVED"
        reservation["expected_available_at"] = None
        db.touch(reservation)
        available -= reservation["qty"]

    return object_response(serialize.spare_part(part))
