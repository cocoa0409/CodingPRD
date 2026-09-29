"""Steel heats and mill-certificate adjudication (PRD 3.2)."""

from flask import Blueprint, g

import enums
from db import db, new_record, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok
from services.cascades import (
    cascade_heat_cleared,
    cascade_heat_counterfeit,
    cascade_heat_rejected,
)
from services.lookup import require_unique, steel_heat_or_404
from validate import field_enum, field_num, field_str

bp = Blueprint("steel_heats", __name__)

CREATE_ROLES = ("ProcessEngineer", "QualityInspector", "PlantAdmin")


@bp.post("/steel-heats")
@endpoint(CREATE_ROLES)
def create_steel_heat():
    body = g.body
    fields = {
        "heat_number": field_str(body, "heat_number"),
        "mill_code": field_str(body, "mill_code"),
        "grade": field_enum(body, "grade", enums.STEEL_GRADES),
        "carbon_pct": field_num(body, "carbon_pct"),
        "boron_ppm": field_num(body, "boron_ppm", required=False, default=None),
        "gross_mass_kg": field_num(body, "gross_mass_kg", exclusive_min=0),
        "mill_cert_serial": field_str(body, "mill_cert_serial"),
    }
    if fields["boron_ppm"] is None:
        fields["boron_ppm"] = 0

    require_unique(
        "steel_heats",
        "mill_cert_serial",
        fields["mill_cert_serial"],
        "ERR_DUPLICATE_MILL_CERT_SERIAL",
    )
    require_unique("steel_heats", "heat_number", fields["heat_number"])

    fields.update(
        {
            "cert_status": "PENDING",
            "lab_report_reference": None,
            "verified_at": None,
            "verified_by_user_id": None,
            "counterfeit_reason": None,
        }
    )
    heat = new_record(fields)
    db.steel_heats[heat["id"]] = heat
    return created(heat)


@bp.get("/steel-heats/<heat_id>")
@endpoint(ANY_ROLE)
def get_steel_heat(heat_id):
    return ok(steel_heat_or_404(heat_id))


@bp.post("/steel-heats/<heat_id>/verify-mill-cert")
@endpoint("QualityInspector")
def verify_mill_cert(heat_id):
    body = g.body
    outcome = field_enum(body, "outcome", enums.VERIFY_OUTCOMES)
    serial = field_str(body, "mill_cert_serial")
    lab_report_reference = field_str(body, "lab_report_reference", allow_empty=True)

    heat = steel_heat_or_404(heat_id)
    if heat["cert_status"] not in ("PENDING", "SUSPECTED_COUNTERFEIT"):
        raise ApiError("ERR_INVALID_HEAT_STATE")

    previous = heat["cert_status"]

    if outcome == "VERIFIED":
        if serial != heat["mill_cert_serial"]:
            raise ApiError("ERR_MILL_CERT_SERIAL_MISMATCH")
        heat["cert_status"] = "VERIFIED"
        heat["verified_at"] = db.now_iso()
        heat["verified_by_user_id"] = g.user_id
        heat["lab_report_reference"] = lab_report_reference
        touch(heat)
        if previous == "SUSPECTED_COUNTERFEIT":
            cascade_heat_cleared(heat)
    else:
        heat["cert_status"] = "REJECTED"
        heat["lab_report_reference"] = lab_report_reference
        touch(heat)
        if previous == "PENDING":
            cascade_heat_rejected(heat)

    return ok(heat)


@bp.post("/steel-heats/<heat_id>/flag-counterfeit")
@endpoint("QualityManager")
def flag_counterfeit(heat_id):
    reason = field_str(g.body, "reason", allow_empty=True)

    heat = steel_heat_or_404(heat_id)
    if heat["cert_status"] not in ("PENDING", "VERIFIED"):
        raise ApiError("ERR_INVALID_HEAT_STATE")

    heat["cert_status"] = "SUSPECTED_COUNTERFEIT"
    heat["counterfeit_reason"] = reason
    touch(heat)
    cascade_heat_counterfeit(heat)
    return ok(heat)
