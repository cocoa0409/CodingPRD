"""Crimp applicators and setup windows (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_INVALID_REQUEST,
                    ERR_APPLICATOR_SETUP_ALREADY_OPEN, ERR_APPLICATOR_SETUP_OVERLAP)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import common_fields, touch, ser_applicator, ser_setup, paginated
from util import CLOCK
from validate import get_body, req_str, req_dt, require_path, require_fk

bp = Blueprint("applicators", __name__)

PROCESS_ENGINEER = {"ProcessEngineer"}


@bp.route("/plant/applicators", methods=["POST"])
def create_applicator():
    body = get_body()
    applicator_code = req_str(body, "applicator_code")
    compatible_terminal_mpn = req_str(body, "compatible_terminal_mpn")
    authenticate(PROCESS_ENGINEER)
    for a in db["applicators"].values():
        if a["applicator_code"] == applicator_code:
            raise_error(ERR_INVALID_REQUEST, f"duplicate applicator_code: {applicator_code}")

    app_obj = common_fields()
    app_obj.update({
        "applicator_code": applicator_code,
        "compatible_terminal_mpn": compatible_terminal_mpn,
        "status": "AVAILABLE",
        "current_program_id": None,
        "qualified_at": None,
        "_quarantine_seq": None,
    })
    db["applicators"][app_obj["id"]] = app_obj
    return success_object(ser_applicator(app_obj), 201)


@bp.route("/plant/applicators/<aid>", methods=["GET"])
def get_applicator(aid):
    authenticate(ALL_ROLES)
    app_obj = require_path("applicators", aid)
    return success_object(ser_applicator(app_obj), 200)


@bp.route("/plant/applicators", methods=["GET"])
def list_applicators():
    authenticate(ALL_ROLES)
    items = list(db["applicators"].values())
    current_program_id = request.args.get("current_program_id")
    if current_program_id is not None:
        items = [a for a in items if a["current_program_id"] == current_program_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginated(items, ser_applicator)


@bp.route("/plant/applicator-setups", methods=["POST"])
def create_setup():
    body = get_body()
    # Tier 1
    applicator_id = req_str(body, "applicator_id")
    program_id = req_str(body, "program_id")
    setup_operator_id = req_str(body, "setup_operator_id")
    planned_start_at = req_dt(body, "planned_start_at")
    planned_end_at = req_dt(body, "planned_end_at")
    if planned_end_at <= planned_start_at:
        raise_error(ERR_INVALID_REQUEST,
                    "planned_end_at must be strictly after planned_start_at")
    # Tiers 2-3
    authenticate(PROCESS_ENGINEER)
    # Tier 4, left-to-right in declared input order
    applicator = require_fk("applicators", applicator_id, "applicator_id")
    require_fk("machine_programs", program_id, "program_id")
    require_fk("operators", setup_operator_id, "setup_operator_id")
    # Tier 6: no other OPEN setup on this applicator
    for s in db["applicator_setups"].values():
        if s["applicator_id"] == applicator["id"] and s["status"] == "OPEN":
            raise_error(ERR_APPLICATOR_SETUP_ALREADY_OPEN,
                        "another OPEN setup exists on this applicator")
    # Tier 9: half-open interval overlap against every existing setup window on
    # this applicator; touching endpoints allowed.
    for s in db["applicator_setups"].values():
        if s["applicator_id"] != applicator["id"]:
            continue
        if planned_start_at < s["planned_end_at"] and s["planned_start_at"] < planned_end_at:
            raise_error(ERR_APPLICATOR_SETUP_OVERLAP,
                        "planned setup window overlaps an existing window on the applicator")

    setup = common_fields()
    setup.update({
        "applicator_id": applicator["id"],
        "program_id": program_id,
        "setup_operator_id": setup_operator_id,
        "planned_start_at": planned_start_at,
        "planned_end_at": planned_end_at,
        "status": "OPEN",
        "closed_at": None,
    })
    db["applicator_setups"][setup["id"]] = setup

    # Applicator AVAILABLE|QUALIFIED|QUARANTINED -> IN_SETUP.
    applicator["status"] = "IN_SETUP"
    applicator["current_program_id"] = program_id
    touch(applicator)
    return success_object(ser_setup(setup), 201)


@bp.route("/plant/applicator-setups/<sid>", methods=["GET"])
def get_setup(sid):
    authenticate(ALL_ROLES)
    setup = require_path("applicator_setups", sid)
    return success_object(ser_setup(setup), 200)


@bp.route("/plant/applicator-setups", methods=["GET"])
def list_setups():
    authenticate(ALL_ROLES)
    items = list(db["applicator_setups"].values())
    applicator_id = request.args.get("applicator_id")
    if applicator_id is not None:
        items = [s for s in items if s["applicator_id"] == applicator_id]
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    setup_operator_id = request.args.get("setup_operator_id")
    if setup_operator_id is not None:
        items = [s for s in items if s["setup_operator_id"] == setup_operator_id]
    return paginated(items, ser_setup)


@bp.route("/plant/applicator-setups/<sid>/close", methods=["POST"])
def close_setup(sid):
    body = get_body()
    closed_at = req_dt(body, "closed_at")
    authenticate(PROCESS_ENGINEER)
    setup = require_path("applicator_setups", sid)
    if setup["status"] != "OPEN":
        raise_error(ERR_INVALID_REQUEST, "setup is not OPEN")
    if closed_at < setup["planned_start_at"]:
        raise_error(ERR_INVALID_REQUEST,
                    "closed_at must be at or after planned_start_at")
    setup["status"] = "CLOSED"
    setup["closed_at"] = closed_at
    touch(setup)

    applicator = db["applicators"].get(setup["applicator_id"])
    if applicator is not None and applicator["status"] == "IN_SETUP":
        applicator["status"] = "AVAILABLE"
        touch(applicator)
    return success_object(ser_setup(setup), 200)
