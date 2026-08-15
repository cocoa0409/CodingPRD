"""MeasurementSheet endpoints."""

from flask import Blueprint, request

import db
import errors
import util
from middleware import require_roles
from response import success_object, success_list, now_iso
from services import domain, calculations as calc

bp = Blueprint("measurement_sheets", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")


@bp.post("/lofts/boats/<boatId>/measurement-sheets")
def create_sheet(boatId):
    user_id, _ = require_roles("Measurer")
    boat = domain.get_boat_or_404(boatId)
    body = util.get_body()
    i_h = util.as_number(util.require_field(body, "i_height_m"), "i_height_m")
    j_b = util.as_number(util.require_field(body, "j_base_m"), "j_base_m")
    p_m = util.as_number(util.require_field(body, "p_main_m"), "p_main_m")
    e_m = util.as_number(util.require_field(body, "e_main_m"), "e_main_m")
    sheet = util.stamp_new({
        "boat_id": boat["id"],
        "captured_by_measurer_id": user_id,
        "i_height_m": i_h,
        "j_base_m": j_b,
        "p_main_m": p_m,
        "e_main_m": e_m,
        "measured_area_sqm": None,
        "sheet_status": "DRAFT",
        "frozen_at": None,
    })
    db.measurement_sheets[sheet["id"]] = sheet
    return success_object(domain.serialize(sheet), 201)


@bp.get("/lofts/boats/<boatId>/measurement-sheets")
def list_boat_sheets(boatId):
    require_roles(*READ_ROLES)
    domain.get_boat_or_404(boatId)
    limit, offset = util.pagination_params()
    items = [s for s in db.measurement_sheets.values() if s["boat_id"] == boatId]
    items = util.filter_exact(items, "sheet_status", request.args.get("sheet_status"))
    items = util.sort_by_created(items)
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(s) for s in page], limit, offset, total)


@bp.get("/lofts/measurement-sheets")
def list_sheets():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.measurement_sheets.values()))
    items = util.filter_exact(items, "boat_id", request.args.get("boat_id"))
    items = util.filter_exact(items, "sheet_status", request.args.get("sheet_status"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(s) for s in page], limit, offset, total)


@bp.get("/lofts/measurement-sheets/<sheetId>")
def get_sheet(sheetId):
    require_roles(*READ_ROLES)
    sheet = domain.get_sheet_or_404(sheetId)
    return success_object(domain.serialize(sheet))


@bp.post("/lofts/boats/<boatId>/measurement-sheets/<sheetId>/freeze")
def freeze_sheet(boatId, sheetId):
    require_roles("Measurer")
    boat = domain.get_boat_or_404(boatId)
    sheet = domain.get_sheet_or_404(sheetId)
    domain.check_child_of(sheet, "boat_id", boat["id"])
    if sheet["sheet_status"] != "DRAFT":
        raise errors.invalid_state(f"Sheet must be DRAFT to freeze (is {sheet['sheet_status']})")
    for fname in ("i_height_m", "j_base_m", "p_main_m", "e_main_m"):
        v = sheet.get(fname)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise errors.invalid_measurement(f"{fname} must be a positive number at freeze time")
    area = calc.sail_area(sheet["i_height_m"], sheet["j_base_m"], sheet["p_main_m"], sheet["e_main_m"])
    sheet["measured_area_sqm"] = area
    sheet["sheet_status"] = "FROZEN"
    sheet["frozen_at"] = now_iso()
    util.touch(sheet)
    domain.supersede_frozen_sheet(boat, sheet)
    return success_object(domain.serialize(sheet))
