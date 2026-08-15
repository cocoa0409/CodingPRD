"""IngredientSupply endpoints: recipe lines on DRAFT formulas and consignment
receipts for CUSTOMER_SUPPLIED lines."""
from flask import Blueprint, g, request

from db import STORE
from errors import (
    err,
    ERR_FORMULA_NOT_DRAFT,
    ERR_FORMULA_NOT_FOUND,
    ERR_INGREDIENT_SUPPLY_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from middleware import check_customer_scope, require_roles
from response import paginate, success
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from util import as_num, as_str, body_json, check_enum, req

bp = Blueprint("supplies", __name__)

SOURCING_MODES = ("CUSTOMER_SUPPLIED", "COPACKER_SUPPLIED")


def _formula_of(supply):
    return STORE.formulas.get(supply["formula_id"])


@bp.post("/copack/ingredient-supplies")
def create_supply():
    require_roles("OpsAdmin", "Customer")
    body = body_json()
    raw_formula_id = body.get("formula_id")
    formula = None
    if isinstance(raw_formula_id, str):
        formula = STORE.formulas.get(raw_formula_id)
        if formula is not None:
            check_customer_scope(formula["customer_id"])
    formula_id = as_str(req(body, "formula_id"), "formula_id")
    if formula is None:
        formula = find_or_404(STORE.formulas, formula_id, ERR_FORMULA_NOT_FOUND, "formula")
    ingredient_name = as_str(req(body, "ingredient_name"), "ingredient_name")
    sourcing_mode = check_enum(
        as_str(req(body, "sourcing_mode"), "sourcing_mode"),
        SOURCING_MODES, "sourcing_mode",
    )
    quantity_per_unit = as_num(req(body, "quantity_per_unit"), "quantity_per_unit")
    if quantity_per_unit <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "quantity_per_unit must be > 0")
    # unit_cost_cents is mandatory for COPACKER_SUPPLIED lines and disregarded
    # for consigned ones (PRD §3.1).
    if sourcing_mode == "COPACKER_SUPPLIED":
        unit_cost_cents = as_num(req(body, "unit_cost_cents"), "unit_cost_cents")
        if unit_cost_cents < 0:
            raise err(ERR_INVALID_REQUEST, 400, "unit_cost_cents must be >= 0")
    else:
        unit_cost_cents = body.get("unit_cost_cents")
        if unit_cost_cents is not None:
            as_num(unit_cost_cents, "unit_cost_cents")
    if formula["status"] != "DRAFT":
        raise err(ERR_FORMULA_NOT_DRAFT, 409, "ingredient lines can only be added while the formula is DRAFT")
    rec = new_record({
        "formula_id": formula_id,
        "ingredient_name": ingredient_name,
        "sourcing_mode": sourcing_mode,
        "quantity_per_unit": quantity_per_unit,
        "unit_cost_cents": unit_cost_cents,
        "consigned_units_on_hand": 0,
    })
    STORE.supplies[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/copack/ingredient-supplies")
def list_supplies():
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    formula_id = request.args.get("formula_id")
    items = []
    for s in sorted_created(STORE.supplies.values()):
        if g.user_role == "Customer":
            f = _formula_of(s)
            if f is None or f["customer_id"] != g.user_id:
                continue
        if formula_id is not None and s["formula_id"] != formula_id:
            continue
        items.append(serialize(s))
    return paginate(items)


@bp.get("/copack/ingredient-supplies/<sid>")
def get_supply(sid):
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    rec = find_or_404(STORE.supplies, sid, ERR_INGREDIENT_SUPPLY_NOT_FOUND, "ingredient supply")
    f = _formula_of(rec)
    if f is not None:
        check_customer_scope(f["customer_id"])
    return success(serialize(rec))


@bp.post("/copack/ingredient-supplies/<sid>/receive")
def receive_supply(sid):
    require_roles("OpsAdmin", "Customer")
    rec = find_or_404(STORE.supplies, sid, ERR_INGREDIENT_SUPPLY_NOT_FOUND, "ingredient supply")
    f = _formula_of(rec)
    if f is not None:
        check_customer_scope(f["customer_id"])
    body = body_json()
    quantity = as_num(req(body, "quantity"), "quantity")
    if quantity <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "quantity must be > 0")
    # Consignment receipts exist only for CUSTOMER_SUPPLIED lines (PRD §3.1).
    if rec["sourcing_mode"] != "CUSTOMER_SUPPLIED":
        raise err(ERR_INVALID_REQUEST, 400, "receipts are accepted only for CUSTOMER_SUPPLIED lines")
    rec["consigned_units_on_hand"] += quantity
    touch(rec)
    return success(serialize(rec))
