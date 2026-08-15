"""Tenancy endpoints (PRD §3.2, §3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_RETURN_COUNT_EXCEEDS_ISSUED,
    ERR_UNIT_OCCUPANCY_OVERLAP,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, recompute_unit_occupancy, touch
from util import CLOCK, parse_date
from validate import (
    get_body, opt_str, req_date, req_int, req_str,
    require_body_ref, require_path_resource,
)

bp = Blueprint("tenancies", __name__)


@bp.post("/pm/tenancies")
def create_tenancy():
    authorized(["PropertyManager"])
    body = get_body()
    fields = {
        "unit_id": req_str(body, "unit_id"),
        "tenant_display_name": req_str(body, "tenant_display_name"),
        "lease_start_on": req_date(body, "lease_start_on"),
        "lease_end_on": req_date(body, "lease_end_on"),
        "monthly_rent_cents": req_int(body, "monthly_rent_cents", non_negative=True),
        "deposit_cents": req_int(body, "deposit_cents", non_negative=True),
        "keys_issued": req_int(body, "keys_issued", non_negative=True),
        "fobs_issued": req_int(body, "fobs_issued", non_negative=True),
        "forwarding_address": opt_str(body, "forwarding_address"),
    }
    start = parse_date(fields["lease_start_on"])
    end = parse_date(fields["lease_end_on"])
    if not start < end:
        raise_error(ERR_INVALID_REQUEST,
                    "lease_start_on must be before lease_end_on")
    # Priority 4: referenced unit must exist.
    require_body_ref("units", fields["unit_id"], "unit_id")
    # Priority 8: half-open lease intervals [start, end) must not overlap on
    # the same unit; mere adjacency (end == start) is allowed.
    for other in db["tenancies"].values():
        if other["unit_id"] != fields["unit_id"]:
            continue
        o_start = parse_date(other["lease_start_on"])
        o_end = parse_date(other["lease_end_on"])
        if start < o_end and o_start < end:
            raise_error(ERR_UNIT_OCCUPANCY_OVERLAP,
                        "lease interval overlaps another tenancy on this unit")
    fields.update({
        "keys_returned": 0,
        "fobs_returned": 0,
        "move_in_on": None,
        "notice_given_on": None,
        "move_out_on": None,
        "interest_accrued_cents": 0,
        "pending_deductions_cents": 0,
        "total_deductions_cents": 0,
        "refund_paid_cents": 0,
        "penalty_paid_cents": 0,
        "escheated_cents": 0,
        "released_cents": 0,
        "reserved_cents": 0,
        "balance_remaining_cents": fields["deposit_cents"],
        "status": "PENDING_MOVE_IN",
    })
    rec = new_record("tenancies", fields)
    # A pending move-in already counts as RESERVED (PRD §3.2).
    recompute_unit_occupancy(fields["unit_id"])
    return success_object(public(rec), status=201)


@bp.get("/pm/tenancies/<rid>")
def get_tenancy(rid):
    return get_one("tenancies", rid)


@bp.get("/pm/tenancies")
def list_tenancies():
    return list_response("tenancies", {
        "unit_id": request.args.get("unit_id"),
        "status": request.args.get("status"),
    })


@bp.post("/pm/tenancies/<rid>/give_notice")
def give_notice(rid):
    authorized(["PropertyManager"])
    get_body()
    tenancy = require_path_resource("tenancies", rid)
    if tenancy["status"] != "OCCUPIED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"give_notice requires OCCUPIED, got {tenancy['status']}")
    tenancy["status"] = "NOTICE_GIVEN"
    tenancy["notice_given_on"] = CLOCK.today().isoformat()
    touch(tenancy)
    recompute_unit_occupancy(tenancy["unit_id"])
    return success_object(public(tenancy))


@bp.post("/pm/tenancies/<rid>/record_key_return")
def record_key_return(rid):
    authorized(["PropertyManager"])
    body = get_body()
    keys_returned = req_int(body, "keys_returned", non_negative=True)
    fobs_returned = req_int(body, "fobs_returned", non_negative=True)
    tenancy = require_path_resource("tenancies", rid)
    if tenancy["status"] not in ("OCCUPIED", "NOTICE_GIVEN"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "key returns close once the tenancy is VACATED")
    if (keys_returned > tenancy["keys_issued"]
            or fobs_returned > tenancy["fobs_issued"]):
        raise_error(ERR_RETURN_COUNT_EXCEEDS_ISSUED,
                    "returned count exceeds the issued count")
    # Counts are absolute running tallies, not deltas (PRD §3.3).
    tenancy["keys_returned"] = keys_returned
    tenancy["fobs_returned"] = fobs_returned
    touch(tenancy)
    return success_object(public(tenancy))
