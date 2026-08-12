from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body
from response import success, paged
from services import get_or_404, cs_append, update_lot_exhaustion
from util import (new_resource, touch, req, opt, as_str, as_int, as_num, as_bool,
                  as_enum, as_list, as_date_str)

bp = Blueprint("catalog", __name__)

SCHEDULES = {"NON_CONTROLLED", "C_II", "C_III", "C_IV", "C_V"}
DOSAGE_FORMS = {"SUSPENSION", "CAPSULE", "CHEW", "TOPICAL", "INJECTABLE"}
SPECIES = {"DOG", "CAT", "BIRD", "REPTILE", "OTHER"}
READ_CATALOG = ("Owner", "Veterinarian", "Pharmacist", "PharmacyTech",
                "ComplianceOfficer", "PharmacyAdmin")


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


# ---- Drug catalog items ----

@bp.route("/drug-catalog-items", methods=["POST"])
def create_drug():
    auth("PharmacyAdmin")
    d = body()
    name = as_str(req(d, "drug_name"), "drug_name")
    schedule = as_enum(req(d, "schedule"), "schedule", SCHEDULES)
    cold = as_bool(req(d, "requires_cold_chain"), "requires_cold_chain")
    cost = as_int(req(d, "unit_cost_cents"), "unit_cost_cents")
    if cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents must be >= 0", 400)
    bud = as_int(req(d, "default_beyond_use_days"), "default_beyond_use_days")
    if bud <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "default_beyond_use_days must be > 0", 400)
    item = new_resource({
        "drug_name": name, "schedule": schedule, "requires_cold_chain": cold,
        "cold_chain_min_celsius": as_num(opt(d, "cold_chain_min_celsius", 2),
                                         "cold_chain_min_celsius"),
        "cold_chain_max_celsius": as_num(opt(d, "cold_chain_max_celsius", 8),
                                         "cold_chain_max_celsius"),
        "unit_cost_cents": cost, "default_beyond_use_days": bud,
        "status": "ACTIVE",
    })
    db.drug_catalog_items[item["id"]] = item
    return success(item, 201)


@bp.route("/drug-catalog-items", methods=["GET"])
def list_drugs():
    auth(*READ_CATALOG)
    return paged(_filter(list(db.drug_catalog_items.values()), ["schedule", "status"]))


@bp.route("/drug-catalog-items/<rid>", methods=["GET"])
def get_drug(rid):
    auth(*READ_CATALOG)
    return success(get_or_404(db.drug_catalog_items, rid, "drug catalog item"))


@bp.route("/drug-catalog-items/<rid>", methods=["PATCH"])
def patch_drug(rid):
    auth("PharmacyAdmin")
    item = get_or_404(db.drug_catalog_items, rid, "drug catalog item")
    d = body()
    if "status" in d and d["status"] is not None:
        item["status"] = as_enum(d["status"], "status", {"ACTIVE", "DISCONTINUED"})
    touch(item)
    return success(item)


@bp.route("/drug-catalog-items/<rid>/formulas", methods=["GET"])
def list_drug_formulas(rid):
    auth("Veterinarian", "Pharmacist", "PharmacyTech", "PharmacyAdmin")
    get_or_404(db.drug_catalog_items, rid, "drug catalog item")
    return paged([f for f in db.formulas.values() if f["drug_catalog_item_id"] == rid])


# ---- Flavorings ----

@bp.route("/flavorings", methods=["POST"])
def create_flavoring():
    auth("PharmacyAdmin")
    d = body()
    name = as_str(req(d, "name"), "name")
    allergen_tags = as_list(opt(d, "allergen_tags", []), "allergen_tags")
    surcharge = as_int(req(d, "surcharge_cents"), "surcharge_cents")
    if surcharge < 0:
        raise ApiError("ERR_INVALID_REQUEST", "surcharge_cents must be >= 0", 400)
    compat = as_list(req(d, "compatible_species"), "compatible_species")
    for s in compat:
        as_enum(s, "compatible_species", SPECIES)
    f = new_resource({
        "name": name, "allergen_tags": allergen_tags, "surcharge_cents": surcharge,
        "compatible_species": compat, "status": "ACTIVE",
    })
    db.flavorings[f["id"]] = f
    return success(f, 201)


@bp.route("/flavorings", methods=["GET"])
def list_flavorings():
    auth("Owner", "Veterinarian", "Pharmacist", "PharmacyTech", "PharmacyAdmin")
    return paged(_filter(list(db.flavorings.values()), ["status"]))


@bp.route("/flavorings/<rid>", methods=["GET"])
def get_flavoring(rid):
    auth("Owner", "Veterinarian", "Pharmacist", "PharmacyTech", "PharmacyAdmin")
    return success(get_or_404(db.flavorings, rid, "flavoring"))


# ---- Formulas ----

@bp.route("/formulas", methods=["POST"])
def create_formula():
    auth("Pharmacist", "PharmacyAdmin")
    d = body()
    drug_id = as_str(req(d, "drug_catalog_item_id"), "drug_catalog_item_id")
    get_or_404(db.drug_catalog_items, drug_id, "drug catalog item")
    name = as_str(req(d, "name"), "name")
    form = as_enum(req(d, "dosage_form"), "dosage_form", DOSAGE_FORMS)
    strength = as_num(req(d, "strength_mg_per_ml"), "strength_mg_per_ml")
    if strength <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "strength_mg_per_ml must be > 0", 400)
    bud = as_int(req(d, "beyond_use_days"), "beyond_use_days")
    if bud <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "beyond_use_days must be > 0", 400)
    minutes = as_int(req(d, "base_compounding_minutes"), "base_compounding_minutes")
    if minutes <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "base_compounding_minutes must be > 0", 400)
    f = new_resource({
        "drug_catalog_item_id": drug_id, "name": name, "dosage_form": form,
        "strength_mg_per_ml": strength, "beyond_use_days": bud,
        "base_compounding_minutes": minutes, "status": "ACTIVE",
    })
    db.formulas[f["id"]] = f
    return success(f, 201)


@bp.route("/formulas/<rid>", methods=["GET"])
def get_formula(rid):
    auth("Veterinarian", "Pharmacist", "PharmacyTech", "PharmacyAdmin")
    return success(get_or_404(db.formulas, rid, "formula"))


# ---- Lots ----

@bp.route("/lots", methods=["POST"])
def create_lot():
    _, user_id = auth("PharmacyTech", "PharmacyAdmin")
    d = body()
    drug_id = as_str(req(d, "drug_catalog_item_id"), "drug_catalog_item_id")
    get_or_404(db.drug_catalog_items, drug_id, "drug catalog item")
    lot_number = as_str(req(d, "lot_number"), "lot_number")
    received = as_int(req(d, "received_qty"), "received_qty")
    if received <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "received_qty must be > 0", 400)
    cost = as_int(req(d, "unit_cost_cents"), "unit_cost_cents")
    if cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents must be >= 0", 400)
    exp = as_date_str(req(d, "expiration_date"), "expiration_date")
    for l in db.lots.values():
        if l["drug_catalog_item_id"] == drug_id and l["lot_number"] == lot_number:
            raise ApiError("ERR_DUPLICATE_LOT_NUMBER",
                           "lot_number already exists for this drug", 409)
    lot = new_resource({
        "drug_catalog_item_id": drug_id, "lot_number": lot_number,
        "received_qty": received, "qty_on_hand": received, "qty_reserved": 0,
        "qty_dispensed": 0, "qty_wasted": 0, "unit_cost_cents": cost,
        "expiration_date": exp, "status": "ACTIVE", "recall_id": None,
    })
    db.lots[lot["id"]] = lot
    cs_append(lot, "RECEIVE", received, user_id)
    return success(lot, 201)


@bp.route("/lots", methods=["GET"])
def list_lots():
    auth("Pharmacist", "PharmacyTech", "ComplianceOfficer", "PharmacyAdmin")
    return paged(_filter(list(db.lots.values()),
                         ["drug_catalog_item_id", "status", "recall_id"]))


@bp.route("/lots/<rid>", methods=["GET"])
def get_lot(rid):
    auth("Pharmacist", "PharmacyTech", "ComplianceOfficer", "PharmacyAdmin")
    return success(get_or_404(db.lots, rid, "lot"))


@bp.route("/lots/<rid>/waste", methods=["POST"])
def waste_lot(rid):
    _, user_id = auth("ComplianceOfficer")
    lot = get_or_404(db.lots, rid, "lot")
    d = body()
    qty = as_int(req(d, "qty"), "qty")
    if qty <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "qty must be > 0", 400)
    as_str(req(d, "reason"), "reason")
    if qty > lot["qty_on_hand"]:
        raise ApiError("ERR_WASTE_EXCEEDS_ON_HAND",
                       "waste qty exceeds the lot's on-hand units", 422)
    lot["qty_on_hand"] -= qty
    lot["qty_wasted"] += qty
    cs_append(lot, "WASTE", -qty, user_id)
    update_lot_exhaustion(lot)
    touch(lot)
    return success(lot)


# ---- Controlled substance log ----

@bp.route("/controlled-substance-entries", methods=["GET"])
def list_cs_entries():
    auth("Pharmacist", "ComplianceOfficer", "PharmacyAdmin")
    return paged(_filter(list(db.cs_entries.values()),
                         ["lot_id", "compound_order_id", "entry_type"]))


@bp.route("/controlled-substance-entries/<rid>", methods=["GET"])
def get_cs_entry(rid):
    auth("Pharmacist", "ComplianceOfficer", "PharmacyAdmin")
    return success(get_or_404(db.cs_entries, rid, "controlled substance entry"))
