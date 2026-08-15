"""Suppliers, ingredients, and ingredient lots."""
from decimal import Decimal

from flask import Blueprint, request

import serialize
from db import STORES, base_record, touch
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state, terminal_locked,
    unprocessable,
    ERR_SUPPLIER_NOT_FOUND, ERR_INGREDIENT_NOT_FOUND, ERR_LOT_NOT_FOUND,
    ERR_SUPPLIER_NOT_QUALIFIED, ERR_DUPLICATE_LOT_CODE,
)
from middleware import require_roles
from response import ok_object, list_response
from util import (
    D, get_body, require, opt, check_str, check_number, check_enum,
    check_allergen_array, parse_dt, CATEGORY_ENUM, ALLERGEN_ENUM,
)

bp = Blueprint("catalog", __name__)

READ_ROLES = ("PlantAdmin", "FormulationScientist", "QualityManager",
              "ProductionPlanner", "LabTechnician")

SUPPLIER_STATUS = ["PROVISIONAL", "APPROVED", "SUSPENDED"]
INGREDIENT_STATUS = ["ACTIVE", "DISCONTINUED"]
LOT_STATUS = ["QUARANTINE", "RELEASED", "REJECTED", "DEPLETED"]

SUPPLIER_TRANSITIONS = {
    ("PROVISIONAL", "APPROVED"),
    ("APPROVED", "SUSPENDED"),
    ("SUSPENDED", "APPROVED"),
}


def _sorted(name):
    return sorted(STORES[name].values(), key=lambda r: r["_seq"])


def _get_supplier(sid):
    rec = STORES["suppliers"].get(sid)
    if rec is None:
        raise not_found(ERR_SUPPLIER_NOT_FOUND, f"Supplier {sid} does not exist")
    return rec


def _get_ingredient(iid):
    rec = STORES["ingredients"].get(iid)
    if rec is None:
        raise not_found(ERR_INGREDIENT_NOT_FOUND, f"Ingredient {iid} does not exist")
    return rec


def _get_lot(lid):
    rec = STORES["lots"].get(lid)
    if rec is None:
        raise not_found(ERR_LOT_NOT_FOUND, f"Ingredient lot {lid} does not exist")
    return rec


# ---------------- suppliers ----------------

@bp.post("/mfg/suppliers")
def create_supplier():
    require_roles("PlantAdmin")
    body = get_body(request)
    rec = base_record()
    rec.update({
        "name": check_str(require(body, "name"), "name"),
        "allergens_handled": check_allergen_array(opt(body, "allergens_handled", []),
                                                  "allergens_handled"),
        "qualification_status": check_enum(
            opt(body, "qualification_status", "PROVISIONAL"),
            "qualification_status", SUPPLIER_STATUS),
    })
    STORES["suppliers"][rec["id"]] = rec
    return ok_object(serialize.supplier(rec), 201)


@bp.get("/mfg/suppliers")
def list_suppliers():
    require_roles(*READ_ROLES)
    items = _sorted("suppliers")
    f = request.args.get("qualification_status")
    if f is not None:
        check_enum(f, "qualification_status", SUPPLIER_STATUS)
        items = [s for s in items if s["qualification_status"] == f]
    return list_response([serialize.supplier(s) for s in items])


@bp.get("/mfg/suppliers/<sid>")
def get_supplier(sid):
    require_roles(*READ_ROLES)
    return ok_object(serialize.supplier(_get_supplier(sid)))


@bp.patch("/mfg/suppliers/<sid>")
def patch_supplier(sid):
    require_roles("PlantAdmin")
    rec = _get_supplier(sid)
    body = get_body(request)
    new_status = None
    if "qualification_status" in body and body["qualification_status"] is not None:
        new_status = check_enum(body["qualification_status"],
                                "qualification_status", SUPPLIER_STATUS)
    new_allergens = None
    if "allergens_handled" in body and body["allergens_handled"] is not None:
        new_allergens = check_allergen_array(body["allergens_handled"],
                                             "allergens_handled")
    if new_status is not None and new_status != rec["qualification_status"]:
        if (rec["qualification_status"], new_status) not in SUPPLIER_TRANSITIONS:
            raise invalid_state(
                f"Supplier qualification cannot move "
                f"{rec['qualification_status']} -> {new_status}")
        rec["qualification_status"] = new_status
    if new_allergens is not None:
        rec["allergens_handled"] = new_allergens
    touch(rec)
    return ok_object(serialize.supplier(rec))


# ---------------- ingredients ----------------

@bp.post("/mfg/ingredients")
def create_ingredient():
    require_roles("PlantAdmin")
    body = get_body(request)
    # Stage 6: presence / types / numeric ranges
    name = check_str(require(body, "name"), "name")
    category_raw = require(body, "category")
    check_str(category_raw, "category")
    tags_raw = opt(body, "allergen_tags", [])
    if not isinstance(tags_raw, list):
        raise invalid_request("Field 'allergen_tags' must be an array")
    protein_pct = None
    if "nominal_protein_pct" in body and body["nominal_protein_pct"] is not None:
        protein_pct = check_number(body["nominal_protein_pct"],
                                   "nominal_protein_pct", gt=0, lte=1)
    sweetness = None
    if "nominal_sweetness_factor" in body and body["nominal_sweetness_factor"] is not None:
        sweetness = check_number(body["nominal_sweetness_factor"],
                                 "nominal_sweetness_factor", gt=0)
    status_raw = opt(body, "status", "ACTIVE")
    check_str(status_raw, "status")
    # Stage 7: enum membership
    category = check_enum(category_raw, "category", CATEGORY_ENUM)
    tags = check_allergen_array(tags_raw, "allergen_tags")
    status = check_enum(status_raw, "status", INGREDIENT_STATUS)
    # Conditional mandatory assays
    if category == "PROTEIN" and protein_pct is None:
        raise invalid_request(
            "Field 'nominal_protein_pct' is required when category is PROTEIN")
    if category == "SWEETENER" and sweetness is None:
        raise invalid_request(
            "Field 'nominal_sweetness_factor' is required when category is SWEETENER")
    rec = base_record()
    rec.update({
        "name": name,
        "category": category,
        "allergen_tags": tags,
        "nominal_protein_pct": protein_pct,
        "nominal_sweetness_factor": sweetness,
        "status": status,
    })
    STORES["ingredients"][rec["id"]] = rec
    return ok_object(serialize.ingredient(rec), 201)


@bp.get("/mfg/ingredients")
def list_ingredients():
    require_roles(*READ_ROLES)
    items = _sorted("ingredients")
    cat = request.args.get("category")
    if cat is not None:
        check_enum(cat, "category", CATEGORY_ENUM)
        items = [i for i in items if i["category"] == cat]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", INGREDIENT_STATUS)
        items = [i for i in items if i["status"] == st]
    return list_response([serialize.ingredient(i) for i in items])


@bp.get("/mfg/ingredients/<iid>")
def get_ingredient(iid):
    require_roles(*READ_ROLES)
    return ok_object(serialize.ingredient(_get_ingredient(iid)))


# ---------------- ingredient lots ----------------

@bp.post("/mfg/ingredient-lots")
def create_lot():
    require_roles("PlantAdmin")
    body = get_body(request)
    # Body FK existence (stage 5)
    ingredient = None
    supplier = None
    if "ingredient_id" in body and body["ingredient_id"] is not None:
        ingredient = STORES["ingredients"].get(body["ingredient_id"])
        if ingredient is None:
            raise not_found(ERR_INGREDIENT_NOT_FOUND,
                            f"Ingredient {body['ingredient_id']} does not exist")
    if "supplier_id" in body and body["supplier_id"] is not None:
        supplier = STORES["suppliers"].get(body["supplier_id"])
        if supplier is None:
            raise not_found(ERR_SUPPLIER_NOT_FOUND,
                            f"Supplier {body['supplier_id']} does not exist")
    # Request shape (stage 6)
    if ingredient is None:
        raise invalid_request("Missing required field 'ingredient_id'")
    if supplier is None:
        raise invalid_request("Missing required field 'supplier_id'")
    lot_code = check_str(require(body, "lot_code"), "lot_code")
    qty = check_number(require(body, "received_qty_kg"), "received_qty_kg", gt=0)
    received_at = parse_dt(require(body, "received_at"), "received_at")
    coa_protein = None
    if "coa_protein_pct" in body and body["coa_protein_pct"] is not None:
        coa_protein = check_number(body["coa_protein_pct"], "coa_protein_pct",
                                   gt=0, lte=1)
    coa_sweet = None
    if "coa_sweetness_factor" in body and body["coa_sweetness_factor"] is not None:
        coa_sweet = check_number(body["coa_sweetness_factor"],
                                 "coa_sweetness_factor", gt=0)
    if ingredient["category"] == "PROTEIN" and coa_protein is None:
        raise invalid_request(
            "Field 'coa_protein_pct' is required for PROTEIN ingredients")
    if ingredient["category"] == "SWEETENER" and coa_sweet is None:
        raise invalid_request(
            "Field 'coa_sweetness_factor' is required for SWEETENER ingredients")
    # Business rules in order: supplier qualification, then lot-code uniqueness
    if supplier["qualification_status"] != "APPROVED":
        raise unprocessable(ERR_SUPPLIER_NOT_QUALIFIED,
                            "Supplier is not APPROVED for ingredient receipt")
    for other in STORES["lots"].values():
        if (other["ingredient_id"] == ingredient["id"]
                and other["lot_code"] == lot_code
                and other["status"] != "REJECTED"):
            raise unprocessable(
                ERR_DUPLICATE_LOT_CODE,
                f"lot_code '{lot_code}' already exists for this ingredient", 409)
    rec = base_record()
    rec.update({
        "ingredient_id": ingredient["id"],
        "supplier_id": supplier["id"],
        "lot_code": lot_code,
        "received_qty_kg": qty,
        "coa_protein_pct": coa_protein,
        "coa_sweetness_factor": coa_sweet,
        "received_at_dt": received_at,
        "reserved_qty_kg": Decimal("0"),
        "consumed_qty_kg": Decimal("0"),
        "status": "QUARANTINE",
    })
    STORES["lots"][rec["id"]] = rec
    return ok_object(serialize.lot(rec), 201)


@bp.get("/mfg/ingredient-lots")
def list_lots():
    require_roles(*READ_ROLES)
    items = _sorted("lots")
    iid = request.args.get("ingredient_id")
    if iid is not None:
        items = [l for l in items if l["ingredient_id"] == iid]
    sid = request.args.get("supplier_id")
    if sid is not None:
        items = [l for l in items if l["supplier_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", LOT_STATUS)
        items = [l for l in items if l["status"] == st]
    return list_response([serialize.lot(l) for l in items])


@bp.get("/mfg/ingredient-lots/<lid>")
def get_lot(lid):
    require_roles(*READ_ROLES)
    return ok_object(serialize.lot(_get_lot(lid)))


@bp.post("/mfg/ingredient-lots/<lid>/release")
def release_lot(lid):
    require_roles("QualityManager")
    lot = _get_lot(lid)
    if lot["status"] in ("REJECTED", "DEPLETED"):
        raise terminal_locked(f"Lot is {lot['status']} (terminal)")
    if lot["status"] != "QUARANTINE":
        raise invalid_state("Only a QUARANTINE lot can be released")
    lot["status"] = "RELEASED"
    touch(lot)
    return ok_object(serialize.lot(lot))


@bp.post("/mfg/ingredient-lots/<lid>/reject")
def reject_lot(lid):
    from services.inventory import cascade_reject_lot
    require_roles("QualityManager")
    lot = _get_lot(lid)
    if lot["status"] in ("REJECTED", "DEPLETED"):
        raise terminal_locked(f"Lot is {lot['status']} (terminal)")
    if lot["status"] == "QUARANTINE":
        lot["status"] = "REJECTED"
        touch(lot)
    else:  # RELEASED -> REJECTED with the three-link cascade
        lot["status"] = "REJECTED"
        cascade_reject_lot(lot)
    return ok_object(serialize.lot(lot))
