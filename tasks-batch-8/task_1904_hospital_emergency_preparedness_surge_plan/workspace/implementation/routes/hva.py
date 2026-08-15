"""Hazard vulnerability analysis endpoints."""

from flask import Blueprint, g

from db import store
from domain import (HAZARD_CATEGORIES, PLAN_REVIEW_TRIGGER_SCORE, SCORING_MODELS,
                    get_or_404, rescore_hva, ser_hva)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_enum, field_str, new_entity, require_body, touch

bp = Blueprint("hva", __name__)


def _validate_entries(raw):
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field 'hazard_entries' must be an array")
    entries = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "hazard_entries[%d] must be an object" % i)
        entry_key = item.get("entry_key")
        if not isinstance(entry_key, str):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "hazard_entries[%d].entry_key must be a string" % i)
        hazard_name = item.get("hazard_name")
        if not isinstance(hazard_name, str):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "hazard_entries[%d].hazard_name must be a string" % i)
        category = item.get("category")
        if category not in HAZARD_CATEGORIES:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "hazard_entries[%d].category must be one of %s"
                           % (i, ", ".join(HAZARD_CATEGORIES)))
        factors = {}
        for name in ("probability", "severity", "preparedness"):
            v = item.get(name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 3:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "hazard_entries[%d].%s must be an integer between 0 and 3"
                               % (i, name))
            factors[name] = v
        # Client-supplied risk_score is ignored; the server computes it.
        entries.append({
            "entry_key": entry_key,
            "hazard_name": hazard_name,
            "category": category,
            "probability": factors["probability"],
            "severity": factors["severity"],
            "preparedness": factors["preparedness"],
            "risk_score": 0,
        })
    return entries


@bp.post("/hazard-assessments")
@authorize(["EmergencyManager"])
def create_hva():
    body = require_body()
    fiscal_year = field_str(body, "fiscal_year", required=True)
    scoring_model = field_enum(body, "scoring_model", SCORING_MODELS, required=True)
    entries = _validate_entries(body.get("hazard_entries", []))

    hva = new_entity()
    hva.update({
        "fiscal_year": fiscal_year,
        "scoring_model": scoring_model,
        "hazard_entries": entries,
        "max_risk_score": 0,
        "plan_review_triggered": False,
        "status": "DRAFT",
    })
    rescore_hva(hva)
    store["hazard_assessments"][hva["id"]] = hva
    return success(ser_hva(hva), "object", 201)


@bp.get("/hazard-assessments/<hva_id>")
@authorize(ALL_ROLES)
def get_hva(hva_id):
    return success(ser_hva(get_or_404("hazard_assessments", hva_id)), "object", 200)


@bp.patch("/hazard-assessments/<hva_id>")
@authorize(["EmergencyManager"])
def patch_hva(hva_id):
    hva = get_or_404("hazard_assessments", hva_id)
    body = require_body()
    if "hazard_entries" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field 'hazard_entries'")
    entries = _validate_entries(body.get("hazard_entries"))

    if hva["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "hazard entries are frozen once the assessment is FINALIZED")

    hva["hazard_entries"] = entries
    rescore_hva(hva)
    touch(hva)
    return success(ser_hva(hva), "object", 200)


@bp.post("/hazard-assessments/<hva_id>/finalize")
@authorize(["EmergencyManager"])
def finalize_hva(hva_id):
    hva = get_or_404("hazard_assessments", hva_id)

    if hva["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a DRAFT hazard assessment can be finalized")
    if len(hva["hazard_entries"]) < 1:
        raise ApiError("ERR_HVA_NO_ENTRIES", 422,
                       "cannot finalize a hazard assessment with no hazard entries")

    rescore_hva(hva)
    hva["plan_review_triggered"] = hva["max_risk_score"] >= PLAN_REVIEW_TRIGGER_SCORE
    hva["status"] = "FINALIZED"
    touch(hva)
    return success(ser_hva(hva), "object", 200)
