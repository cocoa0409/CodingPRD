"""Employer, Claimant, WageRecord, EmergencyExtensionProgram endpoints."""
from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_role
from response import object_response, array_response
from validate import (
    as_bool, as_int, as_number, as_string, check_occ, get_json_body, paginate,
    serialize, validate_iso_date, validate_quarter, validate_ssn_last4,
)

bp = Blueprint("parties", __name__)


# ===========================================================================
# Employer
# ===========================================================================
@bp.route("/ui/employers", methods=["POST"])
def create_employer():
    p = authenticate()
    require_role(p, {"ProgramAdmin"})
    body = get_json_body()
    legal_name = as_string(body, "legal_name")
    state_account_number = as_string(body, "state_account_number")
    experience_rate = as_number(body, "experience_rate", minimum=0.0, maximum=0.12)
    reserve_opening = as_int(body, "reserve_opening_balance_cents", minimum=0)

    # Uniqueness (priority 6)
    for e in db.employers.values():
        if e["state_account_number"] == state_account_number:
            raise err("ERR_DUPLICATE_RESOURCE", "state_account_number already exists.")

    rec = {
        "legal_name": legal_name,
        "state_account_number": state_account_number,
        "experience_rate": experience_rate,
        "reserve_opening_balance_cents": reserve_opening,
        "reserve_account_balance_cents": reserve_opening,
        "charge_protest_count": 0,
    }
    db.stamp_create(rec)
    db.employers[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/employers/<eid>", methods=["GET"])
def get_employer(eid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Employer"})
    rec = db.employers.get(eid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Employer not found.")
    return object_response(serialize(rec))


@bp.route("/ui/employers", methods=["GET"])
def list_employers():
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator"})
    page, limit, offset, total = paginate(list(db.employers.values()))
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/employers/<eid>/charges", methods=["GET"])
def list_employer_charges(eid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Employer"})
    if eid not in db.employers:
        raise err("ERR_NOT_FOUND", "Employer not found.")
    items = [c for c in db.employer_charges.values() if c["employer_id"] == eid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/employers/<eid>/wage-records", methods=["GET"])
def list_employer_wage_records(eid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator"})
    if eid not in db.employers:
        raise err("ERR_NOT_FOUND", "Employer not found.")
    items = [w for w in db.wage_records.values() if w["employer_id"] == eid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/employers/<eid>/work-search-contacts", methods=["GET"])
def list_employer_work_search_contacts(eid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator"})
    if eid not in db.employers:
        raise err("ERR_NOT_FOUND", "Employer not found.")
    items = [w for w in db.work_search_contacts.values()
             if w.get("employer_id") == eid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


# ===========================================================================
# Claimant
# ===========================================================================
@bp.route("/ui/claimants", methods=["POST"])
def create_claimant():
    p = authenticate()
    require_role(p, {"Anonymous", "ProgramAdmin"})
    body = get_json_body()
    full_name = as_string(body, "full_name")
    ssn_last4 = validate_ssn_last4(body.get("ssn_last4"))
    dob = as_string(body, "date_of_birth")
    validate_iso_date(dob, "date_of_birth")
    is_able = as_bool(body, "is_able_and_available", required=False, default=True)

    rec = {
        "full_name": full_name,
        "ssn_last4": ssn_last4,
        "date_of_birth": dob,
        "is_able_and_available": is_able,
    }
    db.stamp_create(rec)
    db.claimants[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/claimants/<cid>", methods=["GET"])
def get_claimant(cid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant"})
    rec = db.claimants.get(cid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Claimant not found.")
    return object_response(serialize(rec))


@bp.route("/ui/claimants/<cid>/wage-records", methods=["GET"])
def list_claimant_wage_records(cid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant"})
    if cid not in db.claimants:
        raise err("ERR_NOT_FOUND", "Claimant not found.")
    items = [w for w in db.wage_records.values() if w["claimant_id"] == cid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/claimants/<cid>", methods=["PATCH"])
def patch_claimant(cid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Claimant"})
    rec = db.claimants.get(cid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Claimant not found.")
    body = get_json_body()
    is_able = as_bool(body, "is_able_and_available")
    check_occ(body, "expected_claimant_version", rec, "ERR_STALE_VERSION")
    rec["is_able_and_available"] = is_able
    db.touch(rec)
    return object_response(serialize(rec))


# ===========================================================================
# WageRecord
# ===========================================================================
@bp.route("/ui/wage-records", methods=["POST"])
def create_wage_record():
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Employer"})
    body = get_json_body()
    claimant_id = as_string(body, "claimant_id")
    employer_id = as_string(body, "employer_id")
    # Existence (404) then reference type (422). Both FKs are strings to
    # specific collections; a missing target is NOT_FOUND.
    if claimant_id not in db.claimants:
        raise err("ERR_NOT_FOUND", "claimant_id not found.")
    if employer_id not in db.employers:
        raise err("ERR_NOT_FOUND", "employer_id not found.")
    calendar_quarter = validate_quarter(body.get("calendar_quarter"))
    gross = as_int(body, "gross_wages_cents", minimum=0)
    is_disputed = as_bool(body, "is_disputed", required=False, default=False)

    rec = {
        "claimant_id": claimant_id,
        "employer_id": employer_id,
        "calendar_quarter": calendar_quarter,
        "gross_wages_cents": gross,
        "is_disputed": is_disputed,
    }
    db.stamp_create(rec, with_version=False)
    db.wage_records[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/wage-records", methods=["GET"])
def list_wage_records():
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator"})
    items = list(db.wage_records.values())
    from flask import request
    claimant_id = request.args.get("claimant_id")
    employer_id = request.args.get("employer_id")
    if claimant_id is not None:
        items = [w for w in items if w["claimant_id"] == claimant_id]
    if employer_id is not None:
        items = [w for w in items if w["employer_id"] == employer_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/wage-records/<wid>", methods=["PATCH"])
def patch_wage_record(wid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Employer"})
    rec = db.wage_records.get(wid)
    if not rec:
        raise err("ERR_NOT_FOUND", "WageRecord not found.")
    body = get_json_body()
    is_disputed = as_bool(body, "is_disputed")
    # WageRecord is an immutable ledger line w.r.t. common fields (no version),
    # but the dispute flag is explicitly toggleable (PRD §3.1). No version bump
    # since WageRecord carries no version field.
    rec["is_disputed"] = is_disputed
    return object_response(serialize(rec))


# ===========================================================================
# EmergencyExtensionProgram
# ===========================================================================
@bp.route("/ui/extension-programs", methods=["POST"])
def create_extension_program():
    p = authenticate()
    require_role(p, {"ProgramAdmin"})
    body = get_json_body()
    program_code = as_string(body, "program_code")
    extra_weeks = as_int(body, "extra_weeks", minimum=1, maximum=53)
    if extra_weeks <= 0:
        raise err("ERR_INVALID_REQUEST", "extra_weeks must be > 0.")
    trigger_start = as_string(body, "trigger_start_date")
    validate_iso_date(trigger_start, "trigger_start_date")
    trigger_end = as_string(body, "trigger_end_date")
    validate_iso_date(trigger_end, "trigger_end_date")
    waives = as_bool(body, "waives_work_search", required=False, default=False)
    is_active = as_bool(body, "is_active", required=False, default=True)

    for prog in db.extension_programs.values():
        if prog["program_code"] == program_code:
            raise err("ERR_DUPLICATE_RESOURCE", "program_code already exists.")

    rec = {
        "program_code": program_code,
        "extra_weeks": extra_weeks,
        "trigger_start_date": trigger_start,
        "trigger_end_date": trigger_end,
        "waives_work_search": waives,
        "is_active": is_active,
    }
    db.stamp_create(rec)
    db.extension_programs[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/extension-programs/<pid>", methods=["GET"])
def get_extension_program(pid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator"})
    rec = db.extension_programs.get(pid)
    if not rec:
        raise err("ERR_NOT_FOUND", "EmergencyExtensionProgram not found.")
    return object_response(serialize(rec))


@bp.route("/ui/extension-programs/<pid>", methods=["PATCH"])
def patch_extension_program(pid):
    p = authenticate()
    require_role(p, {"ProgramAdmin"})
    rec = db.extension_programs.get(pid)
    if not rec:
        raise err("ERR_NOT_FOUND", "EmergencyExtensionProgram not found.")
    body = get_json_body()
    is_active = as_bool(body, "is_active")
    rec["is_active"] = is_active
    db.touch(rec)
    return object_response(serialize(rec))
