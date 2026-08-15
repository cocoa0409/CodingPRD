"""Pole and WattageAudit endpoints (PRD 3.1, 3.2)."""
from flask import Blueprint

from db import new_record, store, touch
from domain import (
    audit_retroactive_adjustment, program_of_audit, program_of_pole,
    require_active, ser_audit, ser_pole,
)
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from validate import get_body, opt_str, req_int, req_str, req_enum
from routes.common import list_endpoint, require_record

bp = Blueprint("poles", __name__)

PM = ["ProgramManager"]
FS = ["FieldSupervisor"]
BA = ["BillingAnalyst"]
OWNERSHIP = ["MUNICIPAL", "UTILITY_OWNED"]
FIXTURE_CLASSES = ["COBRA_HEAD", "FLOOD", "POST_TOP", "DECORATIVE"]


@bp.route("/streetlights/poles", methods=["POST"])
@locked
def create_pole():
    caller = get_caller()
    body = get_body()
    district_id = req_str(body, "district_id")
    pole_number = req_str(body, "pole_number")
    ownership_type = req_enum(body, "ownership_type", OWNERSHIP)
    fixture_class = req_enum(body, "fixture_class", FIXTURE_CLASSES)
    nameplate = req_int(body, "nameplate_wattage", positive=True)
    require_roles(caller, PM)
    district = store.districts.get(district_id)
    if district is None:
        raise_error("ERR_DISTRICT_NOT_FOUND", f"district not found: {district_id}")
    require_active(store.programs.get(district["program_id"]))
    program_id = district["program_id"]
    for p in store.poles.values():
        pd = store.districts.get(p["district_id"])
        if pd and pd["program_id"] == program_id and p["pole_number"] == pole_number:
            raise_error("ERR_DUPLICATE_POLE_NUMBER", "pole_number must be unique per program")
    rec = new_record("poles", {
        "district_id": district_id,
        "pole_number": pole_number,
        "ownership_type": ownership_type,
        "fixture_class": fixture_class,
        "nameplate_wattage": nameplate,
        "effective_wattage": nameplate,
        "pre_conversion_wattage": None,
        "led_wattage": None,
        "led_in_service_date": None,
        "pre_repair_status": None,
        "status": "SURVEYED",
    })
    return success_object(ser_pole(rec), status=201)


@bp.route("/streetlights/poles", methods=["GET"])
@locked
def list_poles():
    return list_endpoint("poles", ser_pole, ["district_id", "status", "ownership_type"])


@bp.route("/streetlights/poles/<pid>", methods=["GET"])
@locked
def get_pole(pid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("poles", pid, "ERR_POLE_NOT_FOUND")
    return success_object(ser_pole(rec))


@bp.route("/streetlights/poles/<pid>/attest-nameplate", methods=["POST"])
@locked
def attest_nameplate(pid):
    caller = get_caller()
    require_roles(caller, BA)
    pole = require_record("poles", pid, "ERR_POLE_NOT_FOUND")
    require_active(program_of_pole(pole))
    if pole["status"] == "EXEMPT":
        raise_error("ERR_POLE_EXEMPT", "operation not permitted on an EXEMPT pole")
    if pole["ownership_type"] != "UTILITY_OWNED":
        raise_error("ERR_ATTEST_NOT_PERMITTED_MUNICIPAL",
                    "nameplate attestation is permitted only for UTILITY_OWNED poles")
    if pole["status"] != "SURVEYED":
        raise_error("ERR_INVALID_REQUEST", "nameplate attestation requires a SURVEYED pole")
    pole["status"] = "AUDIT_CLEARED"
    touch(pole)
    return success_object(ser_pole(pole))


# ---------------------------------------------------------------------------
# Wattage audits
# ---------------------------------------------------------------------------

@bp.route("/streetlights/poles/<pole_id>/audits", methods=["POST"])
@locked
def submit_audit(pole_id):
    caller = get_caller()
    body = get_body()
    audited_wattage = req_int(body, "audited_wattage", positive=True)
    auditor_notes = opt_str(body, "auditor_notes", default="")
    expected_pole_version = req_int(body, "expected_pole_version")
    require_roles(caller, FS)
    pole = require_record("poles", pole_id, "ERR_POLE_NOT_FOUND")
    # Stage 7 OCC (before program-lifecycle and business checks, PRD 2.10).
    if expected_pole_version != pole["version"]:
        raise_error("ERR_STALE_VERSION", "expected_pole_version does not match the pole's version")
    require_active(program_of_pole(pole))
    if pole["status"] == "EXEMPT":
        raise_error("ERR_POLE_EXEMPT", "operation not permitted on an EXEMPT pole")
    for a in store.audits.values():
        if a["pole_id"] == pole["id"] and a["status"] == "SUBMITTED":
            raise_error("ERR_AUDIT_ALREADY_PENDING", "pole already holds a SUBMITTED audit")
    if pole["ownership_type"] != "MUNICIPAL":
        raise_error("ERR_AUDIT_NOT_PERMITTED_UTILITY",
                    "wattage audits are permitted only for MUNICIPAL poles")
    rec = new_record("audits", {
        "pole_id": pole["id"],
        "audited_wattage": audited_wattage,
        "auditor_notes": auditor_notes,
        "revision_count": 0,
        "decided_by_user_id": None,
        "status": "SUBMITTED",
    })
    # Submission itself bumps the pole's version (PRD 3.2).
    touch(pole)
    return success_object(ser_audit(rec), status=201)


@bp.route("/streetlights/audits", methods=["GET"])
@locked
def list_audits():
    return list_endpoint("audits", ser_audit, ["pole_id", "status"])


@bp.route("/streetlights/audits/<aid>", methods=["GET"])
@locked
def get_audit(aid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("audits", aid, "ERR_AUDIT_NOT_FOUND")
    return success_object(ser_audit(rec))


@bp.route("/streetlights/audits/<aid>/accept", methods=["POST"])
@locked
def accept_audit(aid):
    caller = get_caller()
    require_roles(caller, PM)
    audit = require_record("audits", aid, "ERR_AUDIT_NOT_FOUND")
    require_active(program_of_audit(audit))
    if audit["status"] != "SUBMITTED":
        raise_error("ERR_AUDIT_NOT_SUBMITTED", "accept requires a SUBMITTED audit")
    pole = store.poles[audit["pole_id"]]
    if pole["status"] == "EXEMPT":
        raise_error("ERR_POLE_EXEMPT", "operation not permitted on an EXEMPT pole")
    for other in store.audits.values():
        if other["pole_id"] == pole["id"] and other["status"] == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    audit["status"] = "ACCEPTED"
    audit["decided_by_user_id"] = caller.user_id
    touch(audit)
    pole["effective_wattage"] = audit["audited_wattage"]
    if pole["status"] == "SURVEYED":
        pole["status"] = "AUDIT_CLEARED"
    touch(pole)
    audit_retroactive_adjustment(pole)
    return success_object(ser_audit(audit))


@bp.route("/streetlights/audits/<aid>/dispute", methods=["POST"])
@locked
def dispute_audit(aid):
    caller = get_caller()
    require_roles(caller, PM)
    audit = require_record("audits", aid, "ERR_AUDIT_NOT_FOUND")
    require_active(program_of_audit(audit))
    if audit["status"] != "SUBMITTED":
        raise_error("ERR_AUDIT_NOT_SUBMITTED", "dispute requires a SUBMITTED audit")
    audit["status"] = "DISPUTED"
    audit["decided_by_user_id"] = caller.user_id
    touch(audit)
    return success_object(ser_audit(audit))


@bp.route("/streetlights/audits/<aid>/resubmit", methods=["POST"])
@locked
def resubmit_audit(aid):
    caller = get_caller()
    body = get_body()
    audited_wattage = req_int(body, "audited_wattage", positive=True)
    auditor_notes = opt_str(body, "auditor_notes", default=None)
    require_roles(caller, FS)
    audit = require_record("audits", aid, "ERR_AUDIT_NOT_FOUND")
    require_active(program_of_audit(audit))
    if audit["status"] != "DISPUTED":
        raise_error("ERR_AUDIT_NOT_SUBMITTED", "resubmit requires a DISPUTED audit")
    audit["audited_wattage"] = audited_wattage
    if auditor_notes is not None:
        audit["auditor_notes"] = auditor_notes
    audit["revision_count"] += 1
    audit["decided_by_user_id"] = None
    audit["status"] = "SUBMITTED"
    touch(audit)
    return success_object(ser_audit(audit))
