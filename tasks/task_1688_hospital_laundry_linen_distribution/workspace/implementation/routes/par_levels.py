"""ParLevel endpoints (PRD 3.2)."""
from flask import Blueprint, request

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_FACILITY_IN_SURGE, ERR_INVALID_REQUEST, \
    ERR_PAR_LEVEL_CONFLICT, ERR_STALE_VERSION, raise_err
from serializers import par_out
from util import body_json, bump, fk_ref, get_or_404, list_response, new_record, \
    occ_field, opt_enum, opt_int, req_enum, req_int, success_object

bp = Blueprint("par_levels", __name__)

CART_CYCLES = ["DAILY", "TWICE_DAILY", "WEEKLY"]


@bp.route("/par-levels", methods=["POST"])
def create_par_level():
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    body = body_json()

    unit = fk_ref(body, "unit_id", store.units, "Unit")
    stock = fk_ref(body, "stock_id", store.stocks, "LinenStock")
    base = req_int(body, "base_par_quantity")
    if base < 0:
        raise_err(ERR_INVALID_REQUEST, "base_par_quantity must be >= 0")
    cycle = req_enum(body, "cart_cycle", CART_CYCLES)

    for p in store.par_levels.values():
        if p["unit_id"] == unit["id"] and p["stock_id"] == stock["id"]:
            raise_err(ERR_PAR_LEVEL_CONFLICT,
                      "a par level already exists for this (unit_id, stock_id) pair")

    rec = new_record()
    rec.update({
        "unit_id": unit["id"],
        "stock_id": stock["id"],
        "base_par_quantity": base,
        "cart_cycle": cycle,
        "on_hand": 0,
        "effective_par": base,
    })
    store.par_levels[rec["id"]] = rec
    return success_object(par_out(rec), 201)


@bp.route("/par-levels/<par_level_id>", methods=["GET"])
def get_par_level(par_level_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.par_levels, par_level_id, "ParLevel")
    return success_object(par_out(rec))


@bp.route("/par-levels", methods=["GET"])
def list_par_levels():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.par_levels.values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        records = [r for r in records if r["unit_id"] == unit_id]
    stock_id = request.args.get("stock_id")
    if stock_id is not None:
        records = [r for r in records if r["stock_id"] == stock_id]
    return list_response(records, par_out)


@bp.route("/par-levels/<par_level_id>", methods=["PUT"])
def update_par_level(par_level_id):
    """OCC-guarded; blocked while the facility is in SURGE posture (PRD 3.2)."""
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    par = get_or_404(store.par_levels, par_level_id, "ParLevel")
    body = body_json()

    expected = occ_field(body, "expected_par_level_version")
    base = opt_int(body, "base_par_quantity", None)
    if base is not None and base < 0:
        raise_err(ERR_INVALID_REQUEST, "base_par_quantity must be >= 0")
    cycle = opt_enum(body, "cart_cycle", CART_CYCLES, None)

    # OCC (priority 6) before the surge-posture state guard (priority 7)
    if expected != par["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_par_level_version %s does not match current version %s"
                  % (expected, par["version"]))

    unit = store.units.get(par["unit_id"])
    fac = store.facilities.get(unit["facility_id"]) if unit else None
    if fac is not None and fac["surge_posture"] == "SURGE":
        raise_err(ERR_FACILITY_IN_SURGE,
                  "par-level updates are blocked while the facility is in surge")

    if base is not None:
        par["base_par_quantity"] = base
    if cycle is not None:
        par["cart_cycle"] = cycle
    # not in surge: effective_par tracks base_par_quantity
    par["effective_par"] = par["base_par_quantity"]
    bump(par)
    return success_object(par_out(par), 200)
