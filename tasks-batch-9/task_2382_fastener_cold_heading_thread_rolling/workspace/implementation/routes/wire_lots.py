"""Drawn wire lots (PRD 3.2)."""

from flask import Blueprint, g

import enums
from db import db, new_record, sorted_records, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok, ok_list
from services import calc
from services.lookup import steel_heat_or_404, wire_lot_or_404
from validate import (
    field_int,
    field_num,
    field_enum,
    field_str,
    paginate,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("wire_lots", __name__)

CREATE_ROLES = ("ProcessEngineer", "PlantAdmin")


@bp.post("/wire-lots")
@endpoint(CREATE_ROLES)
def create_wire_lot():
    body = g.body
    steel_heat_id = field_str(body, "steel_heat_id")
    draw_pass_count = field_int(body, "draw_pass_count", minimum=1)
    inlet = field_num(body, "inlet_diameter_mm", exclusive_min=0)
    outlet = field_num(body, "outlet_diameter_mm", exclusive_min=0)
    lubricant_coating = field_enum(body, "lubricant_coating", enums.LUBRICANT_COATINGS)
    coating_weight_gsm = field_num(body, "coating_weight_gsm", minimum=0)
    gross_mass_kg = field_num(body, "gross_mass_kg", exclusive_min=0)
    if outlet >= inlet:
        raise ApiError(
            "ERR_VALIDATION", "outlet_diameter_mm must be smaller than inlet_diameter_mm."
        )

    steel_heat_or_404(steel_heat_id)

    wire = new_record(
        {
            "steel_heat_id": steel_heat_id,
            "draw_pass_count": draw_pass_count,
            "inlet_diameter_mm": inlet,
            "outlet_diameter_mm": outlet,
            "reduction_pct": calc.reduction_pct(inlet, outlet),
            "lubricant_coating": lubricant_coating,
            "coating_weight_gsm": coating_weight_gsm,
            "gross_mass_kg": gross_mass_kg,
            "available_mass_kg": gross_mass_kg,
            "reserved_mass_kg": calc.D(0),
            "consumed_mass_kg": calc.D(0),
            "status": "DRAWN",
            "quarantine_source": "NONE",
            "inspected_at": None,
        }
    )
    db.wire_lots[wire["id"]] = wire
    return created(wire)


@bp.get("/wire-lots/<wire_lot_id>")
@endpoint(ANY_ROLE)
def get_wire_lot(wire_lot_id):
    return ok(wire_lot_or_404(wire_lot_id))


@bp.get("/wire-lots")
@endpoint(ANY_ROLE)
def list_wire_lots():
    limit, offset = pagination()
    steel_heat_id = query_str("steel_heat_id")
    status = query_enum("status", enums.WIRE_LOT_STATUSES)

    records = sorted_records(db.wire_lots.values())
    if steel_heat_id is not None:
        records = [r for r in records if r["steel_heat_id"] == steel_heat_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/wire-lots/<wire_lot_id>/release")
@endpoint("QualityInspector")
def release_wire_lot(wire_lot_id):
    wire = wire_lot_or_404(wire_lot_id)

    if wire["status"] != "DRAWN":
        raise ApiError("ERR_INVALID_WIRE_LOT_STATE")

    heat = db.steel_heats.get(wire["steel_heat_id"])
    if heat is None or heat["cert_status"] != "VERIFIED":
        raise ApiError("ERR_STEEL_HEAT_NOT_VERIFIED")

    if (
        wire["lubricant_coating"] == "NONE"
        or calc.dec(wire["coating_weight_gsm"]) < calc.COATING_WEIGHT_MIN
    ):
        raise ApiError("ERR_LUBRICATION_INSUFFICIENT")

    reduction = calc.dec(wire["reduction_pct"])
    if reduction < calc.REDUCTION_MIN or reduction > calc.REDUCTION_MAX:
        raise ApiError("ERR_DRAW_REDUCTION_OUT_OF_RANGE")

    wire["status"] = "RELEASED"
    wire["inspected_at"] = db.now_iso()
    touch(wire)
    return ok(wire)
