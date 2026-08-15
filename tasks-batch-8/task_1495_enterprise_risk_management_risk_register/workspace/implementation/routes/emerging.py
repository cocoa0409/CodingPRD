"""Emerging risks and scenario analysis (PRD 3.7)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import store
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object, ok_list
from services import (new_entity, touch, serialize_emerging, serialize_risk,
                      sorted_by_creation)
from util import json_body, req_str, opt_str, req_int, opt_num, opt_bool, paginate

bp = Blueprint("emerging", __name__)

PROMOTE_THRESHOLD = 10


def get_emerging_or_404(eid):
    e = store["emerging_risks"].get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Emerging risk not found")
    return e


@bp.post("/emerging-risks")
def create_emerging():
    authenticate(("RiskManager", "RiskOwner"))
    data = json_body()
    category_id = req_str(data, "category_id")
    title = req_str(data, "title")
    severity = req_int(data, "scenario_severity")
    probability = req_int(data, "scenario_probability")
    stress = opt_num(data, "stress_factor")
    if stress is None:
        stress = Decimal("1.0")
    description = opt_str(data, "description")
    if category_id not in store["categories"]:
        raise ApiError("ERR_NOT_FOUND", 404, "category_id does not exist")
    if not (1 <= severity <= 5) or not (1 <= probability <= 5):
        raise ApiError("ERR_SCORE_OUT_OF_RANGE", 422,
                       "scenario_severity and scenario_probability must be in 1..5")
    if stress < Decimal("0.5") or stress > Decimal("3.0"):
        raise ApiError("ERR_SCORE_OUT_OF_RANGE", 422,
                       "stress_factor must be within [0.5, 3.0]")
    score = int((Decimal(severity) * Decimal(probability) * stress).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    e = new_entity()
    e.update({
        "category_id": category_id,
        "title": title,
        "description": description,
        "scenario_severity": severity,
        "scenario_probability": probability,
        "stress_factor": stress,
        "scenario_score": score,
        "status": "DRAFT",
    })
    store["emerging_risks"][e["id"]] = e
    return ok_object(serialize_emerging(e), 201)


@bp.get("/emerging-risks/<eid>")
def get_emerging(eid):
    authenticate(ALL_ROLES)
    return ok_object(serialize_emerging(get_emerging_or_404(eid)))


@bp.get("/emerging-risks/<eid>/risks")
def list_promoted_risks(eid):
    authenticate(ALL_ROLES)
    get_emerging_or_404(eid)
    items = sorted_by_creation(
        r for r in store["risks"].values() if r["source_emerging_risk_id"] == eid)
    page, meta = paginate(items)
    return ok_list([serialize_risk(r) for r in page], meta)


@bp.post("/emerging-risks/<eid>/validate")
def validate_emerging(eid):
    authenticate(("RiskManager",))
    e = get_emerging_or_404(eid)
    if e["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Emerging risk in status %s cannot be validated" % e["status"])
    e["status"] = "VALIDATED"
    touch(e)
    return ok_object(serialize_emerging(e))


@bp.post("/emerging-risks/<eid>/promote")
def promote_emerging(eid):
    authenticate(("RiskManager",))
    data = json_body()
    owner_user_id = req_str(data, "owner_user_id")
    force = opt_bool(data, "force")
    rationale = opt_str(data, "rationale")
    e = get_emerging_or_404(eid)
    if e["status"] != "VALIDATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a VALIDATED emerging risk can be promoted")
    forced = force is True and rationale is not None and rationale.strip() != ""
    if e["scenario_score"] < PROMOTE_THRESHOLD and not forced:
        raise ApiError("ERR_EMERGING_SCORE_BELOW_THRESHOLD", 422,
                       "scenario_score below 10 requires force=true with a non-empty rationale")
    e["status"] = "PROMOTED"
    touch(e)
    r = new_entity()
    r.update({
        "category_id": e["category_id"],
        "source_emerging_risk_id": e["id"],
        "title": e["title"],
        "description": None,
        "owner_user_id": owner_user_id,
        "treatment_budget_cents": 0,
        "status": "DRAFT",
        "likelihood": None,
        "impact": None,
        "inherent_score": None,
        "inherent_band": None,
        "residual_score": None,
        "residual_band": None,
        "reserved_treatment_cents": 0,
        "kri_alert": False,
    })
    store["risks"][r["id"]] = r
    return ok_object(serialize_risk(r), 201)


@bp.post("/emerging-risks/<eid>/dismiss")
def dismiss_emerging(eid):
    authenticate(("RiskManager",))
    json_body()  # optional reason; not persisted
    e = get_emerging_or_404(eid)
    if e["status"] not in ("DRAFT", "VALIDATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Emerging risk in status %s cannot be dismissed" % e["status"])
    e["status"] = "DISMISSED"
    touch(e)
    return ok_object(serialize_emerging(e))
