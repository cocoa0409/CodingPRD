"""Seasonal program and commitment endpoints (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_DRAFT, ERR_PROGRAM_NOT_OPEN,
    ERR_PROGRAM_WINDOW_INVALID, ERR_COMMITMENT_WINDOW_CLOSED, ERR_PROGRAM_POOL_EXHAUSTED,
    ERR_COMMITMENT_BELOW_CONSUMED, ERR_STALE_PROGRAM_VERSION,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import ALL_READ_ROLES, get_one, list_response, public
from services import new_record, settle_program_commitments, touch
from util import CLOCK, parse_dt
from validate import (
    get_body, req_datetime, req_int, req_number, req_str, require_path_resource, require_ref,
)

bp = Blueprint("programs", __name__)

COMMITMENT_READ_ROLES = ["BranchManager", "Account"]


# --- SeasonalProgram -------------------------------------------------------

@bp.post("/pool-supply/seasonal-programs")
def create_program():
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    body = get_body()
    branch_id = req_str(body, "branch_id")
    require_ref("branches", branch_id, "branch_id")
    rec = new_record("seasonal_programs", {
        "branch_id": branch_id,
        "program_name": req_str(body, "program_name"),
        "order_window_start": req_datetime(body, "order_window_start"),
        "order_window_end": req_datetime(body, "order_window_end"),
        "ship_window_start": req_datetime(body, "ship_window_start"),
        "ship_window_end": req_datetime(body, "ship_window_end"),
        "early_buy_discount_pct": req_number(body, "early_buy_discount_pct", minimum=0, maximum=50),
        "pool_cap_units": req_int(body, "pool_cap_units", minimum=0),
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/pool-supply/seasonal-programs")
def list_programs():
    filters = {
        "branch_id": request.args.get("branch_id"),
        "status": request.args.get("status"),
    }
    return list_response("seasonal_programs", ALL_READ_ROLES, filters)


@bp.get("/pool-supply/seasonal-programs/<rid>")
def get_program(rid):
    return get_one("seasonal_programs", rid, ALL_READ_ROLES)


@bp.post("/pool-supply/seasonal-programs/<rid>/open")
def open_program(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    program = require_path_resource("seasonal_programs", rid)
    if program["status"] != "DRAFT":
        raise_error(ERR_PROGRAM_NOT_DRAFT, "open requires a DRAFT program")
    if parse_dt(program["order_window_start"]) > parse_dt(program["order_window_end"]):
        raise_error(ERR_PROGRAM_WINDOW_INVALID, "order_window_start is after order_window_end")
    if parse_dt(program["ship_window_start"]) > parse_dt(program["ship_window_end"]):
        raise_error(ERR_PROGRAM_WINDOW_INVALID, "ship_window_start is after ship_window_end")
    program["status"] = "OPEN"
    touch(program)
    return success_object(public(program))


@bp.post("/pool-supply/seasonal-programs/<rid>/close")
def close_program(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    program = require_path_resource("seasonal_programs", rid)
    if program["status"] != "OPEN":
        raise_error(ERR_PROGRAM_NOT_OPEN, "close requires an OPEN program")
    program["status"] = "CLOSED"
    touch(program)
    settle_program_commitments(program)
    return success_object(public(program))


# --- SeasonalCommitment ----------------------------------------------------

@bp.post("/pool-supply/seasonal-commitments")
def create_commitment():
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    body = get_body()
    program_id = req_str(body, "program_id")
    account_id = req_str(body, "account_id")
    committed_units = req_int(body, "committed_units", minimum=1)
    # existence (priority 4)
    program = require_ref("seasonal_programs", program_id, "program_id")
    require_ref("accounts", account_id, "account_id")
    # state (priority 5): commitment create requires an OPEN program
    if program["status"] != "OPEN":
        raise_error(ERR_PROGRAM_NOT_OPEN, "commitment create requires an OPEN program")
    # OCC on the program snapshot (PRD 2.8): non-optional, before business checks
    if "expected_program_version" not in body or body["expected_program_version"] is None:
        raise_error(ERR_INVALID_REQUEST, "expected_program_version is required")
    epv = body["expected_program_version"]
    if isinstance(epv, bool) or not isinstance(epv, int):
        raise_error(ERR_INVALID_REQUEST, "expected_program_version must be an integer")
    if epv != program["version"]:
        raise_error(ERR_STALE_PROGRAM_VERSION, "stale program version; re-read and retry")
    # business temporal (priority 9): now within [order_window_start, order_window_end] inclusive
    now = CLOCK.now()
    if not (parse_dt(program["order_window_start"]) <= now <= parse_dt(program["order_window_end"])):
        raise_error(ERR_COMMITMENT_WINDOW_CLOSED, "outside the commitment order window")
    # business fiscal (priority 14): pool cap (old commitment still COMMITTED at check time)
    pool_used = sum(
        c["committed_units"]
        for c in db["seasonal_commitments"].values()
        if c["program_id"] == program_id and c["status"] == "COMMITTED"
    )
    if pool_used + committed_units > program["pool_cap_units"]:
        raise_error(ERR_PROGRAM_POOL_EXHAUSTED, "program committed-units pool cap would be exceeded")
    # supersede of an existing COMMITTED commitment for the same (program, account)
    existing = next(
        (
            c for c in db["seasonal_commitments"].values()
            if c["program_id"] == program_id
            and c["account_id"] == account_id
            and c["status"] == "COMMITTED"
        ),
        None,
    )
    if existing is not None:
        if committed_units < existing["consumed_units"]:
            raise_error(
                ERR_COMMITMENT_BELOW_CONSUMED,
                "replacement committed_units below already-consumed units",
            )
        existing["status"] = "SUPERSEDED"
        touch(existing)
    rec = new_record("seasonal_commitments", {
        "program_id": program_id,
        "account_id": account_id,
        "committed_units": committed_units,
        "consumed_units": 0,
        "status": "COMMITTED",
    })
    touch(program)  # recording a commitment increments the program version
    return success_object(public(rec), status=201)


@bp.get("/pool-supply/seasonal-commitments")
def list_commitments():
    filters = {
        "program_id": request.args.get("program_id"),
        "account_id": request.args.get("account_id"),
        "status": request.args.get("status"),
    }
    return list_response("seasonal_commitments", COMMITMENT_READ_ROLES, filters)


@bp.get("/pool-supply/seasonal-commitments/<rid>")
def get_commitment(rid):
    return get_one("seasonal_commitments", rid, COMMITMENT_READ_ROLES)
