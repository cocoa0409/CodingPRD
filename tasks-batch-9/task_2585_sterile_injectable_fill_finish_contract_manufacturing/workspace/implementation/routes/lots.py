"""/component-lots and /component-reservations - the component-unit ledger."""

from flask import Blueprint, request

import calc
import serialize
import services
from auth import endpoint
from common import ApiError, clock_now
from listing import list_response, object_response
from store import DB, by_created, new_row, set_raw, touch
from validate import (
    COMPONENT_TYPES,
    STERILIZATION_OUTCOMES,
    f_dt,
    f_enum,
    f_int,
    f_num,
    f_str,
    parse_body,
)

bp = Blueprint("lots", __name__)

LOT_FIELDS = [
    f_str("client_project_id", 1, None),
    f_enum("component_type", COMPONENT_TYPES),
    f_str("lot_code", 1, 30),
    f_int("quantity_received", 1),
    f_dt("sterilization_expiry"),
]


@bp.post("/component-lots")
@endpoint(["ProgramManager"])
def create_lot():
    body = parse_body(request.get_json(silent=True), LOT_FIELDS)
    project = services.require("project", body["client_project_id"])
    for existing in DB.lots.values():
        if (
            existing["component_type"] == body["component_type"]
            and existing["lot_code"] == body["lot_code"]
        ):
            raise services.state_conflict(
                "ERR_DUPLICATE_LOT_CODE",
                "That lot_code is already in use for this component_type.",
            )
    row = new_row(
        {
            "client_project_id": project["id"],
            "component_type": body["component_type"],
            "lot_code": body["lot_code"],
            "quantity_received": body["quantity_received"],
            "quantity_available": 0,
            "sterilization_expiry": body["sterilization_expiry"],
            "sterilization_validation_status": "PENDING",
            "status": "QUARANTINE",
        }
    )
    set_raw(row, "sterilization_expiry", body["_raw_sterilization_expiry"])
    DB.lots[row["id"]] = row
    return object_response(serialize.lot_out(row), 201)


@bp.get("/component-lots/<lot_id>")
@endpoint(
    ["ProgramManager", "MicrobiologyAnalyst", "ProductionSupervisor", "QaReviewer"]
)
def read_lot(lot_id):
    row = services.require("lot", lot_id)
    return object_response(serialize.lot_out(row))


@bp.get("/component-lots")
@endpoint(
    ["ProgramManager", "MicrobiologyAnalyst", "ProductionSupervisor", "QaReviewer"]
)
def list_lots():
    rows = by_created(list(DB.lots.values()))
    return list_response(
        rows,
        serialize.lot_out,
        {
            "client_project_id": "client_project_id",
            "component_type": "component_type",
            "status": "status",
        },
    )


@bp.post("/component-lots/<lot_id>/sterilization-validation")
@endpoint(["MicrobiologyAnalyst"])
def sterilization_validation(lot_id):
    lot = services.require("lot", lot_id)
    body = parse_body(
        request.get_json(silent=True),
        [f_enum("outcome", STERILIZATION_OUTCOMES), f_num("f0_minutes")],
    )
    if lot["sterilization_validation_status"] != "PENDING":
        raise services.state_conflict(
            "ERR_COMPONENT_LOT_STATE_INVALID",
            "This lot has already received a sterilisation verdict.",
        )
    if body["outcome"] == "RELEASED":
        if lot["sterilization_expiry"] is None or lot["sterilization_expiry"] <= clock_now():
            raise services.state_conflict(
                "ERR_COMPONENT_LOT_STATE_INVALID",
                "The sterilisation hold time has already lapsed.",
            )
        lot["sterilization_validation_status"] = "RELEASED"
        lot["status"] = "RELEASED"
        lot["quantity_available"] = lot["quantity_received"]
    else:
        lot["sterilization_validation_status"] = "REJECTED"
        lot["status"] = "REJECTED"
        lot["quantity_available"] = 0
    touch(lot)
    return object_response(serialize.lot_out(lot))


# --------------------------------------------------------------------------
# Reservations
# --------------------------------------------------------------------------

RESERVATION_FIELDS = [
    f_str("batch_order_id", 1, None),
    f_str("component_lot_id", 1, None),
    f_int("quantity_reserved", 1),
    f_int("expected_component_lot_version"),
]


@bp.post("/component-reservations")
@endpoint(["ProgramManager", "ProductionSupervisor"])
def create_reservation():
    body = parse_body(request.get_json(silent=True), RESERVATION_FIELDS)
    batch = services.require("batch", body["batch_order_id"])
    lot = services.require("lot", body["component_lot_id"])
    if body["expected_component_lot_version"] != lot["version"]:
        raise ApiError(
            "ERR_STALE_COMPONENT_LOT_VERSION",
            412,
            "expected_component_lot_version does not match the lot's current version.",
        )
    if lot["status"] != "RELEASED":
        raise services.state_conflict(
            "ERR_COMPONENT_LOT_STATE_INVALID",
            "Only a RELEASED lot can be drawn from.",
        )
    if (
        lot["sterilization_validation_status"] != "RELEASED"
        or lot["sterilization_expiry"] is None
        or lot["sterilization_expiry"] <= clock_now()
        or lot["sterilization_expiry"] < batch["planned_end"]
    ):
        raise services.state_conflict(
            "ERR_COMPONENT_STERILIZATION_INVALID",
            "The lot's sterility does not cover the batch's whole window.",
        )
    project = DB.projects.get(batch["client_project_id"])
    allowed_lines = calc.BILL_OF_COMPONENTS[project["dosage_form"]] if project else ()
    if (
        lot["client_project_id"] != batch["client_project_id"]
        or lot["component_type"] not in allowed_lines
    ):
        raise services.state_conflict(
            "ERR_COMPONENT_LOT_PROJECT_MISMATCH",
            "The lot belongs to another programme or another presentation.",
        )
    if body["quantity_reserved"] > lot["quantity_available"]:
        raise services.state_conflict(
            "ERR_COMPONENT_LOT_INSUFFICIENT",
            "The lot does not hold that many available units.",
        )
    row = new_row(
        {
            "batch_order_id": batch["id"],
            "component_lot_id": lot["id"],
            "quantity_reserved": body["quantity_reserved"],
            "status": "RESERVED",
            "released_reason": None,
        }
    )
    DB.reservations[row["id"]] = row
    services.draw_lot_availability(lot, body["quantity_reserved"])
    return object_response(serialize.reservation_out(row), 201)


@bp.get("/component-reservations/<reservation_id>")
@endpoint(
    ["ProgramManager", "ProductionSupervisor", "QaReviewer", "MicrobiologyAnalyst"]
)
def read_reservation(reservation_id):
    row = services.require("reservation", reservation_id)
    return object_response(serialize.reservation_out(row))


@bp.get("/component-reservations")
@endpoint(
    ["ProgramManager", "ProductionSupervisor", "QaReviewer", "MicrobiologyAnalyst"]
)
def list_reservations():
    rows = by_created(list(DB.reservations.values()))
    return list_response(
        rows,
        serialize.reservation_out,
        {
            "batch_order_id": "batch_order_id",
            "component_lot_id": "component_lot_id",
            "status": "status",
        },
    )
