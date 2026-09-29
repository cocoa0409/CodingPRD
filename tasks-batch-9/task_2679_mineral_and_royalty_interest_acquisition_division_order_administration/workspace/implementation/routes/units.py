"""Unitization, acreage commitments, pugh elections and terminations
(PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import guards
import response
import serializers
from db import clock_date, db, stamp_new, touch
from errors import ApiError
from guards import (authorize, body, body_ref, get_allocation, get_unit,
                    opt_bool, opt_date, opt_int, opt_num, pagination, paginate,
                    parse_date_str, req_date, req_enum, req_int, req_num,
                    req_str)

bp = Blueprint("units", __name__)

POOLING_ELECTIONS = ("POOLED", "NON_CONSENT", "LEASED_ROYALTY_ONLY")
ACREAGE_BEARING = ("ACTIVE", "PUGH_RELEASED")


def _require_operator(unit, user_id):
    """Rung 4 for the operator-bound writes named in PRD 2.10."""
    if unit is None or unit["operator_user_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return unit


def _committed_acres(unit_id):
    total = Decimal("0.0000")
    for row in db.allocations.values():
        if row["unit_id"] == unit_id and row["allocation_status"] in ACREAGE_BEARING:
            total += row["allocated_acres"]
    return calc.q4(total)


@bp.route("/units", methods=["POST"])
def create_unit():
    user_id, _role = authorize("Operator")
    payload = body()
    unit_name = req_str(payload, "unit_name")
    formation = req_str(payload, "formation")
    state_code = req_enum(payload, "state_code", guards.STATE_CODES)
    unit_gross_acres = req_num(payload, "unit_gross_acres", 4, minimum=0, exclusive_min=True)
    royalty_rate_cap = req_num(payload, "royalty_rate_cap", 6,
                               minimum=0, maximum=1, exclusive_min=True)
    total_depth_count = req_int(payload, "total_depth_count", minimum=1)
    producing_depth_count = req_int(payload, "producing_depth_count", minimum=0,
                                    maximum=total_depth_count)
    pugh_clause_active = opt_bool(payload, "pugh_clause_active", default=False)
    pugh_deadline, _parsed = opt_date(payload, "pugh_deadline")
    if pugh_clause_active and pugh_deadline is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'pugh_deadline' is required when pugh_clause_active is true.")

    row = {
        "unit_name": unit_name,
        "formation": formation,
        "state_code": state_code,
        "unit_gross_acres": unit_gross_acres,
        "royalty_rate_cap": royalty_rate_cap,
        "pugh_clause_active": pugh_clause_active,
        "pugh_deadline": pugh_deadline,
        "producing_depth_count": producing_depth_count,
        "total_depth_count": total_depth_count,
        "unallocated_acres": unit_gross_acres,
        "active_allocation_count": 0,
        "operator_user_id": user_id,
    }
    stamp_new(row)
    db.units[row["id"]] = row
    return response.created(serializers.unit_out(row))


@bp.route("/units/<unit_id>", methods=["GET"])
def read_unit(unit_id):
    authorize("TitleAnalyst", "AcquisitionManager", "DivisionOrderAdmin", "Operator")
    row = get_unit(unit_id)
    return response.ok(serializers.unit_out(row))


@bp.route("/units", methods=["GET"])
def list_units():
    authorize("DivisionOrderAdmin", "Operator")
    limit, offset = pagination()
    rows = list(db.units.values())
    for field in ("state_code", "formation"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.unit_out(r) for r in page], limit, offset, total)


@bp.route("/units/<unit_id>", methods=["PATCH"])
def update_unit(unit_id):
    authorize("Operator")
    unit = get_unit(unit_id)
    payload = body()
    producing_depth_count = opt_int(payload, "producing_depth_count", minimum=0,
                                    maximum=unit["total_depth_count"])
    pugh_clause_active = opt_bool(payload, "pugh_clause_active")
    pugh_deadline, _parsed = opt_date(payload, "pugh_deadline")
    royalty_rate_cap = opt_num(payload, "royalty_rate_cap", 6,
                               minimum=0, maximum=1, exclusive_min=True)

    if producing_depth_count is not None:
        unit["producing_depth_count"] = producing_depth_count
    if pugh_deadline is not None:
        unit["pugh_deadline"] = pugh_deadline
    if pugh_clause_active is not None:
        if pugh_clause_active and unit["pugh_deadline"] is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'pugh_deadline' is required when pugh_clause_active is true.")
        unit["pugh_clause_active"] = pugh_clause_active
    if royalty_rate_cap is not None:
        unit["royalty_rate_cap"] = royalty_rate_cap
    touch(unit)
    return response.ok(serializers.unit_out(unit))


# --------------------------------------------------------------------------
# acreage commitments
# --------------------------------------------------------------------------
@bp.route("/unit-tract-allocations", methods=["POST"])
def create_allocation():
    authorize("Operator")
    payload = body()
    unit = body_ref(payload, "unit_id", db.units, "ERR_UNIT_NOT_FOUND")
    tract = body_ref(payload, "tract_id", db.tracts, "ERR_TRACT_NOT_FOUND")
    if unit is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'unit_id' is required.")
    if tract is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'tract_id' is required.")
    allocated_acres = req_num(payload, "allocated_acres", 4, minimum=0, exclusive_min=True)
    effective_from, from_dt = req_date(payload, "effective_from")
    effective_to, to_dt = req_date(payload, "effective_to")
    pooling_election = req_enum(payload, "pooling_election", POOLING_ELECTIONS)
    if to_dt <= from_dt:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'effective_to' must be strictly later than 'effective_from'.")

    # priority 66: half-open intervals, so exact adjacency is legal
    for other in db.allocations.values():
        if other["unit_id"] != unit["id"] or other["tract_id"] != tract["id"]:
            continue
        if other["allocation_status"] not in ACREAGE_BEARING:
            continue
        if from_dt < other["_effective_to_date"] and other["_effective_from_date"] < to_dt:
            raise ApiError("ERR_ALLOCATION_INTERVAL_OVERLAP")

    # priority 80
    if calc.q4(_committed_acres(unit["id"]) + allocated_acres) > unit["unit_gross_acres"]:
        raise ApiError("ERR_UNIT_ACREAGE_OVERSUBSCRIBED")

    row = {
        "unit_id": unit["id"],
        "tract_id": tract["id"],
        "allocated_acres": allocated_acres,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "pooling_election": pooling_election,
        "allocation_status": "ACTIVE",
        "released_acres": Decimal("0.0000"),
        "termination_reason": None,
        "_effective_from_date": from_dt,
        "_effective_to_date": to_dt,
    }
    stamp_new(row)
    db.allocations[row["id"]] = row
    unit["unallocated_acres"] = calc.q4(unit["unallocated_acres"] - allocated_acres)
    unit["active_allocation_count"] = unit["active_allocation_count"] + 1
    touch(unit)
    return response.created(serializers.allocation_out(row))


@bp.route("/unit-tract-allocations/<allocation_id>", methods=["GET"])
def read_allocation(allocation_id):
    authorize("DivisionOrderAdmin", "Operator")
    row = get_allocation(allocation_id)
    return response.ok(serializers.allocation_out(row))


@bp.route("/units/<unit_id>/tract-allocations", methods=["GET"])
def list_unit_allocations(unit_id):
    authorize("DivisionOrderAdmin", "Operator")
    unit = get_unit(unit_id)
    limit, offset = pagination()
    allocation_status = request.args.get("allocation_status")
    tract_id = request.args.get("tract_id")
    rows = [a for a in db.allocations.values() if a["unit_id"] == unit["id"]]
    if allocation_status is not None:
        rows = [a for a in rows if a["allocation_status"] == allocation_status]
    if tract_id is not None:
        rows = [a for a in rows if a["tract_id"] == tract_id]
    rows.sort(key=lambda a: a["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.allocation_out(r) for r in page],
                            limit, offset, total)


@bp.route("/unit-tract-allocations/<allocation_id>/pugh-release", methods=["POST"])
def pugh_release(allocation_id):
    user_id, _role = authorize("Operator")
    allocation = get_allocation(allocation_id)
    unit = db.units.get(allocation["unit_id"])
    _require_operator(unit, user_id)                          # rung 4

    if allocation["allocation_status"] != "ACTIVE":            # priority 31
        raise ApiError("ERR_ALLOCATION_STATE_INVALID")
    deadline = parse_date_str(unit["pugh_deadline"]) if unit["pugh_deadline"] else None
    if deadline is not None and clock_date() < deadline:       # priority 63
        raise ApiError("ERR_PUGH_DEADLINE_NOT_REACHED")
    if not unit["pugh_clause_active"]:                         # priority 70
        raise ApiError("ERR_PUGH_CLAUSE_NOT_APPLICABLE")
    if unit["producing_depth_count"] >= unit["total_depth_count"]:
        raise ApiError("ERR_PUGH_ALL_DEPTHS_PRODUCING")

    original = allocation["allocated_acres"]
    retained = calc.q4(original * unit["producing_depth_count"] / unit["total_depth_count"])
    released = calc.q4(original - retained)
    allocation["released_acres"] = released
    allocation["allocated_acres"] = retained
    allocation["allocation_status"] = "PUGH_RELEASED"
    touch(allocation)
    unit["unallocated_acres"] = calc.q4(unit["unallocated_acres"] + released)
    touch(unit)
    return response.ok(serializers.allocation_out(allocation))


@bp.route("/unit-tract-allocations/<allocation_id>/terminate", methods=["POST"])
def terminate_allocation(allocation_id):
    user_id, _role = authorize("Operator")
    allocation = get_allocation(allocation_id)
    unit = db.units.get(allocation["unit_id"])
    _require_operator(unit, user_id)                          # rung 4
    payload = body()
    termination_reason = req_str(payload, "termination_reason")

    if allocation["allocation_status"] not in ACREAGE_BEARING:  # priority 31
        raise ApiError("ERR_ALLOCATION_STATE_INVALID")

    remaining = allocation["allocated_acres"]
    allocation["allocation_status"] = "TERMINATED"
    allocation["termination_reason"] = termination_reason
    touch(allocation)
    unit["unallocated_acres"] = calc.q4(unit["unallocated_acres"] + remaining)
    unit["active_allocation_count"] = unit["active_allocation_count"] - 1
    touch(unit)
    return response.ok(serializers.allocation_out(allocation))
