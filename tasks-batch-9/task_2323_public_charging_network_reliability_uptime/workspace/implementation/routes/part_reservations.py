"""Part reservations: OCC-guarded earmarking, consumption and release
(PRD §2.7, §3.6)."""
from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import clock
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint, current_user_id, require_role_for_leg
from response import array_response, object_response, paginate

bp = Blueprint("part_reservations", __name__)

DISPOSITION_ACTIONS = ("CONSUME", "RELEASE")


@bp.post("/part-reservations")
@endpoint("NetworkOperator")
def create_reservation():
    body = validation.json_body()

    raw_dispatch_id = validation.fk(body, "dispatch_id")
    dispatch = lookup.dispatch(raw_dispatch_id) if raw_dispatch_id is not None else None
    raw_part_id = validation.fk(body, "spare_part_id")
    part = lookup.spare_part(raw_part_id) if raw_part_id is not None else None

    validation.as_string(body, "dispatch_id")
    validation.as_string(body, "spare_part_id")
    qty = validation.as_int(body, "qty")
    expected_version = validation.as_int(body, "expected_spare_part_version")

    if expected_version != part["version"]:
        raise err("ERR_STALE_PARENT_VERSION",
                  "expected_spare_part_version does not match the spare part's version.")

    if qty < 1:
        raise err("ERR_RESERVATION_QTY_INVALID", "qty must be at least 1.")

    unencumbered = calc.unencumbered_qty(part)
    row = db.base_record()
    row.update({
        "dispatch_id": dispatch["id"],
        "spare_part_id": part["id"],
        "qty": qty,
        "state": "RESERVED",
        "expected_available_at": None,
    })
    if qty > unencumbered:
        row["state"] = "BACKORDERED"
        row["expected_available_at"] = clock.now() + timedelta(days=part["lead_time_days"])
    db.reservations[row["id"]] = row
    db.mark_fresh(row)
    db.touch(part)

    return object_response(serialize.part_reservation(row), 201)


@bp.get("/part-reservations")
@endpoint()
def list_reservations():
    limit, offset = validation.pagination()
    rows = db.sort_rows(list(db.reservations.values()))
    rows = validation.apply_filters(rows, validation.filters(
        "dispatch_id", "spare_part_id", "state"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.part_reservation(r) for r in page],
                          limit, offset, total)


@bp.get("/part-reservations/<reservation_id>")
@endpoint()
def get_reservation(reservation_id):
    return object_response(serialize.part_reservation(lookup.reservation(reservation_id)))


@bp.post("/part-reservations/<reservation_id>/disposition")
@endpoint("NetworkOperator", "FieldTechnician")
def dispose_reservation(reservation_id):
    reservation = lookup.reservation(reservation_id)
    body = validation.json_body()
    action = validation.as_enum(body, "action", DISPOSITION_ACTIONS)

    require_role_for_leg("FieldTechnician" if action == "CONSUME" else "NetworkOperator")

    dispatch = db.dispatches.get(reservation["dispatch_id"])
    part = db.spare_parts.get(reservation["spare_part_id"])

    if action == "CONSUME":
        if reservation["state"] != "RESERVED":
            raise err("ERR_INVALID_STATE", "Only a RESERVED reservation may be consumed.")
        if dispatch is None or dispatch["state"] not in ("ON_SITE", "PARTS_HOLD"):
            raise err("ERR_INVALID_STATE",
                      "The owning dispatch must be ON_SITE or PARTS_HOLD.")
        if dispatch["technician_user_id"] != current_user_id():
            raise err("ERR_NOT_ASSIGNED_TECHNICIAN",
                      "Only the assigned technician may consume a reservation.")
        reservation["state"] = "CONSUMED"
        db.touch(reservation)
        if part is not None:
            part["on_hand_qty"] = part["on_hand_qty"] - reservation["qty"]
            db.touch(part)
    else:  # RELEASE
        if reservation["state"] not in ("RESERVED", "BACKORDERED"):
            raise err("ERR_RESERVATION_QTY_INVALID",
                      "The reservation no longer encumbers any stock.")
        cascades.release_reservation(reservation)

    return object_response(serialize.part_reservation(reservation))
