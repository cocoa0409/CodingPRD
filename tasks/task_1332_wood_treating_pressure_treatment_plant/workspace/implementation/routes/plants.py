"""TreatmentPlant endpoints and license governance (PRD section 3.1)."""

from flask import Blueprint

import calc
from db import store, new_entity, touch, public
from errors import ApiError, ERR_INVALID_STATE
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from util import body_json, req_field, as_str, resolve_plant, paginate, query_filter

bp = Blueprint("plants", __name__)

INSPECTION_OPEN_STATES = ("SCHEDULED", "IN_PROGRESS", "FINDINGS_ISSUED")
CHARGE_TERMINAL_STATES = ("RELEASED", "REJECTED", "SCRAPPED")


@bp.route("/treatment-plants", methods=["POST"])
def create_plant():
    body = body_json()
    plant_name = as_str(req_field(body, "plant_name"), "plant_name")
    alsc_license_number = as_str(req_field(body, "alsc_license_number"), "alsc_license_number")
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    plant = new_entity()
    plant.update({
        "plant_name": plant_name,
        "alsc_license_number": alsc_license_number,
        "compliance_score": 1000,
        "hazardous_waste_liability_cents": 0,
        "status": "LICENSED",
    })
    store.plants[plant["id"]] = plant
    return success(public(plant), status=201)


@bp.route("/treatment-plants", methods=["GET"])
def list_plants():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store.plants.values())
    status = query_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>", methods=["GET"])
def get_plant(plantId):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success(public(resolve_plant(plantId)))


@bp.route("/treatment-plants/<plantId>/suspend", methods=["POST"])
def suspend_plant(plantId):
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    plant = resolve_plant(plantId)
    if plant["status"] != "LICENSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Suspend requires plant status LICENSED")
    critical_open = any(
        i for i in store.inspections.values()
        if i["plant_id"] == plant["id"]
        and i["severity"] == "CRITICAL"
        and i["status"] == "FINDINGS_ISSUED"
    )
    if not (plant["compliance_score"] <= calc.SUSPEND_THRESHOLD or critical_open):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Suspend is warranted only when compliance_score <= 300 or a CRITICAL inspection is in FINDINGS_ISSUED",
        )
    plant["status"] = "SUSPENDED"
    touch(plant)
    return success(public(plant))


@bp.route("/treatment-plants/<plantId>/reinstate", methods=["POST"])
def reinstate_plant(plantId):
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    plant = resolve_plant(plantId)
    if plant["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Reinstate requires plant status SUSPENDED")
    open_inspections = [
        i for i in store.inspections.values()
        if i["plant_id"] == plant["id"] and i["status"] in INSPECTION_OPEN_STATES
    ]
    if open_inspections:
        raise ApiError(ERR_INVALID_STATE, 409, "All open QualityInspections must reach CLOSED_PASS before reinstatement")
    if plant["hazardous_waste_liability_cents"] != 0:
        raise ApiError(ERR_INVALID_STATE, 409, "Hazardous-waste liability must be settled to zero before reinstatement")
    plant["status"] = "LICENSED"
    touch(plant)
    return success(public(plant))


@bp.route("/treatment-plants/<plantId>/revoke", methods=["POST"])
def revoke_plant(plantId):
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    plant = resolve_plant(plantId)
    if plant["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Revoke requires plant status SUSPENDED")
    if plant["compliance_score"] != 0:
        raise ApiError(ERR_INVALID_STATE, 409, "Revoke requires compliance_score == 0")
    plant["status"] = "REVOKED"
    touch(plant)
    # Cascade: every cylinder decommissioned; every non-terminal charge scrapped.
    for cyl in store.cylinders.values():
        if cyl["plant_id"] == plant["id"] and cyl["status"] != "DECOMMISSIONED":
            cyl["status"] = "DECOMMISSIONED"
            touch(cyl)
    for charge in store.charges.values():
        if charge["plant_id"] == plant["id"] and charge["status"] not in CHARGE_TERMINAL_STATES:
            charge["status"] = "SCRAPPED"
            touch(charge)
            for piece in store.pieces.values():
                if piece["charge_id"] == charge["id"] and piece["status"] not in ("RELEASED", "SCRAPPED"):
                    piece["status"] = "SCRAPPED"
                    touch(piece)
    return success(public(plant))


@bp.route("/treatment-plants/<plantId>/settle-liability", methods=["POST"])
def settle_liability(plantId):
    _, role = authenticate()
    authorize(role, ["AccountsReceivable"])
    plant = resolve_plant(plantId)
    plant["hazardous_waste_liability_cents"] = 0
    touch(plant)
    return success(public(plant))


# --- FK reverse-reachability sub-resources under TreatmentPlant ---

@bp.route("/treatment-plants/<plantId>/cylinders", methods=["GET"])
def list_plant_cylinders(plantId):
    _, role = authenticate()
    authorize(role, ["PlantOperator", "LabTechnician", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer"])
    plant = resolve_plant(plantId)
    items = [c for c in store.cylinders.values() if c["plant_id"] == plant["id"]]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/preservatives", methods=["GET"])
def list_plant_preservatives(plantId):
    _, role = authenticate()
    authorize(role, ["LabTechnician", "PlantOperator", "QualityManager", "ComplianceOfficer"])
    plant = resolve_plant(plantId)
    items = [p for p in store.preservatives.values() if p["plant_id"] == plant["id"]]
    status = query_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/inspections", methods=["GET"])
def list_plant_inspections(plantId):
    _, role = authenticate()
    authorize(role, ["QualityAgencyInspector", "ComplianceOfficer", "QualityManager", "PlantOperator", "LabTechnician"])
    plant = resolve_plant(plantId)
    items = [i for i in store.inspections.values() if i["plant_id"] == plant["id"]]
    status = query_filter("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    severity = query_filter("severity")
    if severity is not None:
        items = [i for i in items if i["severity"] == severity]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/charges", methods=["GET"])
def list_plant_charges(plantId):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    plant = resolve_plant(plantId)
    items = [c for c in store.charges.values() if c["plant_id"] == plant["id"]]
    for param in ("status", "use_category", "customer_id", "cylinder_id"):
        value = query_filter(param)
        if value is not None:
            items = [c for c in items if c.get(param) == value]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)
