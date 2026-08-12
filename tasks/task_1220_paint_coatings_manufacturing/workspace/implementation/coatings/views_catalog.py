"""Tint base and colorant endpoints."""
from flask import Blueprint

from .domain import (
    BASE_FAMILIES,
    PRODUCT_CATEGORIES,
    ser_batch_adjustment,
    ser_colorant,
    ser_formula_line,
    ser_tint_base,
)
from .errors import conflict, not_found
from .store import store
from .util import auth, body, list_response, new_record, success, v_bool, v_enum, v_int, v_num, v_str

bp = Blueprint("catalog", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")


@bp.post("/coatings/tint-bases")
def create_tint_base():
    auth(("LabTechnician",))
    b = body()
    base_code = v_str(b, "base_code")
    product_category = v_enum(b, "product_category", PRODUCT_CATEGORIES)
    base_family = v_enum(b, "base_family", BASE_FAMILIES)
    base_voc_gpl = v_num(b, "base_voc_gpl", minv=0)
    water_fraction_pct = v_num(b, "water_fraction_pct", minv=0)
    if water_fraction_pct >= 100:
        from .errors import bad_request

        raise bad_request("water_fraction_pct must be < 100")
    density = v_num(b, "density_kg_per_gal", gt=0)
    base_cost = v_int(b, "base_cost_per_gal_cents", minv=0)
    unit_price = v_int(b, "unit_price_per_gal_cents", minv=0)
    shelf_life = v_int(b, "shelf_life_months", minv=0)
    grind_spec = v_num(b, "grind_spec_um", minv=0)
    for tb in store.tint_bases.values():
        if tb["base_code"] == base_code:
            raise conflict("ERR_DUPLICATE_CODE", "base_code already exists")
    rec = new_record()
    rec.update({
        "base_code": base_code,
        "product_category": product_category,
        "base_family": base_family,
        "base_voc_gpl": base_voc_gpl,
        "water_fraction_pct": water_fraction_pct,
        "density_kg_per_gal": density,
        "base_cost_per_gal_cents": base_cost,
        "unit_price_per_gal_cents": unit_price,
        "shelf_life_months": shelf_life,
        "grind_spec_um": grind_spec,
    })
    store.tint_bases[rec["id"]] = rec
    return success(ser_tint_base(rec), 201)


@bp.get("/coatings/tint-bases/<bid>")
def get_tint_base(bid):
    auth(ALL)
    rec = store.tint_bases.get(bid)
    if rec is None:
        raise not_found()
    return success(ser_tint_base(rec), 200)


@bp.post("/coatings/colorants")
def create_colorant():
    auth(("LabTechnician",))
    b = body()
    colorant_code = v_str(b, "colorant_code")
    voc_g_per_unit = v_num(b, "voc_g_per_unit", minv=0)
    cost_per_shot_cents = v_int(b, "cost_per_shot_cents", minv=0)
    is_hazmat = v_bool(b, "is_hazmat")
    for c in store.colorants.values():
        if c["colorant_code"] == colorant_code:
            raise conflict("ERR_DUPLICATE_CODE", "colorant_code already exists")
    rec = new_record()
    rec.update({
        "colorant_code": colorant_code,
        "voc_g_per_unit": voc_g_per_unit,
        "cost_per_shot_cents": cost_per_shot_cents,
        "is_hazmat": is_hazmat,
    })
    store.colorants[rec["id"]] = rec
    return success(ser_colorant(rec), 201)


@bp.get("/coatings/colorants/<cid>")
def get_colorant(cid):
    auth(ALL)
    rec = store.colorants.get(cid)
    if rec is None:
        raise not_found()
    return success(ser_colorant(rec), 200)


@bp.get("/coatings/colorants/<cid>/formula-lines")
def colorant_formula_lines(cid):
    auth(ALL)
    rec = store.colorants.get(cid)
    if rec is None:
        raise not_found()
    recs = [l for l in store.formula_lines.values() if l["colorant_id"] == cid]
    return list_response(recs, ser_formula_line)


@bp.get("/coatings/colorants/<cid>/batch-adjustments")
def colorant_batch_adjustments(cid):
    auth(ALL)
    rec = store.colorants.get(cid)
    if rec is None:
        raise not_found()
    recs = [a for a in store.batch_adjustments.values() if a.get("colorant_id") == cid]
    return list_response(recs, ser_batch_adjustment)
