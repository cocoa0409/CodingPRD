"""New item setup, UPC integrity and catalog data (PRD section 3.3)."""

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize, check_principal_scope
from services import calc, domain

bp = Blueprint("items", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "principal_id": rec["principal_id"],
        "upc": rec["upc"],
        "description": rec["description"],
        "case_pack_units": rec["case_pack_units"],
        "list_price_cents": rec["list_price_cents"],
        "unit_cost_cents": rec["unit_cost_cents"],
        "gtin14": rec["gtin14"],
        "dimensions_cm": rec["dimensions_cm"],
        "gross_weight_g": rec["gross_weight_g"],
        "nutrition_panel_url": rec["nutrition_panel_url"],
        "shelf_life_days": rec["shelf_life_days"],
        "catalog_state": rec["catalog_state"],
        "catalog_submission_round": rec["catalog_submission_round"],
        "catalog_reject_reason": rec["catalog_reject_reason"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/items")
def create_item():
    authorize("BrokerAccountManager")
    data = v.body()

    principal_id = v.req_id(data, "principal_id")
    upc = v.req_upc_shape(data)
    description = v.req_string(data, "description")
    case_pack_units = v.req_int(data, "case_pack_units", 1)
    list_price_cents = v.req_int(data, "list_price_cents", 1)
    unit_cost_cents = v.req_int(data, "unit_cost_cents", 1)
    # The check digit is the last shape defect, after every required field is present.
    v.check_upc_digit(upc)

    db.get("principals", principal_id)

    for existing in db.ordered("items"):
        if existing["upc"] == upc:
            raise ApiError("ERR_UPC_DUPLICATE")

    rec = db.base_record()
    rec.update({
        "principal_id": principal_id,
        "upc": upc,
        "description": description,
        "case_pack_units": case_pack_units,
        "list_price_cents": list_price_cents,
        "unit_cost_cents": unit_cost_cents,
        "gtin14": None,
        "dimensions_cm": None,
        "gross_weight_g": None,
        "nutrition_panel_url": None,
        "shelf_life_days": None,
        "catalog_state": "INCOMPLETE",
        "catalog_submission_round": 0,
        "catalog_reject_reason": None,
    })
    db.insert("items", rec)
    return response.created(serialize(rec))


@bp.get("/items/<item_id>")
def read_item(item_id):
    user_id, role = authorize(*ALL_ROLES)
    rec = db.get("items", item_id)
    check_principal_scope(role, user_id, rec["principal_id"])
    return response.ok(serialize(rec))


@bp.get("/items")
def list_items():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    principal_id = v.filter_value("principal_id")
    catalog_state = v.filter_value("catalog_state")
    upc = v.filter_value("upc")
    rows = []
    for rec in db.ordered("items"):
        if principal_id is not None and rec["principal_id"] != principal_id:
            continue
        if catalog_state is not None and rec["catalog_state"] != catalog_state:
            continue
        if upc is not None and rec["upc"] != upc:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/items/<item_id>/catalog-submissions")
def submit_catalog(item_id):
    authorize("BrokerAccountManager")
    data = v.body()

    gtin14 = v.req_string(data, "gtin14")
    dimensions_cm = v.req_string(data, "dimensions_cm")
    gross_weight_g = v.req_int(data, "gross_weight_g", 1)
    nutrition_panel_url = v.req_string(data, "nutrition_panel_url")
    shelf_life_days = v.req_int(data, "shelf_life_days")

    rec = db.get("items", item_id)

    if rec["catalog_state"] not in ("INCOMPLETE", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE")

    if rec["catalog_state"] == "INCOMPLETE":
        principal = db.find("principals", rec["principal_id"])
        if principal is None or principal["status"] not in ("PROSPECT", "ACTIVE"):
            raise ApiError("ERR_PRINCIPAL_NOT_ACTIVE")

    if gtin14 != "00" + rec["upc"]:
        raise ApiError("ERR_CATALOG_GTIN_MISMATCH")
    if shelf_life_days < calc.MIN_SHELF_LIFE_DAYS:
        raise ApiError("ERR_CATALOG_SHELF_LIFE_TOO_SHORT")

    rec["gtin14"] = gtin14
    rec["dimensions_cm"] = dimensions_cm
    rec["gross_weight_g"] = gross_weight_g
    rec["nutrition_panel_url"] = nutrition_panel_url
    rec["shelf_life_days"] = shelf_life_days
    rec["catalog_state"] = "SUBMITTED"
    rec["catalog_submission_round"] = rec["catalog_submission_round"] + 1
    rec["catalog_reject_reason"] = None
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/items/<item_id>/catalog-decision")
def decide_catalog(item_id):
    authorize("RetailerBuyer")
    data = v.body()

    decision = v.req_enum(data, "decision", v.CATALOG_DECISIONS)
    if decision == "REJECTED":
        reject_reason = v.req_string(data, "reject_reason")
    else:
        reject_reason = None

    rec = db.get("items", item_id)

    if rec["catalog_state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")

    if decision == "VALIDATED":
        db.assign(rec, catalog_state="VALIDATED")
    else:
        db.assign(rec, catalog_state="REJECTED", catalog_reject_reason=reject_reason)

    domain.recompute_prep_for_item(rec["id"])
    return response.ok(serialize(rec))
