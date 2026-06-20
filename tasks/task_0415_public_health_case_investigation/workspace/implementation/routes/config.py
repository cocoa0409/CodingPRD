"""Programs, jurisdictions, reportable conditions."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import (base_entity, touch, parse_pagination, sorted_by_creation,
                     get_or_404, require_string, require_non_negative_int,
                     require_bool, parse_dt)
from middleware import get_user_context, require_role
from response import success, success_list
from serializers import ser_program, ser_jurisdiction, ser_condition

bp = Blueprint("config", __name__)

ALL_ROLES = {"JurisdictionAdmin", "IntakeProcessor", "CaseInvestigator", "ContactTracer", "EpiAnalyst"}

PROGRAM_DEFAULT_DATE = "2026-01-01T00:00:00.000Z"


# --- Surveillance Programs ---
@bp.route("/surveillance/programs", methods=["POST"])
def create_program():
    _, role = get_user_context()
    require_role(role, {"JurisdictionAdmin"})
    body = request.get_json(silent=True) or {}
    name = require_string(body, "name")
    description = require_string(body, "description", required=False)
    with db.lock:
        ent = base_entity(common_fields=True)
        ent.update({
            "name": name,
            "description": description,
            "current_date": PROGRAM_DEFAULT_DATE,
        })
        db.programs[ent["id"]] = ent
        return success(ser_program(ent), 201)


@bp.route("/surveillance/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        prog = get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        return success(ser_program(prog), 200)


@bp.route("/surveillance/programs/<program_id>/clock/set", methods=["POST"])
def set_clock(program_id):
    _, role = get_user_context()
    require_role(role, {"JurisdictionAdmin"})
    with db.lock:
        prog = get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        body = request.get_json(silent=True) or {}
        to_iso8601 = require_string(body, "to_iso8601")
        # validate parseable
        parse_dt(to_iso8601)
        prog["current_date"] = to_iso8601
        touch(prog)
        return success(ser_program(prog), 200)


# --- Jurisdictions ---
@bp.route("/surveillance/jurisdictions", methods=["POST"])
def create_jurisdiction():
    _, role = get_user_context()
    require_role(role, {"JurisdictionAdmin"})
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    name = require_string(body, "name")
    fips_code = require_string(body, "fips_code")
    with db.lock:
        get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        # uniqueness within program
        for j in db.jurisdictions.values():
            if j["program_id"] == program_id and j["fips_code"] == fips_code:
                raise err("ERR_DUPLICATE_KEY", "fips_code already exists in program")
        ent = base_entity(common_fields=True)
        ent.update({
            "program_id": program_id,
            "name": name,
            "fips_code": fips_code,
            "active_monitoring_count": 0,
        })
        db.jurisdictions[ent["id"]] = ent
        return success(ser_jurisdiction(ent), 201)


@bp.route("/surveillance/jurisdictions", methods=["GET"])
def list_jurisdictions():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        program_id = request.args.get("program_id")
        items = [j for j in db.jurisdictions.values()
                 if program_id is None or j["program_id"] == program_id]
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_jurisdiction(j) for j in page], limit, offset, total)


@bp.route("/surveillance/jurisdictions/<jurisdiction_id>", methods=["GET"])
def get_jurisdiction(jurisdiction_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        j = get_or_404(db.jurisdictions, jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
        return success(ser_jurisdiction(j), 200)


# --- Reportable Conditions ---
@bp.route("/surveillance/reportable-conditions", methods=["POST"])
def create_condition():
    _, role = get_user_context()
    require_role(role, {"JurisdictionAdmin"})
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    condition_code = require_string(body, "condition_code")
    display_name = require_string(body, "display_name")
    presymptomatic_days = require_non_negative_int(body, "presymptomatic_days")
    infectious_tail_days = require_non_negative_int(body, "infectious_tail_days")
    quarantine_days = require_non_negative_int(body, "quarantine_days")
    test_based_release_days = require_non_negative_int(body, "test_based_release_days")
    test_release_earliest_offset_days = require_non_negative_int(
        body, "test_release_earliest_offset_days", required=False)
    if test_release_earliest_offset_days is None:
        test_release_earliest_offset_days = 5
    isolation_min_days = require_non_negative_int(body, "isolation_min_days")
    fever_free_days = require_non_negative_int(body, "fever_free_days")
    cluster_min_cases = require_non_negative_int(body, "cluster_min_cases", required=False)
    if cluster_min_cases is None:
        cluster_min_cases = 3
    cluster_window_days = require_non_negative_int(body, "cluster_window_days", required=False)
    if cluster_window_days is None:
        cluster_window_days = 14
    requires_lab_confirmation = require_bool(body, "requires_lab_confirmation", default=True)

    # test_based_release_days must not exceed quarantine_days
    if test_based_release_days > quarantine_days:
        raise err("ERR_INVALID_REQUEST", "test_based_release_days must not exceed quarantine_days")
    # cluster_min_cases never below 2
    if cluster_min_cases < 2:
        raise err("ERR_INVALID_REQUEST", "cluster_min_cases must be >= 2")

    with db.lock:
        get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        for c in db.conditions.values():
            if c["program_id"] == program_id and c["condition_code"] == condition_code:
                raise err("ERR_DUPLICATE_KEY", "condition_code already exists in program")
        ent = base_entity(common_fields=True)
        ent.update({
            "program_id": program_id,
            "condition_code": condition_code,
            "display_name": display_name,
            "presymptomatic_days": presymptomatic_days,
            "infectious_tail_days": infectious_tail_days,
            "quarantine_days": quarantine_days,
            "test_based_release_days": test_based_release_days,
            "test_release_earliest_offset_days": test_release_earliest_offset_days,
            "isolation_min_days": isolation_min_days,
            "fever_free_days": fever_free_days,
            "cluster_min_cases": cluster_min_cases,
            "cluster_window_days": cluster_window_days,
            "requires_lab_confirmation": requires_lab_confirmation,
        })
        db.conditions[ent["id"]] = ent
        return success(ser_condition(ent), 201)


@bp.route("/surveillance/reportable-conditions", methods=["GET"])
def list_conditions():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        program_id = request.args.get("program_id")
        items = [c for c in db.conditions.values()
                 if program_id is None or c["program_id"] == program_id]
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_condition(c) for c in page], limit, offset, total)


@bp.route("/surveillance/reportable-conditions/<condition_id>", methods=["GET"])
def get_condition(condition_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        c = get_or_404(db.conditions, condition_id, "ERR_CONDITION_NOT_FOUND")
        return success(ser_condition(c), 200)
