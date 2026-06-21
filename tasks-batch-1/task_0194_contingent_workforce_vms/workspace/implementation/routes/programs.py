"""Program, Supplier, WorkerProfile routes."""
from flask import Blueprint, request

import db
import services
from errors import err
from middleware import get_user_context, require_role, get_json_body, parse_iso
from response import success
from serializers import public
from listing import paginate, filter_by
import validators as V

bp = Blueprint("programs", __name__)

INITIAL_CLOCK = "1970-01-01T00:00:00.000Z"


# ============================= Program =====================================

@bp.route("/vms/programs", methods=["POST"])
def create_program():
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    body = get_json_body()

    name = V.as_string(V.require_present(body, "name"), "name")
    client_name = V.as_string(V.require_present(body, "client_name"), "client_name")
    default_markup = V.markup_in_range(V.require_present(body, "default_markup_pct"), "default_markup_pct")
    max_markup = V.markup_in_range(V.require_present(body, "max_markup_pct"), "max_markup_pct")
    limit_days = V.as_int(V.require_present(body, "coemployment_tenure_limit_days"), "coemployment_tenure_limit_days")
    if limit_days < 2:
        raise err("ERR_INVALID_REQUEST", "coemployment_tenure_limit_days must be >= 2")
    warn_days = V.as_int(V.require_present(body, "tenure_warning_threshold_days"), "tenure_warning_threshold_days")
    if warn_days < 1:
        raise err("ERR_INVALID_REQUEST", "tenure_warning_threshold_days must be >= 1")

    window_days = 7
    if body.get("timesheet_approval_window_days") is not None:
        window_days = V.as_int(body["timesheet_approval_window_days"], "timesheet_approval_window_days")
        if window_days < 1:
            raise err("ERR_INVALID_REQUEST", "timesheet_approval_window_days must be >= 1")

    # Threshold relation check (dedicated error, distinct from field validity).
    if not (warn_days < limit_days):
        raise err("ERR_THRESHOLD_INVALID",
                  "tenure_warning_threshold_days must be strictly less than coemployment_tenure_limit_days")

    record = db.common_fields()
    record.update({
        "name": name,
        "client_name": client_name,
        "default_markup_pct": default_markup,
        "max_markup_pct": max_markup,
        "coemployment_tenure_limit_days": limit_days,
        "tenure_warning_threshold_days": warn_days,
        "timesheet_approval_window_days": window_days,
        "current_clock": INITIAL_CLOCK,
        "status": "ACTIVE",
    })
    db.programs[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/programs/<pid>", methods=["GET"])
def get_program(pid):
    get_user_context()
    program = db.programs.get(pid)
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    return success(public(program), 200)


@bp.route("/vms/programs", methods=["GET"])
def list_programs():
    get_user_context()
    status = request.args.get("status")
    records = filter_by(list(db.programs.values()), status=status)
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


@bp.route("/vms/programs/<pid>/advance_clock", methods=["POST"])
def advance_clock(pid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    program = db.programs.get(pid)
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    body = get_json_body()
    to_iso = V.as_string(V.require_present(body, "to_iso8601"), "to_iso8601")
    dt = parse_iso(to_iso, "to_iso8601")
    program["current_clock"] = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    db.touch(program)
    services.advance_clock_sweeps(program)
    return success(public(program), 200)


@bp.route("/vms/programs/<pid>/_clock/set", methods=["POST"])
def set_clock(pid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    program = db.programs.get(pid)
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    body = get_json_body()
    to_iso = V.as_string(V.require_present(body, "to_iso8601"), "to_iso8601")
    dt = parse_iso(to_iso, "to_iso8601")
    program["current_clock"] = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    db.touch(program)
    return success(public(program), 200)


@bp.route("/vms/programs/<pid>/suspend", methods=["POST"])
def suspend_program(pid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    program = db.programs.get(pid)
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    program["status"] = "SUSPENDED"
    db.touch(program)
    return success(public(program), 200)


# ============================= Supplier ====================================

@bp.route("/vms/suppliers", methods=["POST"])
def create_supplier():
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    body = get_json_body()
    program_id = V.as_string(V.require_present(body, "program_id"), "program_id")
    program = db.programs.get(program_id)
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    name = V.as_string(V.require_present(body, "name"), "name")
    tier = V.as_int(V.require_present(body, "tier"), "tier")
    if tier < 1:
        raise err("ERR_TIER_INVALID", "tier must be >= 1")

    record = db.common_fields()
    record.update({
        "program_id": program_id,
        "name": name,
        "tier": tier,
        "status": "ACTIVE",
    })
    db.suppliers[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    get_user_context()
    supplier = db.suppliers.get(sid)
    if supplier is None:
        raise err("ERR_NOT_FOUND", "Supplier not found")
    return success(public(supplier), 200)


@bp.route("/vms/suppliers", methods=["GET"])
def list_suppliers():
    get_user_context()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    records = filter_by(list(db.suppliers.values()), program_id=program_id, status=status)
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


@bp.route("/vms/suppliers/<sid>/suspend", methods=["POST"])
def suspend_supplier(sid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    supplier = db.suppliers.get(sid)
    if supplier is None:
        raise err("ERR_NOT_FOUND", "Supplier not found")
    supplier["status"] = "SUSPENDED"
    db.touch(supplier)
    return success(public(supplier), 200)


# ============================= WorkerProfile ===============================

@bp.route("/vms/workers", methods=["POST"])
def create_worker():
    _, role = get_user_context()
    require_role(role, ["ProgramManager", "Supplier"])
    body = get_json_body()
    program_id = V.as_string(V.require_present(body, "program_id"), "program_id")
    program = db.programs.get(program_id)
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    full_name = V.as_string(V.require_present(body, "full_name"), "full_name")
    national_id_hash = V.as_string(V.require_present(body, "national_id_hash"), "national_id_hash")

    # Unique per program by national_id_hash.
    for w in db.workers.values():
        if w["program_id"] == program_id and w["national_id_hash"] == national_id_hash:
            raise err("ERR_DUPLICATE_WORKER",
                      "national_id_hash already used in this program")

    record = db.common_fields()
    record.update({
        "program_id": program_id,
        "full_name": full_name,
        "national_id_hash": national_id_hash,
        "cumulative_engaged_days": 0,
        "tenure_status": "CLEAR",
    })
    db.workers[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/workers/<wid>", methods=["GET"])
def get_worker(wid):
    get_user_context()
    worker = db.workers.get(wid)
    if worker is None:
        raise err("ERR_NOT_FOUND", "Worker not found")
    return success(public(worker), 200)


@bp.route("/vms/workers", methods=["GET"])
def list_workers():
    get_user_context()
    program_id = request.args.get("program_id")
    records = filter_by(list(db.workers.values()), program_id=program_id)
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)
