"""Fitment-rule junction routes (PRD §3.1, §2.10).

A FitmentRule is immutable: it carries only id + created_at (PRD §2.4).
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_fk_or_404,
    lookup_path_or_404,
    require_enum,
    require_fields,
    require_string,
)

bp = Blueprint("fitment_rules", __name__)

FITMENT_GRADES = {"OE_EXACT", "APPROVED_PLUS", "NOT_RECOMMENDED"}


@bp.post("/fitment-rules")
def create_fitment_rule():
    require_auth(["InventoryManager"])()
    body = get_json_body()
    require_fields(body, ["vehicle_id", "tire_model_id", "fitment_grade"])
    vehicle_id = require_string(body["vehicle_id"], "vehicle_id")
    tire_model_id = require_string(body["tire_model_id"], "tire_model_id")
    fitment_grade = require_enum(body["fitment_grade"], FITMENT_GRADES,
                                 "fitment_grade")

    with db.mutation_lock:
        lookup_fk_or_404(db.vehicles, vehicle_id, "Vehicle")
        lookup_fk_or_404(db.tire_models, tire_model_id, "TireModel")
        rule = {
            "vehicle_id": vehicle_id,
            "tire_model_id": tire_model_id,
            "fitment_grade": fitment_grade,
        }
        db.stamp_immutable(rule)
        db.fitment_rules[rule["id"]] = rule
        return ok_object(rule, 201)


@bp.get("/fitment-rules/<fid>")
def get_fitment_rule(fid: str):
    require_auth(["InventoryManager", "ServiceAdvisor", "Customer"])()
    rule = lookup_path_or_404(db.fitment_rules, fid, "FitmentRule")
    return ok_object(rule, 200)


@bp.get("/fitment-rules")
def list_fitment_rules():
    require_auth(["InventoryManager", "ServiceAdvisor", "Customer"])()
    limit, offset = paginate_params(request.args)
    items = list(db.fitment_rules.values())
    if "vehicle_id" in request.args:
        items = [r for r in items if r["vehicle_id"] == request.args["vehicle_id"]]
    if "tire_model_id" in request.args:
        items = [r for r in items if r["tire_model_id"] == request.args["tire_model_id"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
