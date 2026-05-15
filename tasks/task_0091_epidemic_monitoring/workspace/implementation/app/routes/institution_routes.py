"""ReportingInstitution endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..constants import INSTITUTION_TYPES
from ..errors import ApiError
from ..store import common_fields_create, get_store
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/institutions",
        view_func=require_auth("CDCSupervisor")(with_lock(create_institution)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/institutions/<inst_id>",
        view_func=require_auth(
            "CDCSupervisor",
            "CDCDispatcher",
            "CDCTracer",
            "HospitalReporter",
            "LabTechnician",
            "SupplyManager",
            "PressOfficer",
            "RiskExpert",
        )(with_lock(get_institution)),
        methods=["GET"],
    )


def _validate_institution_code(code: str) -> None:
    if not isinstance(code, str) or not code.isalnum():
        raise ApiError("ERR_INVALID_INPUT", "institution_code must be alphanumeric.")
    if not (4 <= len(code) <= 12):
        raise ApiError("ERR_INVALID_INPUT", "institution_code must be 4-12 chars.")


def create_institution():
    body = get_json_body()
    store = get_store()

    code = body.get("institution_code")
    inst_type = body.get("institution_type")
    district = body.get("district_code")
    if not code or not inst_type or not district:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    _validate_institution_code(code)
    if inst_type not in INSTITUTION_TYPES:
        raise ApiError(
            "ERR_INVALID_INPUT", f"institution_type must be one of {sorted(INSTITUTION_TYPES)}."
        )

    # Unique by institution_code
    for inst in store.institutions.values():
        if inst.get("institution_code") == code:
            raise ApiError("ERR_INVALID_INPUT", f"institution_code {code!r} already exists.")

    row = {
        **common_fields_create(),
        "institution_code": code,
        "institution_type": inst_type,
        "district_code": district,
        "status": "ACTIVE",
    }
    store.institutions[row["id"]] = row
    return ok(row, status=201)


def get_institution(inst_id: str):
    store = get_store()
    inst = store.institutions.get(inst_id)
    if not inst:
        raise ApiError("ERR_NOT_FOUND", f"Institution {inst_id} not found.")
    return ok(inst)
