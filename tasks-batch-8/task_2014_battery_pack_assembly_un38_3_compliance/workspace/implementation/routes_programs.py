"""IntegrationProgram CRUD + lifecycle (§3.1) and the logical-clock endpoint
(§2.13, mounted outside /api)."""

from decimal import Decimal

from flask import Blueprint

import db
import clock
from domain import (
    new_row, touch, sorted_rows, get_program, ser_program,
    OPEN_SHIPMENT_STATES,
)
from errors import (
    err_program_not_open, err_program_not_suspended, err_unresolved_packs,
    err_open_shipments, err_active_recall_exists, err_invalid_request,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, as_str, as_int, parse_datetime, format_ts

bp = Blueprint("programs", __name__)
bp_clock = Blueprint("clock", __name__)


@bp.route("/integration-programs", methods=["POST"])
@require_roles("SafetyOfficer")
def create_program(actor):
    body = get_body(required=True)
    program_code = as_str(req_field(body, "program_code"), "program_code")
    capacity = as_int(req_field(body, "storage_capacity_wh"), "storage_capacity_wh")
    if capacity < 0:
        raise err_invalid_request("storage_capacity_wh must be >= 0")

    row = new_row()
    row.update(
        program_code=program_code,
        compliance_risk_index=100,
        storage_capacity_wh=capacity,
        wh_committed=Decimal("0"),
        recall_count=0,
        status="OPEN",
        _serial_next=1,
    )
    db.programs[row["id"]] = row
    return success_created(ser_program(row))


@bp.route("/integration-programs", methods=["GET"])
@require_roles()
def list_programs(actor):
    return success_list(sorted_rows(db.programs.values()), ser_program)


@bp.route("/integration-programs/<programId>", methods=["GET"])
@require_roles()
def get_one_program(actor, programId):
    return success_object(ser_program(get_program(programId)))


@bp.route("/integration-programs/<programId>/suspend", methods=["POST"])
@require_roles("SafetyOfficer")
def suspend_program(actor, programId):
    program = get_program(programId)
    get_body()
    if program["status"] != "OPEN":
        raise err_program_not_open()
    program["status"] = "SUSPENDED"
    touch(program)
    return success_object(ser_program(program))


@bp.route("/integration-programs/<programId>/resume", methods=["POST"])
@require_roles("SafetyOfficer")
def resume_program(actor, programId):
    program = get_program(programId)
    get_body()
    if program["status"] != "SUSPENDED":
        raise err_program_not_suspended()
    program["status"] = "OPEN"
    touch(program)
    # side effect: drop active_recall_id links whose recall is no longer ACTIVE
    for pack in db.packs.values():
        if pack["program_id"] != program["id"]:
            continue
        rid = pack.get("active_recall_id")
        if rid:
            recall = db.recalls.get(rid)
            if recall is None or recall["status"] != "ACTIVE":
                pack["active_recall_id"] = None
                touch(pack)
    return success_object(ser_program(program))


@bp.route("/integration-programs/<programId>/close", methods=["POST"])
@require_roles("SafetyOfficer")
def close_program(actor, programId):
    program = get_program(programId)
    get_body()
    if program["status"] != "OPEN":
        raise err_program_not_open()
    # guards fire in the narrative order of §3.1: packs, then shipments, then recalls
    for pack in db.packs.values():
        if pack["program_id"] != program["id"]:
            continue
        if pack["assembly_status"] != "RECALLED" and pack["logistics_status"] not in (
            "DELIVERED",
            "RETURNED",
        ):
            raise err_unresolved_packs()
    for shipment in db.shipments.values():
        if shipment["program_id"] != program["id"]:
            continue
        if shipment["status"] in OPEN_SHIPMENT_STATES:
            raise err_open_shipments()
    for recall in db.recalls.values():
        if recall["program_id"] != program["id"]:
            continue
        if recall["status"] == "ACTIVE":
            raise err_active_recall_exists()
    program["status"] = "CLOSED"
    touch(program)
    return success_object(ser_program(program))


@bp_clock.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("SafetyOfficer")
def set_clock(actor):
    body = get_body(required=True)
    to = parse_datetime(req_field(body, "to_iso8601"), "to_iso8601")
    current = clock.set_current(to)
    return success_object({"current_utc": format_ts(current)})
