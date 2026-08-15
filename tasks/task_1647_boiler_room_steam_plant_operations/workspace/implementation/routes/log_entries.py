"""BoilerLogEntry endpoints: record, list/get, verify (OCC + SoD + ledger),
void (DRAFT by Operator; VERIFIED compensating by PlantManager).

Pipeline (PRD 2.7) for verify:
auth(1) -> role(2) -> existence(3) -> schema(400) -> state(4)
-> operator license(8) -> SoD(10) -> fuel underflow(18) -> OCC(22).
"""
from flask import Blueprint, request

import resolve
import store
from auth import authenticate, authorize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REFERENCED_NOT_FOUND,
    ERR_SOD_VERIFICATION,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
)
from services import (
    apply_entry_verify,
    apply_entry_void,
    check_verify_underflow,
    check_void_underflow,
    entries_of,
    log_entry_json,
    require_active_operator,
    require_jurisdiction,
)
from util import (
    body_json,
    list_response,
    new_journal_record,
    req_dt,
    req_num,
    req_str,
    success_object,
)

bp = Blueprint("log_entries", __name__)

READERS = ["PlantManager", "Operator"]


@bp.post("/plants/<plantId>/boilers/<boilerId>/log-entries")
def create_log_entry(plantId, boilerId):
    uid, role = authenticate()
    authorize(role, ["Operator"])
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    body = body_json()
    recorded_by = req_str(body, "recorded_by_operator_id")
    recorded_at = req_dt(body, "recorded_at")
    header_reading = req_num(body, "header_pressure_reading_psi")
    steam = req_num(body, "steam_generated_lb")
    fuel = req_num(body, "fuel_burned_gal")
    feedwater = req_num(body, "feedwater_intake_gal")
    blowdown = req_num(body, "blowdown_gal")
    # license(8) + jurisdiction(9) on the calling operator
    op = require_active_operator(uid)
    require_jurisdiction(op, plant)
    # referential integrity(11)
    if store.operators.get(recorded_by) is None:
        raise_err(ERR_REFERENCED_NOT_FOUND,
                  "recorded_by_operator_id does not reference an existing operator")
    rec = new_journal_record()
    rec.update({
        "boiler_id": boiler["id"],
        "recorded_by_operator_id": recorded_by,
        "recorded_at": recorded_at,
        "header_pressure_reading_psi": header_reading,
        "steam_generated_lb": steam,
        "fuel_burned_gal": fuel,
        "feedwater_intake_gal": feedwater,
        "blowdown_gal": blowdown,
        "status": "DRAFT",
    })
    store.log_entries[rec["id"]] = rec
    return success_object(log_entry_json(rec), 201)


@bp.get("/plants/<plantId>/boilers/<boilerId>/log-entries/<entryId>")
def get_log_entry(plantId, boilerId, entryId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    rec = resolve.log_entry(boiler, entryId)
    return success_object(log_entry_json(rec))


@bp.get("/plants/<plantId>/boilers/<boilerId>/log-entries")
def list_log_entries(plantId, boilerId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    recs = entries_of(boiler["id"])
    status = request.args.get("status")
    if status is not None:
        recs = [e for e in recs if e["status"] == status]
    return list_response(recs, log_entry_json)


@bp.post("/plants/<plantId>/boilers/<boilerId>/log-entries/<entryId>/verify")
def verify_log_entry(plantId, boilerId, entryId):
    uid, role = authenticate()
    authorize(role, ["Operator"])
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    entry = resolve.log_entry(boiler, entryId)
    body = body_json()
    # schema: expected_boiler_version is non-optional (PRD 2.8)
    expected = body.get("expected_boiler_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_boiler_version is required and must be an integer")
    # state(4): entry must be DRAFT; boiler must be in a verifiable ops state
    if entry["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT entry can be verified")
    if boiler["ops_status"] not in ("ONLINE", "BANKING", "STANDBY", "WARMING"):
        raise_err(ERR_INVALID_STATE,
                  "Entries on a TRIPPED or DECOMMISSIONED boiler cannot be verified")
    # operator license(8)
    require_active_operator(uid)
    # segregation of duties(10): verifier != recorder
    if uid == entry["recorded_by_operator_id"]:
        raise_err(ERR_SOD_VERIFICATION,
                  "The verifying operator must not be the recording operator")
    # fuel underflow(18)
    check_verify_underflow(plant, entry)
    # OCC(22): stale expected_boiler_version rejected last
    if expected != boiler["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_boiler_version does not match the boiler's current version")
    apply_entry_verify(plant, boiler, entry, uid)
    return success_object(log_entry_json(entry))


@bp.post("/plants/<plantId>/boilers/<boilerId>/log-entries/<entryId>/void")
def void_log_entry(plantId, boilerId, entryId):
    uid, role = authenticate()
    authorize(role, ["PlantManager", "Operator"])
    plant = resolve.plant(plantId)
    boiler = resolve.boiler(plant, boilerId)
    entry = resolve.log_entry(boiler, entryId)
    # state(4): VERIFIED and VOIDED are terminal for void purposes
    if entry["status"] not in ("DRAFT", "VERIFIED"):
        raise_err(ERR_INVALID_STATE, "Entry is already VOIDED")
    # duty segregation(17): VERIFIED voids are PlantManager-only
    if entry["status"] == "VERIFIED" and role != "PlantManager":
        raise_err(ERR_UNAUTHORIZED,
                  "Only a PlantManager may void a VERIFIED log entry")
    if entry["status"] == "DRAFT" and role == "Operator":
        # license(8): a draft void still requires an ACTIVE caller license
        require_active_operator(uid)
    if entry["status"] == "VERIFIED":
        # fuel underflow(18)
        check_void_underflow(plant, entry)
        apply_entry_void(plant, boiler, entry, uid)
    else:
        entry["status"] = "VOIDED"  # DRAFT entries were never applied
    return success_object(log_entry_json(entry))
