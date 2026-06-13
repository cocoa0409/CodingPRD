"""VaccinationRecord endpoints (PRD §3.1, §4). Immutable proof artifacts."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from services.core import stamp_create
from services.reqs import body, require_enum, require_fields
from services.views import vaccination_view

bp = Blueprint("vaccinations", __name__)

ALL_ROLES = {"Owner", "LicensingClerk", "AnimalControlOfficer"}
VACCINE_TYPES = {"RABIES", "DHPP", "FVRCP"}


@bp.route("/vaccination-records", methods=["POST"])
def create_vaccination():
    _, role = authenticate()
    require_role(role, {"Owner", "LicensingClerk"})
    data = body()
    require_fields(data, ["pet_id", "vaccine_type", "administered_on",
                          "expires_on", "vet_license_no"])
    require_enum(data["vaccine_type"], VACCINE_TYPES, "vaccine_type")
    if db.pets.get(data["pet_id"]) is None:
        raise err("ERR_NOT_FOUND", "Pet not found.")
    record = {
        "pet_id": data["pet_id"],
        "vaccine_type": data["vaccine_type"],
        "administered_on": data["administered_on"],
        "expires_on": data["expires_on"],
        "vet_license_no": data["vet_license_no"],
    }
    stamp_create(record, common_fields=False)  # immutable: id + created_at only
    db.vaccination_records[record["id"]] = record
    return object_response(vaccination_view(record), status=201)


@bp.route("/vaccination-records/<record_id>", methods=["GET"])
def get_vaccination(record_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    record = db.vaccination_records.get(record_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Vaccination record not found.")
    return object_response(vaccination_view(record))
