"""Capital cycles, the stage pipeline and facility allocations (PRD 3.3, 3.6)."""

from flask import Blueprint, g

import lookups
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import CAPITAL_PLANNER, guard
from response import created_response, object_response
from services import allocation as allocation_service
from services import cascades, scoring
from validation import (body, dec_field, dt_field, enum_field, int_field,
                        pagination, q_int, q_str)

bp = Blueprint("cycles", __name__)

METHODS = ("PRO_RATA", "RANK_ORDERED")


def _require_status(cycle, allowed):
    if cycle["status"] not in allowed:
        raise ApiError("ERR_CYCLE_INVALID_STATE")


# -------------------------------------------------------------- CapitalCycle

@bp.route("/capital/cycles", methods=["POST"])
@guard(CAPITAL_PLANNER)
def create_cycle():
    data = body()
    plan_year = int_field(data, "plan_year", 2026, 2035)
    start_raw, start = dt_field(data, "plan_year_start")
    total = int_field(data, "total_capital_cents", 1)
    contingency_pct = dec_field(data, "contingency_pct", "0.00", "0.50", max_dp=4)
    facility_pct = dec_field(data, "facility_contingency_pct", "0.00", "0.50",
                             max_dp=4)

    for row in db.cycles.values():
        if row["plan_year"] == plan_year:
            raise ApiError("ERR_DUPLICATE_KEY")

    row = new_row({
        "plan_year": plan_year,
        "plan_year_start": start_raw,
        "_plan_year_start": start,
        "total_capital_cents": total,
        "contingency_pct": contingency_pct,
        "facility_contingency_pct": facility_pct,
        "allocation_method": None,
        "status": "DRAFT",
        "system_contingency_cents": 0,
        "distributable_cents": 0,
        "unallocated_cents": 0,
        "contingency_drawn_cents": 0,
        "allocation_count": 0,
        "exhausted_allocation_count": 0,
        "scored_count": 0,
        "expedited_count": 0,
        "allocated_by_user_id": None,
    })
    db.cycles[row["id"]] = row
    return created_response(serializers.cycle(row))


@bp.route("/capital/cycles/<cycle_id>", methods=["PATCH"])
@guard(CAPITAL_PLANNER)
def patch_cycle(cycle_id):
    cycle = lookups.cycle(cycle_id)
    data = body()
    total = int_field(data, "total_capital_cents", 1, required=False)
    contingency_pct = dec_field(data, "contingency_pct", "0.00", "0.50",
                                max_dp=4, required=False)
    facility_pct = dec_field(data, "facility_contingency_pct", "0.00", "0.50",
                             max_dp=4, required=False)
    start_raw, start = dt_field(data, "plan_year_start", required=False)

    _require_status(cycle, ("DRAFT",))

    if total is not None:
        cycle["total_capital_cents"] = total
    if contingency_pct is not None:
        cycle["contingency_pct"] = contingency_pct
    if facility_pct is not None:
        cycle["facility_contingency_pct"] = facility_pct
    if start_raw is not None:
        cycle["plan_year_start"] = start_raw
        cycle["_plan_year_start"] = start
    touch(cycle)
    return object_response(serializers.cycle(cycle))


@bp.route("/capital/cycles/<cycle_id>", methods=["GET"])
@guard()
def get_cycle(cycle_id):
    return object_response(serializers.cycle(lookups.cycle(cycle_id)))


@bp.route("/capital/cycles", methods=["GET"])
@guard()
def list_cycles():
    limit, offset = pagination()
    rows = lookups.filtered(db.cycles.values(), [
        ("status", q_str("status")),
        ("plan_year", q_int("plan_year")),
        ("allocation_method", q_str("allocation_method")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.cycle)


# ------------------------------------------------------------ stage pipeline

@bp.route("/capital/cycles/<cycle_id>/open-intake", methods=["POST"])
@guard(CAPITAL_PLANNER)
def open_intake(cycle_id):
    cycle = lookups.cycle(cycle_id)
    _require_status(cycle, ("DRAFT",))
    cycle["status"] = "INTAKE_OPEN"
    touch(cycle)
    return object_response(serializers.cycle(cycle))


@bp.route("/capital/cycles/<cycle_id>/close-intake", methods=["POST"])
@guard(CAPITAL_PLANNER)
def close_intake(cycle_id):
    cycle = lookups.cycle(cycle_id)
    _require_status(cycle, ("INTAKE_OPEN",))
    cycle["status"] = "SCORING"
    touch(cycle)
    return object_response(serializers.cycle(cycle))


@bp.route("/capital/cycles/<cycle_id>/score", methods=["POST"])
@guard(CAPITAL_PLANNER)
def score_cycle(cycle_id):
    cycle = lookups.cycle(cycle_id)
    _require_status(cycle, ("SCORING",))

    for request_row in ordered(db.requests.values()):
        if request_row["cycle_id"] != cycle["id"]:
            continue
        if request_row["status"] not in ("SCREENED", "SCORED"):
            continue
        scoring.score_request(request_row, "CYCLE_SCORING")
        request_row["status"] = "SCORED"
        touch(request_row)

    scoring.refresh_cycle_counts(cycle, bump=True)
    return object_response(serializers.cycle(cycle))


@bp.route("/capital/cycles/<cycle_id>/allocate", methods=["POST"])
@guard(CAPITAL_PLANNER)
def allocate_cycle(cycle_id):
    cycle = lookups.cycle(cycle_id)
    data = body()
    method = enum_field(data, "allocation_method", METHODS)
    expected = int_field(data, "expected_cycle_version")

    _require_status(cycle, ("SCORING", "ALLOCATED"))
    if expected != cycle["version"]:
        raise ApiError("ERR_STALE_CYCLE_VERSION")

    result = allocation_service.plan(cycle, method)

    if result["contingency_drawn_cents"] > result["system_contingency_cents"]:
        raise ApiError("ERR_CONTINGENCY_RESERVE_EXCEEDED")

    for row in db.allocations.values():
        if row["cycle_id"] == cycle["id"] and row["posture"] != "SUPERSEDED":
            if row["committed_cents"] != 0:
                raise ApiError("ERR_ALLOCATION_ALREADY_COMMITTED")

    if not result["requests"]:
        raise ApiError("ERR_NO_ELIGIBLE_REQUESTS")

    allocation_service.commit_plan(cycle, method, result, g.user_id)
    return object_response(serializers.cycle(cycle))


@bp.route("/capital/cycles/<cycle_id>/commit", methods=["POST"])
@guard(CAPITAL_PLANNER)
def commit_cycle(cycle_id):
    cycle = lookups.cycle(cycle_id)
    _require_status(cycle, ("ALLOCATED",))
    cycle["status"] = "COMMITTED"
    touch(cycle)
    cascades.defer_open_requests(cycle)
    return object_response(serializers.cycle(cycle))


# --------------------------------------------------------- FacilityAllocation

@bp.route("/capital/allocations/<allocation_id>", methods=["GET"])
@guard()
def get_allocation(allocation_id):
    return object_response(
        serializers.allocation(lookups.allocation(allocation_id)))


@bp.route("/capital/allocations", methods=["GET"])
@guard()
def list_allocations():
    limit, offset = pagination()
    rows = lookups.filtered(db.allocations.values(), [
        ("cycle_id", q_str("cycle_id")),
        ("facility_id", q_str("facility_id")),
        ("posture", q_str("posture")),
        ("contingency_status", q_str("contingency_status")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.allocation)


@bp.route("/capital/allocations/<allocation_id>/release-contingency",
          methods=["POST"])
@guard(CAPITAL_PLANNER)
def release_contingency(allocation_id):
    allocation = lookups.allocation(allocation_id)
    if (allocation["contingency_status"] == "RELEASED"
            or allocation["posture"] == "SUPERSEDED"):
        raise ApiError("ERR_CONTINGENCY_ALREADY_RELEASED")

    cycle = lookups.cycle(allocation["cycle_id"])
    allocation["contingency_status"] = "RELEASED"
    allocation["released_contingency_cents"] = \
        allocation["contingency_reserve_cents"]
    allocation_service.refresh_available(allocation)
    cycle_changed = allocation_service.refresh_posture(allocation, cycle)
    touch(allocation)
    if cycle_changed:
        touch(cycle)
    return object_response(serializers.allocation(allocation))
