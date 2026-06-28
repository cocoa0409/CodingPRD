"""Catalog/config resources: Practitioner, TreatmentRoom, HerbItem, HerbalFormula.

PRD 3.6 (practitioners/rooms) and 3.9 (herb items/formulas).
"""

from flask import Blueprint

from common import (
    get_json_body,
    optional_int_min,
    paginate,
    public,
    require_fields,
    require_int_min,
    require_string,
    stamp_new,
)
from db import db
from errors import err
from lookups import get_formula, get_herb, get_practitioner, get_room
from middleware import get_auth, require_role
from response import success

bp = Blueprint("catalog", __name__)


# ==========================================================================
# Practitioner
# ==========================================================================
@bp.route("/practitioners", methods=["POST"])
def create_practitioner():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    body = get_json_body()
    require_fields(body, ["full_name", "license_number"])
    full_name = require_string(body, "full_name")
    license_number = require_string(body, "license_number")
    turnover = optional_int_min(body, "turnover_buffer_minutes", 0, 0)
    rec = {
        "full_name": full_name,
        "license_number": license_number,
        "turnover_buffer_minutes": turnover,
    }
    stamp_new(rec)
    db.practitioners[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/practitioners", methods=["GET"])
def list_practitioners():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Pharmacist"])
    data, pg = paginate(list(db.practitioners.values()), public)
    return success(data, status=200, pagination=pg)


@bp.route("/practitioners/<rid>", methods=["GET"])
def get_practitioner_route(rid):
    _, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Pharmacist"])
    rec = get_practitioner(rid)
    return success(public(rec), status=200)


# ==========================================================================
# TreatmentRoom
# ==========================================================================
@bp.route("/rooms", methods=["POST"])
def create_room():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    body = get_json_body()
    require_fields(body, ["room_name"])
    room_name = require_string(body, "room_name")
    cleanup = optional_int_min(body, "cleanup_buffer_minutes", 0, 0)
    rec = {"room_name": room_name, "cleanup_buffer_minutes": cleanup}
    stamp_new(rec)
    db.rooms[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/rooms", methods=["GET"])
def list_rooms():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner"])
    data, pg = paginate(list(db.rooms.values()), public)
    return success(data, status=200, pagination=pg)


@bp.route("/rooms/<rid>", methods=["GET"])
def get_room_route(rid):
    _, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner"])
    rec = get_room(rid)
    return success(public(rec), status=200)


# ==========================================================================
# HerbItem (inventory)
# ==========================================================================
def _herb_public(rec):
    out = public(rec)
    return out


@bp.route("/herb-items", methods=["POST"])
def create_herb_item():
    _, role = get_auth()
    require_role(role, ["Pharmacist"])
    body = get_json_body()
    require_fields(body, ["herb_name", "initial_grams"])
    herb_name = require_string(body, "herb_name")
    initial = require_int_min(body, "initial_grams", 0)
    reorder = optional_int_min(body, "reorder_threshold_grams", 0, 0)
    on_hand = initial
    stock_status = "LOW_STOCK" if on_hand <= reorder else "IN_STOCK"
    rec = {
        "herb_name": herb_name,
        "initial_grams": initial,
        "on_hand_grams": on_hand,
        "reorder_threshold_grams": reorder,
        "stock_status": stock_status,
    }
    stamp_new(rec)
    db.herb_items[rec["id"]] = rec
    return success(_herb_public(rec), status=201)


@bp.route("/herb-items", methods=["GET"])
def list_herb_items():
    _, role = get_auth()
    require_role(role, ["Pharmacist", "Practitioner", "ClinicAdmin"])
    data, pg = paginate(list(db.herb_items.values()), _herb_public)
    return success(data, status=200, pagination=pg)


@bp.route("/herb-items/<rid>", methods=["GET"])
def get_herb_item_route(rid):
    _, role = get_auth()
    require_role(role, ["Pharmacist", "Practitioner", "ClinicAdmin"])
    rec = get_herb(rid)
    return success(_herb_public(rec), status=200)


# ==========================================================================
# HerbalFormula
# ==========================================================================
def _validate_line_items(body):
    items = body.get("line_items")
    if not isinstance(items, list) or len(items) == 0:
        raise err("ERR_INVALID_REQUEST", "line_items must be a non-empty array.")
    normalized = []
    for li in items:
        if not isinstance(li, dict):
            raise err("ERR_INVALID_REQUEST", "Each line item must be an object.")
        herb_item_id = li.get("herb_item_id")
        grams = li.get("grams_per_dose")
        if not isinstance(herb_item_id, str) or herb_item_id == "":
            raise err("ERR_INVALID_REQUEST", "line item herb_item_id required.")
        if isinstance(grams, bool) or not isinstance(grams, int) or grams < 1:
            raise err("ERR_INVALID_REQUEST", "grams_per_dose must be an integer >= 1.")
        normalized.append({"herb_item_id": herb_item_id, "grams_per_dose": grams})
    return normalized


@bp.route("/formulas", methods=["POST"])
def create_formula():
    _, role = get_auth()
    require_role(role, ["Pharmacist", "Practitioner"])
    body = get_json_body()
    require_fields(body, ["formula_name", "line_items"])
    formula_name = require_string(body, "formula_name")
    line_items = _validate_line_items(body)
    rec = {"formula_name": formula_name, "line_items": line_items}
    stamp_new(rec)
    db.herbal_formulas[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/formulas", methods=["GET"])
def list_formulas():
    _, role = get_auth()
    require_role(role, ["Pharmacist", "Practitioner", "ClinicAdmin"])
    data, pg = paginate(list(db.herbal_formulas.values()), public)
    return success(data, status=200, pagination=pg)


@bp.route("/formulas/<rid>", methods=["GET"])
def get_formula_route(rid):
    _, role = get_auth()
    require_role(role, ["Pharmacist", "Practitioner", "ClinicAdmin"])
    rec = get_formula(rid)
    return success(public(rec), status=200)
