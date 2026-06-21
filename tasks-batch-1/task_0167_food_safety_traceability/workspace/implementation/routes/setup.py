"""Supplier, Ingredient, and AllergenProfile endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import err
from middleware import require_auth
from response import ok_object
from services.common import (
    get_json_body, require_fields, require_str, require_number, require_int,
    optional_bool,
)
from services.entities import base_fields, get_facility_or_404, get_supplier_or_404
from services.serialize import public

bp = Blueprint("setup", __name__)


# --- Supplier ---------------------------------------------------------------

@bp.post("/traceability/suppliers")
def create_supplier():
    require_auth(["QualityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "name"])
    facility_id = require_str(body, "facility_id")
    name = require_str(body, "name")
    coa_required = optional_bool(body, "coa_required", True)

    get_facility_or_404(facility_id)

    rec = base_fields(common=True)
    rec.update({
        "facility_id": facility_id,
        "name": name,
        "approval_status": "APPROVED",
        "coa_required": coa_required,
        "failed_coa_streak": 0,
    })
    db.suppliers[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/traceability/suppliers/<sid>")
def get_supplier(sid):
    require_auth(["QualityManager", "ReceivingClerk", "ProductionOperator", "SafetyAuditor"])
    rec = get_supplier_or_404(sid)
    return ok_object(public(rec), 200)


# --- Ingredient -------------------------------------------------------------

@bp.post("/traceability/ingredients")
def create_ingredient():
    require_auth(["QualityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "name", "storage_target_c", "shelf_life_days"])
    facility_id = require_str(body, "facility_id")
    name = require_str(body, "name")
    storage_target_c = require_number(body, "storage_target_c")
    shelf_life_days = require_int(body, "shelf_life_days")

    if "storage_tolerance_c" in body and body["storage_tolerance_c"] is not None:
        storage_tolerance_c = require_number(body, "storage_tolerance_c")
    else:
        storage_tolerance_c = 2

    declared = body.get("declared_allergen_codes")
    if declared is None:
        declared = []
    if not isinstance(declared, list) or not all(isinstance(c, str) for c in declared):
        raise err("ERR_INVALID_REQUEST", "declared_allergen_codes must be a list of strings")

    get_facility_or_404(facility_id)

    rec = base_fields(common=True)
    rec.update({
        "facility_id": facility_id,
        "name": name,
        "storage_target_c": storage_target_c,
        "storage_tolerance_c": storage_tolerance_c,
        "shelf_life_days": shelf_life_days,
        "declared_allergen_codes": list(declared),
    })
    db.ingredients[rec["id"]] = rec
    return ok_object(public(rec), 201)


# --- AllergenProfile (lean entity: id + created_at only) --------------------

@bp.post("/traceability/allergen-profiles")
def create_allergen_profile():
    require_auth(["QualityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "code", "name", "severity_rank"])
    facility_id = require_str(body, "facility_id")
    code = require_str(body, "code")
    name = require_str(body, "name")
    severity_rank = require_int(body, "severity_rank")

    # severity_rank must lie within 1..5 (PRD §3.1, §2.8).
    if not (1 <= severity_rank <= 5):
        raise err("ERR_INVALID_REQUEST", "severity_rank must be within 1 through 5")

    get_facility_or_404(facility_id)

    # code unique per facility_id (scaffold §1.1) -> body constraint.
    for a in db.allergen_profiles.values():
        if a["facility_id"] == facility_id and a["code"] == code:
            raise err("ERR_INVALID_REQUEST", "code must be unique per facility")

    rec = base_fields(common=False)  # lean: no updated_at / version
    rec.update({
        "facility_id": facility_id,
        "code": code,
        "name": name,
        "severity_rank": severity_rank,
    })
    db.allergen_profiles[rec["id"]] = rec
    return ok_object(public(rec), 201)
