"""PreservativeConcentrate endpoints (PRD section 3.3)."""

from flask import Blueprint

import calc
from db import store, new_entity, touch, public
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ASSAY_BELOW_WORKING_MINIMUM,
)
from middleware import authenticate, authorize
from response import success
from util import body_json, req_field, as_number, as_enum, resolve_plant, resolve_preservative

bp = Blueprint("preservatives", __name__)

CHEMICAL_FAMILIES = {"CCA", "ACQ", "CA", "CREOSOTE", "PENTA"}
PRES_READ_ROLES = ["LabTechnician", "PlantOperator", "QualityManager", "ComplianceOfficer"]


def _check_assay_range(value, name):
    if value < 0 or value > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field {} must be between 0 and 100".format(name))


@bp.route("/treatment-plants/<plantId>/preservatives", methods=["POST"])
def create_preservative(plantId):
    body = body_json()
    chemical_family = as_enum(req_field(body, "chemical_family"), "chemical_family", CHEMICAL_FAMILIES)
    assay_pct = as_number(req_field(body, "concentrate_assay_pct"), "concentrate_assay_pct")
    _check_assay_range(assay_pct, "concentrate_assay_pct")
    inventory = as_number(body.get("inventory_gallons", 0), "inventory_gallons")
    min_working = as_number(req_field(body, "min_working_assay_pct"), "min_working_assay_pct")
    _check_assay_range(min_working, "min_working_assay_pct")
    _, role = authenticate()
    authorize(role, ["LabTechnician"])
    plant = resolve_plant(plantId)
    pres = new_entity()
    pres.update({
        "plant_id": plant["id"],
        "chemical_family": chemical_family,
        "concentrate_assay_pct": assay_pct,
        "inventory_gallons": inventory,
        "min_working_assay_pct": min_working,
        "status": "IN_STOCK",
    })
    if inventory < calc.LOW_STOCK_GALLONS:
        pres["status"] = "LOW_STOCK"
    store.preservatives[pres["id"]] = pres
    return success(public(pres), status=201)


@bp.route("/treatment-plants/<plantId>/preservatives/<preservativeId>", methods=["GET"])
def get_preservative(plantId, preservativeId):
    _, role = authenticate()
    authorize(role, PRES_READ_ROLES)
    plant = resolve_plant(plantId)
    return success(public(resolve_preservative(preservativeId, plant)))


@bp.route("/treatment-plants/<plantId>/preservatives/<preservativeId>/assay", methods=["POST"])
def assay_preservative(plantId, preservativeId):
    body = body_json()
    new_assay = as_number(req_field(body, "new_assay_pct"), "new_assay_pct")
    _check_assay_range(new_assay, "new_assay_pct")
    _, role = authenticate()
    authorize(role, ["LabTechnician"])
    plant = resolve_plant(plantId)
    pres = resolve_preservative(preservativeId, plant)
    pres["concentrate_assay_pct"] = new_assay
    touch(pres)
    return success(public(pres))


@bp.route("/treatment-plants/<plantId>/preservatives/<preservativeId>/replenish", methods=["POST"])
def replenish_preservative(plantId, preservativeId):
    body = body_json()
    additional = as_number(req_field(body, "additional_gallons"), "additional_gallons")
    _, role = authenticate()
    authorize(role, ["LabTechnician"])
    plant = resolve_plant(plantId)
    pres = resolve_preservative(preservativeId, plant)
    pres["inventory_gallons"] = pres["inventory_gallons"] + additional
    calc.refresh_stock_status(pres)
    touch(pres)
    return success(public(pres))


@bp.route("/treatment-plants/<plantId>/preservatives/<preservativeId>/quarantine", methods=["POST"])
def quarantine_preservative(plantId, preservativeId):
    body = body_json()
    reason = req_field(body, "reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field reason must be a non-empty string")
    _, role = authenticate()
    authorize(role, ["LabTechnician"])
    plant = resolve_plant(plantId)
    pres = resolve_preservative(preservativeId, plant)
    if pres["status"] != "IN_STOCK":
        raise ApiError(ERR_INVALID_STATE, 409, "Quarantine requires preservative status IN_STOCK")
    pres["status"] = "QUARANTINED"
    pres["quarantine_reason"] = reason
    touch(pres)
    return success(public(pres))


@bp.route("/treatment-plants/<plantId>/preservatives/<preservativeId>/release-quarantine", methods=["POST"])
def release_quarantine(plantId, preservativeId):
    _, role = authenticate()
    authorize(role, ["LabTechnician"])
    plant = resolve_plant(plantId)
    pres = resolve_preservative(preservativeId, plant)
    if pres["status"] != "QUARANTINED":
        raise ApiError(ERR_INVALID_STATE, 409, "Release requires preservative status QUARANTINED")
    if pres["concentrate_assay_pct"] < pres["min_working_assay_pct"]:
        raise ApiError(
            ERR_ASSAY_BELOW_WORKING_MINIMUM,
            422,
            "Re-assay must confirm concentrate_assay_pct >= min_working_assay_pct before release",
        )
    pres["status"] = "IN_STOCK"
    touch(pres)
    return success(public(pres))
