"""Medication error report endpoint (freestanding)."""
from db import LOCK, get_db
from errors import APIError
from helpers import new_entity, require_body, require_enum, require_field
from middleware import require_roles
from response import success
from services import audit


ERR_TYPE = {"WRONG_DRUG", "WRONG_DOSE", "WRONG_TIME", "INTERACTION", "OTHER"}
SEVERITY = {"MINOR", "MODERATE", "SEVERE"}


def register(app):

    @app.post("/medication-errors")
    @require_roles("Nurse", "Supervisor")
    def create_med_error(user_id, role):
        body = require_body()
        administration_id = body.get("administration_id")
        prescription_id = body.get("prescription_id")
        elder_id = require_field(body, "elder_id", str)
        error_type = require_enum(body, "error_type", ERR_TYPE)
        severity = require_enum(body, "severity", SEVERITY)
        description = require_field(body, "description", str)
        with LOCK:
            db = get_db()
            if db.elders.get(elder_id) is None:
                raise APIError("ERR_FK_NOT_FOUND", f"Elder {elder_id} not found", 404)
            if administration_id and db.administrations.get(administration_id) is None:
                raise APIError("ERR_FK_NOT_FOUND",
                               f"Administration {administration_id} not found", 404)
            if prescription_id and db.prescriptions.get(prescription_id) is None:
                raise APIError("ERR_FK_NOT_FOUND",
                               f"Prescription {prescription_id} not found", 404)
            err = new_entity({
                "administration_id": administration_id,
                "prescription_id": prescription_id,
                "elder_id": elder_id,
                "error_type": error_type,
                "severity": severity,
                "description": description,
            }, versioned=False)
            db.medication_errors[err["id"]] = err
            # An audit entry on the relevant administration if any
            if administration_id:
                audit.log(role, user_id, "MedicationAdministration", administration_id,
                          "ERROR_REPORT", None, None)
            return success(dict(err), status=201)
