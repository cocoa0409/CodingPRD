"""Subsidy periods, the cost ledger and the logical clock (PRD sections 2.5, 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import derive
import shapes
from auth import must_exist_filter, must_get, require
from errors import fail
from response import created, ok, ok_list, paginate, read_pagination
from serialize import dump, dump_many, jsonable
from store import all_records, create_record, fmt_dt, set_fields, store

bp = Blueprint("ledger", __name__)

PERIOD_READ_ROLES = ("ProgramDirector", "CaseManager", "FunderAnalyst")


# =========================================================================== #
# SubsidyPeriod
# =========================================================================== #

@bp.route("/subsidy-periods", methods=["POST"])
def create_subsidy_period():
    require(("ProgramDirector",))
    payload = shapes.body()
    line = must_get("business_lines", payload.get("business_line_id"))
    period_start = shapes.req_datetime(payload, "period_start")
    period_end = shapes.req_datetime(payload, "period_end")
    if period_end <= period_start:
        fail("ERR_INVALID_REQUEST", "period_end must be strictly after period_start.")
    supervisor_hours = shapes.req_number(payload, "supervisor_hours", 0, places=3)
    for existing in derive.periods_of_line(line["id"]):
        if period_start <= existing["period_end"] and existing["period_start"] <= period_end:
            fail("ERR_SUBSIDY_PERIOD_OVERLAP",
                 "The interval intersects an existing period of this business line.")
    period = create_record("subsidy_periods", {
        "business_line_id": line["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "supervisor_hours": supervisor_hours,
        "allocation_basis": "HOURS",
        "revenue_cents": None,
        "trainee_hours": Decimal("0.000"),
        "mission_cost_cents": 0,
        "business_operating_cost_cents": 0,
        "total_cost_cents": 0,
        "mission_share": Decimal("0.0000"),
        "true_cost_per_trainee_hour_cents": None,
        "subsidy_per_trainee_hour_cents": None,
        "margin_pct": None,
        "subsidy_rate": None,
        "subsidy_draw_cents": None,
        "closed_at": None,
    })
    return created(dump(period))


@bp.route("/subsidy-periods/<subsidy_period_id>", methods=["GET"])
def read_subsidy_period(subsidy_period_id):
    require(PERIOD_READ_ROLES)
    return ok(dump(must_get("subsidy_periods", subsidy_period_id)))


@bp.route("/subsidy-periods", methods=["GET"])
def list_subsidy_periods():
    require(PERIOD_READ_ROLES)
    line = must_exist_filter("business_lines", shapes.query_id("business_line_id"))
    status = shapes.query_enum("status", C.SUBSIDY_PERIOD_STATUSES)
    limit, offset = read_pagination(request.args)
    rows = all_records("subsidy_periods")
    if line is not None:
        rows = [row for row in rows if row["business_line_id"] == line["id"]]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.route("/subsidy-periods/<subsidy_period_id>/true-cost-analysis", methods=["GET"])
def true_cost_analysis(subsidy_period_id):
    require(("ProgramDirector", "FunderAnalyst"))
    period = must_get("subsidy_periods", subsidy_period_id)
    basis = shapes.query_enum("allocation_basis", C.ALLOCATION_BASES, period["allocation_basis"])
    if basis == "REVENUE" and period["revenue_cents"] is None:
        fail("ERR_REVENUE_NOT_AVAILABLE", "The period has no revenue_cents to allocate against.")
    result = derive.compute_allocation(period, basis)
    return ok(jsonable({
        "subsidy_period_id": period["id"],
        "allocation_basis": basis,
        "mission_share": result["mission_share"],
        "mission_cost_cents": result["mission_cost_cents"],
        "business_operating_cost_cents": result["business_operating_cost_cents"],
        "total_cost_cents": result["total_cost_cents"],
        "trainee_hours": result["trainee_hours"],
        "true_cost_per_trainee_hour_cents": result["true_cost_per_trainee_hour_cents"],
        "subsidy_per_trainee_hour_cents": result["subsidy_per_trainee_hour_cents"],
    }))


@bp.route("/subsidy-periods/<subsidy_period_id>/close", methods=["POST"])
def close_subsidy_period(subsidy_period_id):
    require(("ProgramDirector",))
    period = must_get("subsidy_periods", subsidy_period_id)
    payload = shapes.body()
    basis = shapes.req_enum(payload, "allocation_basis", C.ALLOCATION_BASES)
    revenue = shapes.req_int(payload, "revenue_cents", 0)
    if period["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an OPEN period may be closed.")
    if store.now <= period["period_end"]:
        fail("ERR_PERIOD_NOT_ENDED", "The logical clock has not passed period_end.")
    if _open_seats_inside(period):
        fail("ERR_OPEN_ASSIGNMENTS_BLOCK_CLOSE",
             "An ASSIGNED seat remains on a shift starting inside the period.")

    # hop 1 -- freeze the period and re-allocate the whole ledger on the final basis.
    set_fields(period,
               status="CLOSED",
               closed_at=store.now,
               revenue_cents=revenue,
               allocation_basis=basis)
    derive.apply_allocation(period, basis)
    margin = calc.margin_pct(revenue, period["business_operating_cost_cents"])
    rate = calc.subsidy_rate(margin)
    set_fields(period,
               margin_pct=margin,
               subsidy_rate=rate,
               subsidy_draw_cents=calc.subsidy_draw_cents(period["mission_cost_cents"], rate))

    # hops 2 to 5 -- the line's lifetime subsidy ledger and the cap cascade.
    line = store.business_lines[period["business_line_id"]]
    derive.recompute_cumulative_subsidy(line)
    derive.suspend_line_if_over_cap(line)
    return ok(dump(period))


def _open_seats_inside(period):
    for shift in derive.shifts_of_line(period["business_line_id"]):
        if not (period["period_start"] <= shift["starts_at"] <= period["period_end"]):
            continue
        for assignment in derive.assignments_of_shift(shift["id"]):
            if assignment["status"] == "ASSIGNED":
                return True
    return False


# =========================================================================== #
# CostEntry
# =========================================================================== #

@bp.route("/cost-entries", methods=["POST"])
def post_cost_entry():
    require(("ProgramDirector",))
    payload = shapes.body()
    period = must_get("subsidy_periods", payload.get("subsidy_period_id"))
    category = shapes.req_enum(payload, "category", C.COST_CATEGORIES)
    classification = shapes.req_enum(payload, "classification", C.CLASSIFICATIONS)
    amount = shapes.req_int(payload, "amount_cents", 1)
    expected_version = shapes.req_int(payload, "expected_subsidy_period_version")
    if period["status"] != "OPEN":
        fail("ERR_PERIOD_CLOSED", "The subsidy period is CLOSED.")
    if period["version"] != expected_version:
        fail("ERR_STALE_SUBSIDY_PERIOD_VERSION",
             "expected_subsidy_period_version does not match the period's current version.")
    if category not in C.MANUALLY_POSTABLE_CATEGORIES:
        fail("ERR_CATEGORY_NOT_MANUALLY_POSTABLE",
             "Only SUPERVISION, MATERIALS and OVERHEAD may be posted by hand.")
    entry = derive.post_cost_entry(period, category, classification, amount)
    return created(dump(entry))


@bp.route("/cost-entries/<cost_entry_id>", methods=["GET"])
def read_cost_entry(cost_entry_id):
    require(("ProgramDirector", "FunderAnalyst"))
    return ok(dump(must_get("cost_entries", cost_entry_id)))


@bp.route("/cost-entries", methods=["GET"])
def list_cost_entries():
    require(("ProgramDirector", "FunderAnalyst"))
    period = must_exist_filter("subsidy_periods", shapes.query_id("subsidy_period_id"))
    activity = must_exist_filter("support_activities", shapes.query_id("source_activity_id"))
    classification = shapes.query_enum("classification", C.CLASSIFICATIONS)
    status = shapes.query_enum("status", C.COST_ENTRY_STATUSES)
    limit, offset = read_pagination(request.args)
    rows = all_records("cost_entries")
    if period is not None:
        rows = [row for row in rows if row["subsidy_period_id"] == period["id"]]
    if activity is not None:
        rows = [row for row in rows if row["source_activity_id"] == activity["id"]]
    if classification is not None:
        rows = [row for row in rows if row["classification"] == classification]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


# =========================================================================== #
# The logical clock
# =========================================================================== #

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(("ProgramDirector",))
    payload = shapes.body()
    instant = shapes.req_datetime(payload, "to_iso8601")
    store.now = instant
    return ok({"current_utc": fmt_dt(store.now)})
