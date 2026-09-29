"""Disposal records: the final entry in a unit's history (PRD 3.9)."""

from flask import Blueprint

import constants as C
from clock import clock
from db import db, new_record, public, touch
from errors import fail
from middleware import require
from response import created, ok
from routes.common import list_response
from services.salvage import sale_floor, salvage_value
from validation import get_body, lookup, need_enum, need_int, need_string, resolve_body_fk

bp = Blueprint("disposals", __name__)

READ_ROLES = ["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier",
              "OperationsScheduler", "AssetManager"]


@bp.post("/disposal-records")
def create_disposal():
    require(["AssetManager"])
    body = get_body()
    # rule 5
    unit = resolve_body_fk("unit", body, "portable_unit_id")
    # rule 6
    if unit is None:
        need_string(body, "portable_unit_id")
    method = need_enum(body, "method", C.DISPOSAL_METHODS)
    valuation_basis = need_enum(body, "valuation_basis", C.VALUATION_BASES)
    proceeds = need_int(body, "proceeds_cents", minimum=0)
    # rule 13
    already = any(d["portable_unit_id"] == unit["id"] for d in db.disposals.values())
    disposable = (
        unit["allocation_status"] == "IN_STORAGE"
        and (unit["condition_status"] == "UNSAFE" or unit["condition_grade"] == "D")
        and not already
    )
    if not disposable:
        fail("ERR_UNIT_NOT_DISPOSABLE",
             "That unit is not eligible for disposal.")

    salvage = salvage_value(unit, valuation_basis)
    # rule 41
    if method == "SALE":
        if proceeds < sale_floor(salvage):
            fail("ERR_DISPOSAL_UNDERVALUED",
                 "A SALE must recover at least 70 percent of the salvage value.")
    elif proceeds != 0:
        fail("ERR_DISPOSAL_UNDERVALUED",
             "A %s disposal must record proceeds of exactly 0." % method)

    rec = new_record({
        "portable_unit_id": unit["id"],
        "method": method,
        "valuation_basis": valuation_basis,
        "proceeds_cents": proceeds,
        "salvage_value_cents": salvage,
        "net_disposal_result_cents": proceeds - salvage,
        "disposed_on": clock.iso(),
    }, versioned=False)
    db.disposals[rec["id"]] = rec

    unit["allocation_status"] = "DISPOSED"
    touch(unit)
    return created(public(rec))


@bp.get("/disposal-records/<disposal_id>")
def read_disposal(disposal_id):
    require(READ_ROLES)
    return ok(public(lookup("disposal", disposal_id)))


@bp.get("/disposal-records")
def list_disposals():
    require(READ_ROLES)
    return list_response(db.disposals, ["portable_unit_id", "method"])
