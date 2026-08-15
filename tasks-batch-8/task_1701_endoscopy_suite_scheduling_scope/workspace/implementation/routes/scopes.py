"""Scope registry and scope-lifecycle endpoints (PRD 3.1, 3.6, 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_SCOPE_NOT_FOUND,
    ERR_SERIAL_NUMBER_EXISTS,
    ERR_SCOPE_NOT_REPROCESSABLE,
    ERR_SCOPE_NOT_RETIRABLE,
    ERR_STALE_SCOPE_VERSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_NO_OPEN_QUARANTINE,
    ERR_RECULTURE_NOT_NEGATIVE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, open_quarantine_case_for_scope, public_scope, touch
from util import now
from validate import get_body, req_enum, req_int, req_str, require_path_resource

bp = Blueprint("scopes", __name__)

SCOPE_TYPES = {"COLONOSCOPE", "GASTROSCOPE", "SIGMOIDOSCOPE"}


@bp.post("/endoscopy/scopes")
def create_scope():
    authorized(["UnitAdmin"])
    body = get_body()
    serial_number = req_str(body, "serial_number")
    scope_type = req_enum(body, "scope_type", SCOPE_TYPES)
    # Rung 10 (uniqueness): serial_number unique
    for s in db["scopes"].values():
        if s["serial_number"] == serial_number:
            raise_error(ERR_SERIAL_NUMBER_EXISTS, f"duplicate serial_number: {serial_number}")
    rec = new_record("scopes", {
        "serial_number": serial_number,
        "scope_type": scope_type,
        "status": "AVAILABLE",
        "storage_expires_at": None,
        "awaiting_reprocess_since": None,
    })
    return success_object(public_scope(rec), status=201)


@bp.get("/endoscopy/scopes")
def list_scopes():
    return list_response("scopes", {
        "scope_type": request.args.get("scope_type"),
        "status": request.args.get("status"),
    })


@bp.get("/endoscopy/scopes/<rid>")
def get_scope(rid):
    return get_one("scopes", rid, ERR_SCOPE_NOT_FOUND)


@bp.post("/endoscopy/scopes/<rid>/send-to-reprocessing")
def send_to_reprocessing(rid):
    authorized(["ReprocessingTechnician", "UnitAdmin"])
    scope = require_path_resource("scopes", rid, ERR_SCOPE_NOT_FOUND)
    # Rung 7: only AVAILABLE scopes may be sent manually.
    if scope["status"] != "AVAILABLE":
        raise_error(ERR_SCOPE_NOT_REPROCESSABLE,
                    "manual send-to-reprocessing requires status AVAILABLE")
    scope["status"] = "AWAITING_REPROCESS"
    scope["awaiting_reprocess_since"] = now()
    touch(scope)
    return success_object(public_scope(scope))


@bp.post("/endoscopy/scopes/<rid>/retire")
def retire_scope(rid):
    authorized(["UnitAdmin"])
    scope = require_path_resource("scopes", rid, ERR_SCOPE_NOT_FOUND)
    # Rung 7: retirable from AVAILABLE, AWAITING_REPROCESS, QUARANTINED only.
    if scope["status"] not in ("AVAILABLE", "AWAITING_REPROCESS", "QUARANTINED"):
        raise_error(ERR_SCOPE_NOT_RETIRABLE,
                    "retire requires status AVAILABLE, AWAITING_REPROCESS or QUARANTINED")
    scope["status"] = "OUT_OF_SERVICE"
    # Cascade: any open quarantine case settles at SCOPE_RETIRED.
    for case in db["quarantine_cases"].values():
        if case["scope_id"] == scope["id"] and case["status"] in ("OPEN", "RECULTURING"):
            case["status"] = "SCOPE_RETIRED"
            case["resolved_at"] = now()
            touch(case)
    touch(scope)
    return success_object(public_scope(scope))


@bp.post("/endoscopy/scopes/<rid>/release-quarantine")
def release_quarantine(rid):
    caller = authorized(["InfectionControlNurse"])
    scope = require_path_resource("scopes", rid, ERR_SCOPE_NOT_FOUND)
    body = get_body()
    expected_scope_version = req_int(body, "expected_scope_version")
    # Rung 5 (OCC): evaluated before any business rule once the scope exists.
    if expected_scope_version != scope["version"]:
        raise_error(ERR_STALE_SCOPE_VERSION,
                    "expected_scope_version does not match the scope's current version")
    case = open_quarantine_case_for_scope(scope["id"])
    # Rung 6 (segregation of duties): the releaser must not be the technician
    # who performed the reculture cycle.
    if case is not None and case.get("reculture_cycle_id"):
        cycle = db["reprocessing_cycles"].get(case["reculture_cycle_id"])
        if cycle is not None and cycle["technician_id"] == caller.user_id:
            raise_error(ERR_SEGREGATION_OF_DUTIES,
                        "quarantine releaser must differ from the reculture technician")
    # Rung 7: an open (OPEN or RECULTURING) case must exist for the scope.
    if case is None:
        raise_error(ERR_NO_OPEN_QUARANTINE,
                    "no OPEN/RECULTURING quarantine case exists for this scope")
    # A NEGATIVE culture must exist against the case's reculture cycle.
    reculture_cycle_id = case.get("reculture_cycle_id")
    negative_exists = any(
        c.get("reprocessing_cycle_id") == reculture_cycle_id
        and c.get("result") == "NEGATIVE"
        for c in db["culture_tests"].values()
    ) if reculture_cycle_id else False
    if not negative_exists:
        raise_error(ERR_RECULTURE_NOT_NEGATIVE,
                    "no NEGATIVE culture exists on the quarantine case's reculture cycle")
    case["status"] = "RELEASED"
    case["released_by"] = caller.user_id
    case["resolved_at"] = now()
    touch(case)
    scope["status"] = "AVAILABLE"
    touch(scope)
    return success_object(public_scope(scope))
