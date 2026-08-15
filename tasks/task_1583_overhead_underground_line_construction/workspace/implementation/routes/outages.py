"""Outage request endpoints (PRD 3.6): request, decide (60-minute clearance),
request-change, release, cancel; lazy IN_EFFECT evaluation on reads."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_INVALID_DATE_RANGE,
    ERR_OUTAGE_WINDOW_CONFLICT,
)
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from routes.work_packages import require_contract_active, WP_TERMINAL
from services.core import (
    new_record, touch, contract_of_work_package, sweep_outages_in_effect,
)
from util import parse_datetime
from validate import (
    get_body, req_str, req_enum, req_datetime, require_path_resource,
)

bp = Blueprint("outages", __name__)

BUFFER = timedelta(minutes=60)


@bp.post("/work-packages/<work_package_id>/outage-requests")
def create_outage_request(work_package_id):
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    circuit_id = req_str(body, "circuit_id")
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    wp = require_path_resource("work_packages", work_package_id)
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if wp["status"] in WP_TERMINAL:
        raise_error(ERR_INVALID_STATE,
                    "outage requests require a non-terminal work package")
    if parse_datetime(window_end) <= parse_datetime(window_start):
        raise_error(ERR_INVALID_DATE_RANGE, "window_end must be > window_start")
    rec = new_record("outage_requests", {
        "work_package_id": wp["id"],
        "circuit_id": circuit_id,
        "window_start": window_start,
        "window_end": window_end,
        "requested_window_start": None,
        "requested_window_end": None,
        "status": "REQUESTED",
    })
    return success_object(serialize("outage_requests", rec), status=201)


def _buffer_conflict(circuit_id, start, end, exclude_id):
    """60-minute clearance: the candidate window must start >= other.end + 60m
    or end <= other.start - 60m for every other APPROVED/IN_EFFECT request on
    the same circuit. Exactly 60 minutes satisfies the buffer."""
    for o in db["outage_requests"].values():
        if o["id"] == exclude_id or o["circuit_id"] != circuit_id:
            continue
        if o["status"] not in ("APPROVED", "IN_EFFECT"):
            continue
        os_ = parse_datetime(o["window_start"])
        oe = parse_datetime(o["window_end"])
        if start >= oe + BUFFER or end <= os_ - BUFFER:
            continue
        return True
    return False


@bp.post("/outage-requests/<outage_request_id>/decide")
def decide_outage_request(outage_request_id):
    authorized(["UTILITY_DISPATCHER"])
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVED", "DENIED"})
    outage = require_path_resource("outage_requests", outage_request_id)
    wp = require_path_resource("work_packages", outage["work_package_id"])
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    sweep_outages_in_effect()
    if outage["status"] not in ("REQUESTED", "CHANGE_REQUESTED"):
        raise_error(ERR_INVALID_STATE,
                    f"cannot decide an outage request in {outage['status']}")
    if decision == "APPROVED":
        if outage["status"] == "CHANGE_REQUESTED":
            start = parse_datetime(outage["requested_window_start"])
            end = parse_datetime(outage["requested_window_end"])
        else:
            start = parse_datetime(outage["window_start"])
            end = parse_datetime(outage["window_end"])
        if _buffer_conflict(outage["circuit_id"], start, end, outage["id"]):
            raise_error(ERR_OUTAGE_WINDOW_CONFLICT,
                        "window is within the 60-minute clearance buffer of "
                        "another APPROVED/IN_EFFECT outage on this circuit")
        if outage["status"] == "CHANGE_REQUESTED":
            # Adopt the requested window; clear the proposal.
            outage["window_start"] = outage["requested_window_start"]
            outage["window_end"] = outage["requested_window_end"]
            outage["requested_window_start"] = None
            outage["requested_window_end"] = None
        outage["status"] = "APPROVED"
    else:
        outage["status"] = "DENIED"
    touch(outage)
    # A window adopted (or approved) around the logical now takes effect lazily.
    sweep_outages_in_effect()
    return success_object(serialize("outage_requests", outage))


@bp.post("/outage-requests/<outage_request_id>/request-change")
def request_change_outage(outage_request_id):
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    outage = require_path_resource("outage_requests", outage_request_id)
    wp = require_path_resource("work_packages", outage["work_package_id"])
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if outage["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE,
                    "only an APPROVED outage can be renegotiated")
    if parse_datetime(window_end) <= parse_datetime(window_start):
        raise_error(ERR_INVALID_DATE_RANGE, "window_end must be > window_start")
    outage["requested_window_start"] = window_start
    outage["requested_window_end"] = window_end
    outage["status"] = "CHANGE_REQUESTED"
    touch(outage)
    return success_object(serialize("outage_requests", outage))


@bp.post("/outage-requests/<outage_request_id>/release")
def release_outage(outage_request_id):
    authorized(["UTILITY_DISPATCHER"])
    get_body()
    outage = require_path_resource("outage_requests", outage_request_id)
    wp = require_path_resource("work_packages", outage["work_package_id"])
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    sweep_outages_in_effect()  # release references this outage: lazy evaluation
    if outage["status"] != "IN_EFFECT":
        raise_error(ERR_INVALID_STATE,
                    "only an IN_EFFECT outage can be released")
    outage["status"] = "RELEASED"
    touch(outage)
    return success_object(serialize("outage_requests", outage))


@bp.post("/outage-requests/<outage_request_id>/cancel")
def cancel_outage(outage_request_id):
    authorized(["CONTRACTOR_PM"])
    get_body()
    outage = require_path_resource("outage_requests", outage_request_id)
    wp = require_path_resource("work_packages", outage["work_package_id"])
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if outage["status"] not in ("REQUESTED", "APPROVED", "CHANGE_REQUESTED"):
        raise_error(ERR_INVALID_STATE,
                    f"cannot cancel an outage request in {outage['status']}")
    outage["status"] = "CANCELLED"
    touch(outage)
    return success_object(serialize("outage_requests", outage))


@bp.get("/outage-requests")
def list_outage_requests():
    filters = {
        "work_package_id": request.args.get("work_package_id"),
        "circuit_id": request.args.get("circuit_id"),
        "status": request.args.get("status"),
    }
    return list_response("outage_requests", filters,
                         pre_hook=sweep_outages_in_effect)


@bp.get("/outage-requests/<outage_request_id>")
def get_outage_request(outage_request_id):
    from middleware import ALL_ROLES
    authorized(list(ALL_ROLES))
    sweep_outages_in_effect()
    return get_one("outage_requests", outage_request_id)
