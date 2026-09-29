"""Milling a lot: dimensional planning, mass balance and byproducts (PRD 3.6),
plus lot closeout and the yield summary (PRD 3.7)."""

from flask import Blueprint

from db import db, insert, touch
from errors import ApiError
from middleware import ALL_ROLES, MILL_ADMIN, MILL_SUPERVISOR, GRADE_INSPECTOR, authorize
from response import array_response, object_response, paginate
from serializers import jsonable, serialize, serialize_many
from services import calc, lookup, mill
from services.calc import D, rhu
from validation import (body_json, opt_ref, pagination, query_enum, query_str,
                        req_decimal, req_ref, req_str)

bp = Blueprint("lots", __name__)

LOT_STATUSES = ("PLANNED", "MILLED", "GRADED", "QUARANTINED", "VOIDED")


def _species_for_line(line):
    return db.species_profiles[line["species_profile_id"]]


@bp.post("/mill/flooring-lots")
@authorize(MILL_SUPERVISOR, MILL_ADMIN)
def create_flooring_lot():
    body = body_json()
    product_line_id = req_ref(body, "product_line_id")
    kiln_charge_id = req_ref(body, "kiln_charge_id")
    core_stock_id = opt_ref(body, "core_stock_id")
    input_dry_bf = req_decimal(body, "input_dry_bf")

    line = lookup.product_line(product_line_id)
    stock = lookup.core_stock(core_stock_id) if core_stock_id is not None else None
    charge = lookup.kiln_charge(kiln_charge_id)

    if charge["status"] != "RELEASED":
        raise ApiError("ERR_CHARGE_STATE_INVALID")

    construction_type = line["construction_type"]
    if construction_type == "ENGINEERED" and stock is None:
        raise ApiError("ERR_CORE_STOCK_REQUIRED")
    if construction_type == "SOLID" and stock is not None:
        raise ApiError("ERR_CORE_STOCK_NOT_ALLOWED")
    if stock is not None and stock["product_line_id"] != line["id"]:
        raise ApiError("ERR_CORE_STOCK_LINE_MISMATCH")

    if input_dry_bf > D(charge["remaining_dry_bf"]):
        raise ApiError("ERR_CHARGE_DRY_BF_EXCEEDED")

    reserved_core_sf = None
    if stock is not None:
        reserved_core_sf = calc.core_reservation(input_dry_bf)
        projected = rhu(D(stock["reserved_square_feet"]) + reserved_core_sf, 2)
        if projected > D(stock["available_square_feet"]):
            raise ApiError("ERR_CORE_STOCK_INSUFFICIENT")

    species = _species_for_line(line)
    reference_mc = charge["average_moisture_pct"]
    if reference_mc is None:
        reference_mc = species["target_moisture_pct"]
    movement, planned_width = calc.dimensional_shrinkage_plan(
        line["nominal_width_in"], species["tangential_shrinkage_coefficient"], reference_mc)

    record = insert(db.flooring_lots, {
        "product_line_id": product_line_id,
        "kiln_charge_id": kiln_charge_id,
        "core_stock_id": core_stock_id,
        "input_dry_bf": input_dry_bf,
        "construction_type": construction_type,
        "nominal_width_in": line["nominal_width_in"],
        "planned_finished_width_in": planned_width,
        "dimensional_growth_allowance_in": movement,
        "reserved_core_sf": reserved_core_sf,
        "actual_milled_width_in": None,
        "net_flooring_bf": None,
        "shorts_bf": None,
        "sawdust_tons": None,
        "shavings_tons": None,
        "residue_bf": None,
        "waste_bf": None,
        "provisional_yield_pct": None,
        "final_yield_pct": None,
        "final_grade_run_id": None,
        "quarantine_reason": None,
        "void_reason": None,
        "status": "PLANNED",
    })

    if stock is not None:
        mill.recompute_reserved_square_feet(stock)
        touch(stock)

    mill.recompute_remaining_dry_bf(charge)
    if D(charge["remaining_dry_bf"]) == 0:
        charge["status"] = "CLOSED"
    touch(charge)

    return object_response(serialize("flooring_lot", record), 201)


@bp.get("/mill/flooring-lots/<flooring_lot_id>")
@authorize(*ALL_ROLES)
def get_flooring_lot(flooring_lot_id):
    return object_response(serialize("flooring_lot", lookup.flooring_lot(flooring_lot_id)))


@bp.get("/mill/flooring-lots")
@authorize(*ALL_ROLES)
def list_flooring_lots():
    limit, offset = pagination()
    rows = lookup.filtered(db.flooring_lots, [
        ("product_line_id", query_str("product_line_id")),
        ("kiln_charge_id", query_str("kiln_charge_id")),
        ("core_stock_id", query_str("core_stock_id")),
        ("final_grade_run_id", query_str("final_grade_run_id")),
        ("status", query_enum("status", LOT_STATUSES)),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("flooring_lot", page), limit, offset, total)


@bp.post("/mill/flooring-lots/<flooring_lot_id>/complete_milling")
@authorize(MILL_SUPERVISOR)
def complete_milling(flooring_lot_id):
    body = body_json()
    actual_milled_width_in = req_decimal(body, "actual_milled_width_in")
    net_flooring_bf = req_decimal(body, "net_flooring_bf")
    shorts_bf = req_decimal(body, "shorts_bf")
    sawdust_tons = req_decimal(body, "sawdust_tons")
    shavings_tons = req_decimal(body, "shavings_tons")

    lot = lookup.flooring_lot(flooring_lot_id)
    if lot["status"] != "PLANNED":
        raise ApiError("ERR_LOT_STATE_INVALID")

    if abs(actual_milled_width_in - D(lot["planned_finished_width_in"])) > calc.PROFILE_TOLERANCE_IN:
        raise ApiError("ERR_PROFILE_TOLERANCE_EXCEEDED")

    residue_bf, waste_bf, waste_limit_bf = calc.mill_mass_balance(
        lot["input_dry_bf"], net_flooring_bf, shorts_bf, sawdust_tons, shavings_tons)

    if waste_bf < 0:
        raise ApiError("ERR_MILL_MASS_BALANCE_VIOLATION")
    if waste_bf > waste_limit_bf:
        raise ApiError("ERR_WASTE_LIMIT_EXCEEDED")

    lot["actual_milled_width_in"] = actual_milled_width_in
    lot["net_flooring_bf"] = net_flooring_bf
    lot["shorts_bf"] = shorts_bf
    lot["sawdust_tons"] = sawdust_tons
    lot["shavings_tons"] = shavings_tons
    lot["residue_bf"] = residue_bf
    lot["waste_bf"] = waste_bf
    lot["provisional_yield_pct"] = calc.yield_pct(net_flooring_bf, lot["input_dry_bf"])
    lot["status"] = "MILLED"
    touch(lot)

    for byproduct_type, available in (("SAWDUST", rhu(sawdust_tons, 2)),
                                      ("SHAVINGS", rhu(shavings_tons, 2)),
                                      ("SHORTS", calc.shorts_tons(shorts_bf))):
        insert(db.byproduct_batches, {
            "flooring_lot_id": lot["id"],
            "byproduct_type": byproduct_type,
            "available_tons": available,
            "sold_tons": rhu(0, 2),
        })

    return object_response(serialize("flooring_lot", lot))


@bp.post("/mill/flooring-lots/<flooring_lot_id>/finalize")
@authorize(MILL_SUPERVISOR, GRADE_INSPECTOR)
def finalize_flooring_lot(flooring_lot_id):
    body = body_json()
    grade_run_id = req_ref(body, "grade_run_id")

    lot = lookup.flooring_lot(flooring_lot_id)
    run = lookup.grade_run(grade_run_id)

    if lot["status"] != "MILLED":
        raise ApiError("ERR_LOT_STATE_INVALID")
    if run["status"] != "FINALIZED":
        raise ApiError("ERR_GRADE_RUN_STATE_INVALID")
    if run["flooring_lot_id"] != lot["id"]:
        raise ApiError("ERR_GRADE_RUN_LOT_MISMATCH")

    final_yield_pct = calc.yield_pct(run["credited_board_feet"], lot["input_dry_bf"])
    lot["final_yield_pct"] = final_yield_pct
    lot["final_grade_run_id"] = run["id"]

    if final_yield_pct >= calc.YIELD_FLOOR_PCT:
        lot["status"] = "GRADED"
    else:
        lot["status"] = "QUARANTINED"
        lot["quarantine_reason"] = (
            "Final yield %s percent is below the yield floor of %s percent."
            % (final_yield_pct, calc.YIELD_FLOOR_PCT)
        )
    touch(lot)
    return object_response(serialize("flooring_lot", lot))


@bp.post("/mill/flooring-lots/<flooring_lot_id>/void")
@authorize(MILL_SUPERVISOR, MILL_ADMIN)
def void_flooring_lot(flooring_lot_id):
    body = body_json()
    void_reason = req_str(body, "void_reason")

    lot = lookup.flooring_lot(flooring_lot_id)
    if lot["status"] not in ("PLANNED", "MILLED"):
        raise ApiError("ERR_LOT_STATE_INVALID")

    was_milled = lot["status"] == "MILLED"
    if was_milled and mill.lot_has_byproduct_sale(lot["id"]):
        raise ApiError("ERR_BYPRODUCT_SALE_EXISTS")

    lot["status"] = "VOIDED"
    lot["void_reason"] = void_reason
    touch(lot)

    if lot.get("core_stock_id"):
        stock = db.core_stocks.get(lot["core_stock_id"])
        if stock is not None:
            mill.recompute_reserved_square_feet(stock)
            touch(stock)

    charge = db.kiln_charges.get(lot["kiln_charge_id"])
    if charge is not None:
        mill.recompute_remaining_dry_bf(charge)
        if charge["status"] == "CLOSED" and D(charge["remaining_dry_bf"] or 0) > 0:
            charge["status"] = "RELEASED"
        touch(charge)

    if was_milled:
        for batch in mill.lot_batches(lot["id"]):
            batch["available_tons"] = rhu(0, 2)
            touch(batch)

    return object_response(serialize("flooring_lot", lot))


@bp.get("/mill/flooring-lots/<flooring_lot_id>/yield-summary")
@authorize(*ALL_ROLES)
def yield_summary(flooring_lot_id):
    lot = lookup.flooring_lot(flooring_lot_id)
    provisional = lot["provisional_yield_pct"]
    final = lot["final_yield_pct"]
    delta = None if final is None else rhu(D(final) - D(provisional or 0), 2)
    return object_response({
        "flooring_lot_id": lot["id"],
        "input_dry_bf": jsonable(lot["input_dry_bf"]),
        "net_flooring_bf": jsonable(lot["net_flooring_bf"]),
        "residue_bf": jsonable(lot["residue_bf"]),
        "waste_bf": jsonable(lot["waste_bf"]),
        "provisional_yield_pct": jsonable(provisional),
        "final_yield_pct": jsonable(final),
        "yield_delta_pp": jsonable(delta),
        "yield_floor_pct": jsonable(calc.YIELD_FLOOR_PCT),
    })
