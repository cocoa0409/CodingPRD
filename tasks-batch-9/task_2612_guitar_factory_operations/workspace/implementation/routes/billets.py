"""Billets (PRD 3.3) and immutable component specs (PRD 3.4)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import domain
import validate as v
from constants import (BILLET_STATUSES, COMPONENT_TYPES, GRADES, ROOM_TYPES,
                       SPECIES_CODES)
from envelope import object_response, paginate
from errors import ApiError
from serialize import billet_view, spec_view
from store import BILLETS, LOTS, SPECS, new_record

bp = Blueprint("billets", __name__)


@bp.post("/billets")
def create_billet():
    auth.require(auth.MACHINIST)
    body = v.body()
    billet_code = v.get_str(body, "billet_code", min_len=1, max_len=64)
    lot_id = v.get_id(body, "lot_id")
    board_feet = v.get_dec(body, "board_feet", gt=0, scale=2)
    grade = v.get_enum(body, "grade", GRADES)
    expected = v.get_int(body, "expected_tonewood_lot_version")
    parent_id = v.get_id(body, "parent_billet_id", required=False)

    lot = v.fetch(LOTS, lot_id, "ERR_TONEWOOD_LOT_NOT_FOUND")
    if parent_id is not None:
        v.fetch(BILLETS, parent_id, "ERR_BILLET_NOT_FOUND")
    v.unique_code(BILLETS, "billet_code", billet_code)
    if expected != lot["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "the tonewood lot has moved on since it was read")
    if lot["status"] != "RELEASED":
        raise ApiError("ERR_LOT_NOT_RELEASED",
                       "only a RELEASED lot may be sawn")

    kerf = calc.kerf_for(board_feet)
    if board_feet + kerf > Decimal(lot["board_feet_available"]):
        raise ApiError("ERR_INSUFFICIENT_BOARD_FEET",
                       "the cut would overdraw the lot")

    rec = new_record(BILLETS, {
        "billet_code": billet_code,
        "lot_id": lot_id,
        "parent_billet_id": parent_id,
        "board_feet": calc.bf(board_feet),
        "kerf_loss_board_feet": kerf,
        "moisture_content_pct": lot["moisture_content_pct"],
        "grade": grade,
        "status": "AVAILABLE",
    })
    domain.lot_after_cut(lot, board_feet, kerf)
    return object_response(billet_view(rec), 201)


@bp.get("/billets/<billet_id>")
def read_billet(billet_id):
    auth.require_staff()
    return object_response(billet_view(
        v.fetch(BILLETS, billet_id, "ERR_BILLET_NOT_FOUND")))


@bp.get("/billets")
def list_billets():
    auth.require_staff()
    rows = v.apply_filters(list(BILLETS.values()), [
        ("lot_id", v.filter_value("lot_id")),
        ("parent_billet_id", v.filter_value("parent_billet_id")),
        ("grade", v.filter_enum("grade", GRADES)),
        ("status", v.filter_enum("status", BILLET_STATUSES)),
    ])
    rows.sort(key=lambda r: r["billet_code"])
    return paginate(rows, billet_view)


@bp.post("/component-specs")
def create_spec():
    auth.require(auth.PLANT_ADMIN)
    body = v.body()
    spec_code = v.get_str(body, "spec_code", min_len=1, max_len=64)
    component_type = v.get_enum(body, "component_type", COMPONENT_TYPES)
    species = v.get_code_list(body, "required_species_codes",
                              allowed=SPECIES_CODES)
    min_grade = v.get_enum(body, "min_grade", GRADES)
    nominal = v.get_dec(body, "nominal_board_feet", gt=0)
    thickness = v.get_dec(body, "target_thickness_mm", gt=0, scale=2)
    cnc_minutes = v.get_int(body, "cnc_minutes", minimum=1)
    hand_minutes = v.get_int(body, "hand_shape_minutes", minimum=1)
    tolerance = v.get_dec(body, "thickness_tolerance_mm", required=False, gt=0,
                          default=Decimal("0.15"))
    room_type = v.get_enum(body, "required_room_type",
                           ("BUILD_ROOM", "DRY_STORE"), required=False,
                           default="BUILD_ROOM")
    v.unique_code(SPECS, "spec_code", spec_code)
    rec = new_record(SPECS, {
        "spec_code": spec_code,
        "component_type": component_type,
        "required_species_codes": species,
        "min_grade": min_grade,
        "nominal_board_feet": nominal,
        "target_thickness_mm": thickness,
        "thickness_tolerance_mm": tolerance,
        "cnc_minutes": cnc_minutes,
        "hand_shape_minutes": hand_minutes,
        "required_room_type": room_type,
    }, versioned=False)
    return object_response(spec_view(rec), 201)


@bp.get("/component-specs/<spec_id>")
def read_spec(spec_id):
    auth.require_staff()
    return object_response(spec_view(
        v.fetch(SPECS, spec_id, "ERR_COMPONENT_SPEC_NOT_FOUND")))


@bp.get("/component-specs")
def list_specs():
    auth.require_staff()
    rows = v.apply_filters(list(SPECS.values()), [
        ("component_type", v.filter_enum("component_type", COMPONENT_TYPES)),
        ("min_grade", v.filter_enum("min_grade", GRADES)),
    ])
    rows.sort(key=lambda r: r["spec_code"])
    return paginate(rows, spec_view)
