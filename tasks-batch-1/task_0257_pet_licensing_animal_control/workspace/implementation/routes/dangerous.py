"""DangerousDogCase endpoints (PRD §3.7, §4)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_owner_match, require_role
from response import object_response
from services import dangerous as case_svc
from services.core import stamp_create
from services.reqs import body, require_enum, require_fields
from services.views import case_view

bp = Blueprint("dangerous", __name__)

ALL_ROLES = {"Owner", "LicensingClerk", "AnimalControlOfficer"}
SEVERITIES = {"BITE", "ATTACK", "NUISANCE"}


@bp.route("/dangerous-dog-cases", methods=["POST"])
def create_case():
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    data = body()
    require_fields(data, ["pet_id", "incident_summary", "severity"])
    require_enum(data["severity"], SEVERITIES, "severity")
    if db.pets.get(data["pet_id"]) is None:
        raise err("ERR_NOT_FOUND", "Pet not found.")
    case = {
        "pet_id": data["pet_id"],
        "incident_summary": data["incident_summary"],
        "severity": data["severity"],
        "status": "REPORTED",
        "surcharge_cents": 0,
    }
    stamp_create(case)
    db.dangerous_dog_cases[case["id"]] = case
    return object_response(case_view(case), status=201)


@bp.route("/dangerous-dog-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    case = db.dangerous_dog_cases.get(case_id)
    if case is None:
        raise err("ERR_NOT_FOUND", "Case not found.")
    return object_response(case_view(case))


def _load(case_id):
    case = db.dangerous_dog_cases.get(case_id)
    if case is None:
        raise err("ERR_NOT_FOUND", "Case not found.")
    return case


@bp.route("/dangerous-dog-cases/<case_id>/investigate", methods=["POST"])
def investigate(case_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    case = _load(case_id)
    case_svc.investigate(case)
    return object_response(case_view(case))


@bp.route("/dangerous-dog-cases/<case_id>/designate", methods=["POST"])
def designate(case_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    case = _load(case_id)
    case_svc.designate(case)
    return object_response(case_view(case))


@bp.route("/dangerous-dog-cases/<case_id>/dismiss", methods=["POST"])
def dismiss(case_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    case = _load(case_id)
    case_svc.dismiss(case)
    return object_response(case_view(case))


@bp.route("/dangerous-dog-cases/<case_id>/appeal", methods=["POST"])
def appeal(case_id):
    user_id, role = authenticate()
    require_role(role, {"Owner"})
    case = _load(case_id)
    pet = db.pets.get(case["pet_id"])
    # ownership: acting Owner owns the Pet (PRD §3.7)
    require_owner_match(role, user_id, pet["owner_id"] if pet else None)
    case_svc.appeal(case)
    return object_response(case_view(case))


@bp.route("/dangerous-dog-cases/<case_id>/overturn", methods=["POST"])
def overturn(case_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    case = _load(case_id)
    case_svc.overturn(case)
    return object_response(case_view(case))


@bp.route("/dangerous-dog-cases/<case_id>/uphold", methods=["POST"])
def uphold(case_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    case = _load(case_id)
    case_svc.uphold(case)
    return object_response(case_view(case))
