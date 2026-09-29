"""Haul permits, load building, dispatch and delivery (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascade
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("shipping", __name__)


# ---------------------------------------------------------------------------
# HaulPermit
# ---------------------------------------------------------------------------
@bp.post("/haul-permits")
def create_permit():
    auth.require(constants.ROLE_PERMIT_COORDINATOR)
    body = validation.get_body()
    project_id = validation.req_id(body, "project_id")
    permit_number = validation.req_str(body, "permit_number")
    issuing_state = validation.req_str(body, "issuing_state")
    max_width = validation.req_number(body, "max_width_ft", exclusive_min=0)
    max_height = validation.req_number(body, "max_height_ft", exclusive_min=0)
    max_length = validation.req_number(body, "max_length_ft", exclusive_min=0)
    max_weight = validation.req_number(body, "max_gross_weight_lb", exclusive_min=0)
    valid_from = validation.req_datetime(body, "valid_from")
    valid_to = validation.req_datetime(body, "valid_to")
    validation.require_interval(valid_from, valid_to, "valid_from", "valid_to")
    escort_count = validation.req_int(body, "escort_count", minimum=0)

    lookup.project(project_id)
    for existing in db.store.haul_permits.values():
        if existing["permit_number"] == permit_number:
            errors.fail(errors.ERR_DUPLICATE_RESOURCE_CODE,
                        "permit_number %s is already registered." % permit_number)

    row = db.new_row(db.store.haul_permits, {
        "project_id": project_id,
        "permit_number": permit_number,
        "issuing_state": issuing_state,
        "max_width_ft": max_width,
        "max_height_ft": max_height,
        "max_length_ft": max_length,
        "max_gross_weight_lb": max_weight,
        "valid_from": db.iso_millis(valid_from),
        "valid_to": db.iso_millis(valid_to),
        "escort_count": escort_count,
        "status": "APPLIED",
    })
    db.mark_fresh(row)
    return response.object_response(serialize.haul_permit(row), 201)


@bp.get("/haul-permits/<permit_id>")
def get_permit(permit_id):
    auth.require_any()
    row = lookup.haul_permit(permit_id)
    return response.object_response(serialize.haul_permit(row), 200)


@bp.get("/haul-permits")
def list_permits():
    auth.require_any()
    project_id = validation.query_filter("project_id")
    status = validation.query_filter("status")
    rows = [p for p in db.store.haul_permits.values()
            if (project_id is None or p["project_id"] == project_id)
            and (status is None or p["status"] == status)]
    return listing.list_response(rows, serialize.haul_permit)


@bp.post("/haul-permits/<permit_id>/issue")
def issue_permit(permit_id):
    auth.require(constants.ROLE_PERMIT_COORDINATOR)
    permit = lookup.haul_permit(permit_id)
    if permit["status"] != "APPLIED":
        errors.fail(errors.ERR_HAUL_PERMIT_INVALID_STATE,
                    "Only an APPLIED permit may be issued.")
    permit["status"] = "ISSUED"
    db.touch(permit)
    return response.object_response(serialize.haul_permit(permit), 200)


# ---------------------------------------------------------------------------
# Shipment
# ---------------------------------------------------------------------------
@bp.post("/shipments")
def create_shipment():
    auth.require(constants.ROLE_YARD_FOREMAN)
    body = validation.get_body()
    project_id = validation.req_id(body, "project_id")
    departure = validation.req_datetime(body, "scheduled_departure")
    permit_id = validation.opt_id(body, "haul_permit_id")

    lookup.project(project_id)
    if permit_id is not None:
        lookup.haul_permit(permit_id)

    row = db.new_row(db.store.shipments, {
        "project_id": project_id,
        "haul_permit_id": permit_id,
        "scheduled_departure": db.iso_millis(departure),
        "status": "BUILDING",
        "dispatched_at": None,
    })
    db.mark_fresh(row)
    return response.object_response(serialize.shipment(row), 201)


@bp.get("/shipments/<shipment_id>")
def get_shipment(shipment_id):
    auth.require_any()
    row = lookup.shipment(shipment_id)
    return response.object_response(serialize.shipment(row), 200)


@bp.get("/shipments")
def list_shipments():
    auth.require_any()
    project_id = validation.query_filter("project_id")
    permit_id = validation.query_filter("haul_permit_id")
    status = validation.query_filter("status")
    rows = [s for s in db.store.shipments.values()
            if (project_id is None or s["project_id"] == project_id)
            and (permit_id is None or s["haul_permit_id"] == permit_id)
            and (status is None or s["status"] == status)]
    return listing.list_response(rows, serialize.shipment)


@bp.post("/shipments/<shipment_id>/lines")
def add_line(shipment_id):
    auth.require(constants.ROLE_YARD_FOREMAN)
    shipment = lookup.shipment(shipment_id)
    body = validation.get_body()
    piece_id = validation.req_id(body, "piece_id")
    load_position = validation.req_int(body, "load_position", minimum=1)
    piece = lookup.piece(piece_id)

    if shipment["status"] != "BUILDING":
        errors.fail(errors.ERR_SHIPMENT_INVALID_STATE,
                    "Lines may only be added to a BUILDING shipment.")
    if piece["production_status"] != "YARDED":
        errors.fail(errors.ERR_PIECE_INVALID_STATE,
                    "Only a YARDED piece may be loaded.")
    if piece["qc_status"] not in ("CLEARED", "REPAIRED"):
        errors.fail(errors.ERR_PIECE_QC_HOLD,
                    "The piece is not cleared for shipping.")
    for line in calc.shipment_lines(shipment["id"]):
        if line["load_position"] == load_position:
            errors.fail(errors.ERR_DUPLICATE_LOAD_POSITION,
                        "load_position %d is already used on this shipment."
                        % load_position)
    if piece["project_id"] != shipment["project_id"]:
        errors.fail(errors.ERR_PIECE_PROJECT_MISMATCH,
                    "The piece belongs to another project.")

    row = db.new_row(db.store.shipment_lines, {
        "shipment_id": shipment["id"],
        "piece_id": piece_id,
        "load_position": load_position,
        "loaded_at": db.store.now_iso(),
    }, versioned=False)
    db.mark_fresh(row)

    piece["production_status"] = "LOADED"
    db.touch(piece)
    placement = cascade.active_placement_of(piece["id"])
    if placement is not None:
        cascade.release_placement(placement, "LOAD")
    db.touch(shipment)
    return response.object_response(serialize.shipment_line(row), 201)


@bp.get("/shipments/<shipment_id>/lines")
def list_lines(shipment_id):
    auth.require_any()
    lookup.shipment(shipment_id)
    rows = [l for l in db.store.shipment_lines.values()
            if l["shipment_id"] == shipment_id]
    return listing.list_response(rows, serialize.shipment_line)


@bp.post("/shipments/<shipment_id>/dispatch")
def dispatch(shipment_id):
    auth.require(constants.ROLE_YARD_FOREMAN)
    shipment = lookup.shipment(shipment_id)

    if shipment["status"] != "BUILDING":
        errors.fail(errors.ERR_SHIPMENT_INVALID_STATE,
                    "Only a BUILDING shipment may be dispatched.")

    metrics = calc.shipment_metrics(shipment)
    permit = None
    if shipment["haul_permit_id"]:
        permit = db.store.haul_permits.get(shipment["haul_permit_id"])

    # step 9 - the permit linked to an oversize load must be ISSUED
    if metrics["is_oversize"] and permit is not None and permit["status"] != "ISSUED":
        errors.fail(errors.ERR_PERMIT_NOT_ISSUED,
                    "The linked permit is not ISSUED.")

    # step 12 - the logical clock must lie inside the permit's window
    if metrics["is_oversize"] and permit is not None:
        now = db.store.now()
        valid_from = db.parse_iso8601(permit["valid_from"])
        valid_to = db.parse_iso8601(permit["valid_to"])
        if now > valid_to:
            permit["status"] = "EXPIRED"
            db.touch(permit)
            errors.fail(errors.ERR_PERMIT_EXPIRED, "The permit has expired.")
        if now < valid_from:
            errors.fail(errors.ERR_PERMIT_EXPIRED,
                        "The permit window has not opened yet.")

    # step 15 - load composition
    lines = calc.shipment_lines(shipment["id"])
    if len(lines) == 0:
        errors.fail(errors.ERR_EMPTY_LOAD, "The shipment carries no lines.")
    previous = None
    for line in lines:
        piece = db.store.pieces.get(line["piece_id"])
        sequence = piece["erection_sequence_no"] if piece else 0
        if previous is not None and not sequence < previous:
            errors.fail(errors.ERR_ERECTION_SEQUENCE_VIOLATION,
                        "Lines must carry strictly descending erection_sequence_no.")
        previous = sequence

    # step 16 - permit envelope
    if metrics["is_oversize"]:
        if permit is None:
            errors.fail(errors.ERR_PERMIT_REQUIRED,
                        "An oversize load requires a haul permit.")
        if (metrics["max_width_ft"] > Decimal(permit["max_width_ft"])
                or metrics["max_height_ft"] > Decimal(permit["max_height_ft"])
                or metrics["max_length_ft"] > Decimal(permit["max_length_ft"])):
            errors.fail(errors.ERR_PERMIT_ENVELOPE_EXCEEDED,
                        "The load exceeds the permit's dimensional envelope.")
        if metrics["gross_weight_lb"] > Decimal(permit["max_gross_weight_lb"]):
            errors.fail(errors.ERR_PERMIT_WEIGHT_EXCEEDED,
                        "The load exceeds the permit's gross weight.")

    shipment["status"] = "DISPATCHED"
    shipment["dispatched_at"] = db.store.now_iso()
    db.touch(shipment)
    if permit is not None and permit["status"] == "ISSUED":
        permit["status"] = "ACTIVE"
        db.touch(permit)
    return response.object_response(serialize.shipment(shipment), 200)


@bp.post("/shipments/<shipment_id>/deliver")
def deliver(shipment_id):
    auth.require(constants.ROLE_YARD_FOREMAN)
    shipment = lookup.shipment(shipment_id)
    if shipment["status"] != "DISPATCHED":
        errors.fail(errors.ERR_SHIPMENT_INVALID_STATE,
                    "Only a DISPATCHED shipment may be delivered.")

    shipment["status"] = "DELIVERED"
    db.touch(shipment)
    for line in calc.shipment_lines(shipment["id"]):
        piece = db.store.pieces.get(line["piece_id"])
        if piece is not None and piece["production_status"] == "LOADED":
            piece["production_status"] = "SHIPPED"
            db.touch(piece)
    if shipment["haul_permit_id"]:
        permit = db.store.haul_permits.get(shipment["haul_permit_id"])
        if permit is not None and permit["status"] == "ACTIVE":
            permit["status"] = "CONSUMED"
            db.touch(permit)
    return response.object_response(serialize.shipment(shipment), 200)
