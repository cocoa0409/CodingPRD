"""Retail programs, commitment weeks, the allocation waterfall and settlement."""
import re
from datetime import timedelta

from flask import Blueprint, g, request

import calc
import const
import fields
from authz import (ALL_ROLES, GROWER_MANAGER, QUALITY_INSPECTOR, body, guard)
from envelope import array, created, ok, paginated, public
from errors import ApiError
from helpers import fetch, filter_equals, terminal, to_status_enum, transition
from money import D, q2
from store import base_record, db, now, ordered, touch

bp = Blueprint("commerce", __name__)

ISO_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


# ------------------------------------------------------------ RetailProgram


@bp.post("/retail-programs")
@guard([GROWER_MANAGER])
def create_program():
    payload = body()
    retailer_name = fields.string(payload, "retailer_name", min_len=1)
    program_code = fields.string(payload, "program_code", min_len=1)
    grade_spec = fields.enum_slot(payload, "grade_spec")
    weekly = fields.number(payload, "weekly_commitment_lbs", lo=0, exclusive_lo=True)
    price = fields.number(payload, "price_per_lb_usd", lo=0, exclusive_lo=True)
    penalty = fields.number(payload, "shortfall_penalty_per_lb_usd", lo=0)
    priority_rank = fields.integer(payload, "priority_rank", lo=1, hi=99)
    status = fields.enum_slot(payload, "status", required=False)
    fields.enum_value(grade_spec, "grade_spec", const.GRADE_SPECS)
    fields.enum_value(status, "status", const.PROGRAM_STATUSES)
    # priority 19
    for existing in db["retail_programs"].values():
        if existing["program_code"] == program_code:
            raise ApiError("ERR_PROGRAM_CODE_DUPLICATE")

    record = base_record()
    record.update({
        "retailer_name": retailer_name,
        "program_code": program_code,
        "grade_spec": grade_spec,
        "weekly_commitment_lbs": q2(weekly),
        "price_per_lb_usd": q2(price),
        "shortfall_penalty_per_lb_usd": q2(penalty),
        "priority_rank": priority_rank,
        "status": status or "ACTIVE",
        "at_risk_week_count": 0,
        "penalty_accrued_usd": q2(0),
    })
    db["retail_programs"][record["id"]] = record
    return created(public(record))


@bp.get("/retail-programs")
@guard(ALL_ROLES)
def list_programs():
    """Listed in waterfall order: priority_rank ASC then created_at ASC."""
    rows = ordered("retail_programs")
    rows.sort(key=lambda p: (p["priority_rank"], p["created_at"], p["_seq"]))
    rows = filter_equals(rows, "status", request.args.get("status"))
    rows = filter_equals(rows, "grade_spec", request.args.get("grade_spec"))
    return paginated(rows, public)


@bp.get("/retail-programs/<program_id>")
@guard(ALL_ROLES)
def get_program(program_id):
    return ok(public(fetch("retail_programs", program_id)))


# ------------------------------------------------------------ CommitmentWeek

WEEK_ALLOWED = {
    "ALLOCATED": ("SHIPPED", "CLOSED"),
    "OPEN": ("CLOSED",),
    "SHIPPED": ("CLOSED",),
}

WEEK_SUBROLES = {
    "SHIPPED": (QUALITY_INSPECTOR,),
    "CLOSED": (GROWER_MANAGER,),
    "CLOSED_SHORT": (GROWER_MANAGER,),
    "CLOSED_FULFILLED": (GROWER_MANAGER,),
}

CLOSE_TOKENS = ("CLOSED", "CLOSED_SHORT", "CLOSED_FULFILLED")


@bp.post("/commitment-weeks")
@guard([GROWER_MANAGER])
def create_week():
    payload = body()
    program_id = fields.string(payload, "program_id")
    iso_week = fields.string(payload, "iso_week")
    week_start = fields.day(payload, "week_start_date")
    committed = fields.number(
        payload, "committed_lbs", required=False, lo=0, exclusive_lo=True
    )
    if not ISO_WEEK_RE.match(iso_week):
        raise ApiError("ERR_VALIDATION", "iso_week must match YYYY-Www")
    # priority 7
    program = fetch("retail_programs", program_id)
    # priority 19 - unique inside the program only
    for existing in db["commitment_weeks"].values():
        if existing["program_id"] == program_id and existing["iso_week"] == iso_week:
            raise ApiError("ERR_ISO_WEEK_DUPLICATE")

    committed_lbs = q2(
        committed if committed is not None else program["weekly_commitment_lbs"]
    )
    record = base_record()
    record.update({
        "program_id": program_id,
        "iso_week": iso_week,
        "week_start_date": week_start,
        "committed_lbs": committed_lbs,
        "allocated_lbs": q2(0),
        "shipped_lbs": q2(0),
        "fill_rate_pct": q2(0),
        "provisional_shortfall_lbs": committed_lbs,
        "provisional_penalty_usd": q2(
            committed_lbs * D(program["shortfall_penalty_per_lb_usd"])
        ),
        "final_shortfall_lbs": None,
        "final_penalty_usd": None,
        "gross_revenue_usd": None,
        "net_payout_usd": None,
        "status": "OPEN",
        "shipped_at": None,
        "shipped_by_user_id": None,
    })
    db["commitment_weeks"][record["id"]] = record
    return created(public(record))


@bp.get("/commitment-weeks")
@guard(ALL_ROLES)
def list_weeks():
    rows = ordered("commitment_weeks")
    rows = filter_equals(rows, "program_id", request.args.get("program_id"))
    rows = filter_equals(
        rows, "week_start_date", request.args.get("week_start_date"),
        fields.parse_date,
    )
    rows = filter_equals(rows, "status", request.args.get("status"))
    return paginated(rows, public)


@bp.get("/commitment-weeks/<week_id>")
@guard(ALL_ROLES)
def get_week(week_id):
    return ok(public(fetch("commitment_weeks", week_id)))


@bp.post("/commitment-weeks/<week_id>/transitions")
@guard([GROWER_MANAGER, QUALITY_INSPECTOR], subroles=WEEK_SUBROLES)
def transition_week(week_id):
    payload = body()
    target = fields.enum_slot(payload, "to_status")
    shipped_at = None
    if target == "SHIPPED":
        shipped_at = fields.timestamp(payload, "shipped_at")
    to_status_enum(target, const.WEEK_STATUSES + ("CLOSED",))
    week = fetch("commitment_weeks", week_id)
    program = db["retail_programs"][week["program_id"]]
    terminal(week["status"], const.WEEK_TERMINAL)
    edge = "CLOSED" if target in CLOSE_TOKENS else target
    transition(WEEK_ALLOWED, week["status"], edge)

    if edge == "SHIPPED":
        rows = [
            r for r in ordered("lot_allocations")
            if r["commitment_week_id"] == week["id"]
        ]
        # priority 12 - checked ahead of the segregation rule at priority 18
        if not any(r["status"] == "CONFIRMED" for r in rows):
            raise ApiError("ERR_NO_CONFIRMED_ALLOCATIONS")
        # priority 18 - the releasing inspector may not sign the shipment
        for row in rows:
            lot = db["harvest_lots"].get(row["lot_id"])
            if lot is None:
                continue
            if lot["cold_chain_released_by_user_id"] == g.user_id:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        # priority 34
        if program["status"] != "ACTIVE":
            raise ApiError("ERR_PROGRAM_NOT_ACTIVE")

        dropped = []
        for row in rows:
            if row["status"] == "CONFIRMED":
                row["status"] = "RELEASED"
                touch(row)
            elif row["status"] == "PROVISIONAL":
                dropped.append(row)
        lot_ids, _ = calc.revoke_rows(dropped, const.REVOKE_REASON_SHIP)
        calc.restore_lots(lot_ids)
        week["status"] = "SHIPPED"
        week["shipped_at"] = shipped_at
        week["shipped_by_user_id"] = g.user_id
        calc.recompute_week_allocated(week)
        calc.recompute_week_shipped(week)
        # The ALLOCATED -> OPEN revert rule is deliberately suppressed here.
        committed = D(week["committed_lbs"])
        if committed == 0:
            week["fill_rate_pct"] = q2(0)
        else:
            week["fill_rate_pct"] = q2(D(100) * D(week["shipped_lbs"]) / committed)
        touch(week)
        return ok(public(week))

    # ---- closing out
    if week["status"] == "OPEN":
        # priority 33 - the delivery window must have elapsed
        elapsed_from = week["week_start_date"] + timedelta(
            days=const.LOT_ELIGIBILITY_WINDOW_DAYS
        )
        if now().date() < elapsed_from:
            raise ApiError("ERR_WEEK_STILL_OPEN")
    # priority 34
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE")

    if week["status"] in ("OPEN", "ALLOCATED"):
        rows = [
            r for r in ordered("lot_allocations")
            if r["commitment_week_id"] == week["id"]
            and r["status"] in ("PROVISIONAL", "CONFIRMED")
        ]
        lot_ids, _ = calc.revoke_rows(rows, const.REVOKE_REASON_CLOSE_SHORT)
        calc.restore_lots(lot_ids)
        calc.recompute_week_allocated(week)
        calc.apply_provisional(week)

    calc.recompute_week_shipped(week)
    calc.apply_final(week)
    if D(week["shipped_lbs"]) >= D(week["committed_lbs"]):
        week["status"] = "CLOSED_FULFILLED"
    else:
        week["status"] = "CLOSED_SHORT"
    touch(week)
    return ok(public(week))


# ------------------------------------------------------------ LotAllocation

ALLOCATION_ALLOWED = {
    "PROVISIONAL": ("CONFIRMED", "REVOKED"),
    "CONFIRMED": ("REVOKED",),
}

ALLOCATION_SUBROLES = {
    "CONFIRMED": (QUALITY_INSPECTOR,),
    "REVOKED": (GROWER_MANAGER,),
}


@bp.get("/lot-allocations")
@guard(ALL_ROLES)
def list_allocations():
    rows = ordered("lot_allocations")
    rows = filter_equals(rows, "lot_id", request.args.get("lot_id"))
    rows = filter_equals(
        rows, "commitment_week_id", request.args.get("commitment_week_id")
    )
    rows = filter_equals(rows, "grade", request.args.get("grade"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return paginated(rows, public)


@bp.get("/lot-allocations/<allocation_id>")
@guard(ALL_ROLES)
def get_allocation(allocation_id):
    return ok(public(fetch("lot_allocations", allocation_id)))


@bp.post("/lot-allocations/<allocation_id>/transitions")
@guard([GROWER_MANAGER, QUALITY_INSPECTOR], subroles=ALLOCATION_SUBROLES)
def transition_allocation(allocation_id):
    payload = body()
    target = fields.enum_slot(payload, "to_status")
    revoked_reason = None
    if target == "REVOKED":
        revoked_reason = fields.string(payload, "revoked_reason", min_len=1)
    to_status_enum(target, const.ALLOCATION_STATUSES)
    row = fetch("lot_allocations", allocation_id)
    week = db["commitment_weeks"][row["commitment_week_id"]]
    lot = db["harvest_lots"].get(row["lot_id"])
    terminal(row["status"], const.ALLOCATION_TERMINAL)
    transition(ALLOCATION_ALLOWED, row["status"], target)

    if target == "CONFIRMED":
        # priority 11 - the cross-entity week check precedes the lot checks
        if week["status"] != "ALLOCATED":
            raise ApiError("ERR_WEEK_NOT_ALLOCATED")
        # priority 16 - cold chain before grading
        if lot is None or lot["cold_chain_status"] != "COLD_HELD":
            raise ApiError("ERR_LOT_NOT_COLD_HELD")
        if lot["grading_status"] not in ("GRADED", "REGRADED"):
            raise ApiError("ERR_LOT_NOT_GRADED")
        # priority 41 - mass-invariant backstop, reachable only after a regrade
        pool_key = "available_a_lbs" if row["grade"] == "A" else "available_b_lbs"
        if D(lot[pool_key]) < 0:
            raise ApiError("ERR_INSUFFICIENT_AVAILABLE_LBS")
        # Confirmation moves no pounds at all.
        row["status"] = "CONFIRMED"
        touch(row)
        return ok(public(row))

    # ---- revocation: a three-hop cascade
    # priority 11
    if week["status"] not in ("OPEN", "ALLOCATED"):
        raise ApiError("ERR_WEEK_ALREADY_SHIPPED")
    row["status"] = "REVOKED"
    row["revoked_reason"] = revoked_reason
    touch(row)
    if lot is not None:
        calc.recompute_lot_pools(lot)
        touch(lot)
    reverted = calc.restate_week_after_allocation_change(week)
    if reverted:
        program = db["retail_programs"].get(week["program_id"])
        if program is not None:
            program["at_risk_week_count"] = program["at_risk_week_count"] + 1
            touch(program)
    return ok(public(row))


# ------------------------------------------------------------ allocation runs


@bp.post("/allocation-runs")
@guard([GROWER_MANAGER])
def allocation_run():
    payload = body()
    week_start = fields.day(payload, "week_start_date")
    weeks, _candidates = calc.run_waterfall(week_start)
    return array([public(w) for w in weeks])
