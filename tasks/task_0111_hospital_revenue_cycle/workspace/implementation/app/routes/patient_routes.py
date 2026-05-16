"""Patient endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.serializers import serialize_patient
from ..services.validation import (
    get_patient_or_404,
    require_str,
    validate_mrn,
)
from ..store import LOCK, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok, ok


def register(app: Flask) -> None:
    @app.route("/patients", methods=["POST"])
    @require_auth("RegistrationClerk")
    def create_patient():
        body = get_json_body()
        mrn = require_str(body, "mrn")
        full_name = require_str(body, "full_name")
        dob = require_str(body, "date_of_birth")
        validate_mrn(mrn)
        store = get_store()
        with LOCK:
            if mrn in store.mrn_to_patient:
                raise ApiError("ERR_INVALID_INPUT", f"MRN {mrn!r} already exists.")
            base = common_fields_create()
            patient = {
                **base,
                "mrn": mrn,
                "full_name": full_name,
                "date_of_birth": dob,
                "status": "ACTIVE",
            }
            store.patients[patient["id"]] = patient
            store.mrn_to_patient[mrn] = patient["id"]
        return created(serialize_patient(patient))

    @app.route("/patients/<patient_id>", methods=["GET"])
    @require_auth("RegistrationClerk", "ChargeCaptureClerk", "Coder", "Biller")
    def get_patient(patient_id):
        patient = get_patient_or_404(patient_id)
        return ok(serialize_patient(patient))

    @app.route("/patients", methods=["GET"])
    @require_auth("RegistrationClerk", "ChargeCaptureClerk", "Coder", "Biller")
    def list_patients():
        limit, offset = parse_limit_offset()
        mrn_filter = parse_optional_str("mrn")
        store = get_store()
        items = list(store.patients.values())
        if mrn_filter is not None:
            items = [p for p in items if p["mrn"] == mrn_filter]
        items.sort(key=lambda p: p["created_at"])
        sliced, pag = paginate(items, limit, offset)
        return list_ok([serialize_patient(p) for p in sliced], pag)
