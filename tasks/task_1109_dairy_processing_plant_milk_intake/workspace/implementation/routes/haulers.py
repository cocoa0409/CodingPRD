"""Hauler onboarding (PRD 3.1)."""
from flask import Blueprint

from db import STORE, base_record
from errors import not_found
from helpers import body, req_dt, req_str
from middleware import require_roles
from response import success_object
from services import ser_hauler

bp = Blueprint("haulers", __name__)


@bp.route("/dairy/haulers", methods=["POST"])
def create_hauler():
    require_roles("PlantController")
    data = body()
    hauler_code = req_str(data, "hauler_code")
    company_name = req_str(data, "company_name")
    license_expires_at = req_dt(data, "license_expires_at")
    rec = base_record()
    rec.update({
        "hauler_code": hauler_code,
        "company_name": company_name,
        "license_expires_at": license_expires_at,
        "status": "ACTIVE",
    })
    STORE["haulers"][rec["id"]] = rec
    return success_object(ser_hauler(rec), 201)


@bp.route("/dairy/haulers/<hid>", methods=["GET"])
def get_hauler(hid):
    require_roles("PlantController", "QualityAssuranceManager")
    hauler = STORE["haulers"].get(hid)
    if hauler is None:
        raise not_found("Hauler not found")
    return success_object(ser_hauler(hauler))
