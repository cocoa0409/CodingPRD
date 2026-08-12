"""Formulas: authoring, least-cost optimization, activation, retirement (PRD 3.4)."""
from flask import Blueprint

from db import STORE, make_record, bump, clock_now
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize, ALL_ROLES
from services import (ser_formula, solve_ration, nutrient_totals, provisional_cost,
                      formula_in_use)
from validation import get_body, req_str, req_num, req_int

bp = Blueprint("formulas", __name__)


def _get_formula(fid):
    f = STORE["formulas"].get(fid)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Formula {fid} not found")
    return f


@bp.post("/api/formulas")
def create_formula():
    uid, role = authenticate()
    data = get_body()
    code = req_str(data, "code")
    min_protein = req_num(data, "min_protein_pct")
    max_fiber = req_num(data, "max_fiber_pct")
    min_energy = req_num(data, "min_energy_kcal_kg")
    authorize(role, uid, {"Nutritionist"})
    if any(f["code"] == code for f in STORE["formulas"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, f"Formula code {code!r} already exists")
    rec = make_record()
    rec.update(code=code, min_protein_pct=min_protein, max_fiber_pct=max_fiber,
               min_energy_kcal_kg=min_energy, lines=[], total_protein_pct=None,
               total_fiber_pct=None, total_energy_kcal_kg=None,
               meets_constraints=False, provisional_cost_cents_per_ton=None,
               status="DRAFT")
    STORE["formulas"][rec["id"]] = rec
    return success(ser_formula(rec), 201)


@bp.get("/api/formulas/<fid>")
def get_formula(fid):
    uid, role = authenticate()
    authorize(role, uid, ALL_ROLES)
    return success(ser_formula(_get_formula(fid)), 200)


@bp.post("/api/formulas/<fid>/optimize")
def optimize_formula(fid):
    uid, role = authenticate()
    data = get_body()
    expected = req_int(data, "expected_formula_version")
    authorize(role, uid, {"Nutritionist"})
    f = _get_formula(fid)
    # Layer 5 (OCC) runs before the state check (PRD 2.11).
    if expected != f["version"]:
        raise ApiError("ERR_STALE_FORMULA_VERSION", 412,
                       "expected_formula_version does not match the formula's version")
    if f["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Only DRAFT or ACTIVE formulas can be optimized")
    T = clock_now()
    lines = solve_ration(T)
    tp, tf, te = nutrient_totals(lines)
    f["lines"] = lines
    f["total_protein_pct"] = tp
    f["total_fiber_pct"] = tf
    f["total_energy_kcal_kg"] = te
    f["meets_constraints"] = (tp >= f["min_protein_pct"] and tf <= f["max_fiber_pct"]
                              and te >= f["min_energy_kcal_kg"])
    f["provisional_cost_cents_per_ton"] = provisional_cost(lines, T)
    bump(f)
    return success(ser_formula(f), 200)


@bp.post("/api/formulas/<fid>/activate")
def activate_formula(fid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Nutritionist"})
    f = _get_formula(fid)
    if f["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT formula can be activated")
    if not f["lines"] or not f["meets_constraints"]:
        raise ApiError("ERR_NUTRIENT_CONSTRAINT_VIOLATION", 422,
                       "Formula does not meet its nutrient constraints")
    for line in f["lines"]:
        ing = STORE["ingredients"].get(line["ingredient_id"])
        if ing is None or ing["status"] != "ACTIVE":
            raise ApiError("ERR_INGREDIENT_NOT_ACTIVE", 422,
                           "A line ingredient is not ACTIVE")
    f["status"] = "ACTIVE"
    bump(f)
    return success(ser_formula(f), 200)


@bp.post("/api/formulas/<fid>/retire")
def retire_formula(fid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Nutritionist", "MillManager"})
    f = _get_formula(fid)
    if f["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Formula is already RETIRED")
    # Manual retire only: live orders pinning this formula block retirement.
    if f["status"] == "ACTIVE" and formula_in_use(fid):
        raise ApiError("ERR_FORMULA_IN_USE", 409,
                       "A live order pins this formula; it cannot be retired")
    f["status"] = "RETIRED"
    bump(f)
    return success(ser_formula(f), 200)
