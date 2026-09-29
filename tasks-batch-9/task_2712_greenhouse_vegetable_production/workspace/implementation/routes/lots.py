"""Harvest lots: two parallel state dimensions, grading and the cold chain."""
from flask import Blueprint, g, request

import calc
import const
import fields
from authz import ALL_ROLES, HARVEST_SUPERVISOR, QUALITY_INSPECTOR, body, guard
from envelope import created, ok, paginated, public
from errors import ApiError
from helpers import fetch, filter_equals, occ, terminal, to_status_enum, transition
from money import D, q2
from store import base_record, db, now, ordered, touch

bp = Blueprint("lots", __name__)

COLD_CHAIN_ALLOWED = {
    "AMBIENT": ("PRECOOLED", "REJECTED"),
    "PRECOOLED": ("COLD_HELD", "REJECTED"),
    "COLD_HELD": ("RELEASED", "REJECTED"),
}

GRADED_STATES = ("GRADED", "REGRADED")


@bp.post("/harvest-lots")
@guard([HARVEST_SUPERVISOR])
def create_lot():
    payload = body()
    crop_cycle_id = fields.string(payload, "crop_cycle_id")
    harvest_date = fields.day(payload, "harvest_date")
    gross = fields.number(payload, "gross_weight_lbs", lo=0, exclusive_lo=True)
    labor_task_id = fields.string(payload, "labor_task_id", required=False)
    # priority 7 - declared input order
    cycle = fetch("crop_cycles", crop_cycle_id)
    if labor_task_id is not None:
        fetch("labor_tasks", labor_task_id)
    zone = db["zones"][cycle["zone_id"]]
    # priority 13 then 14
    if zone["ipm_posture"] == "LOCKED":
        raise ApiError("ERR_ZONE_IPM_LOCKED")
    if zone["reentry_clear_at"] is not None and now() < zone["reentry_clear_at"]:
        raise ApiError("ERR_REENTRY_INTERVAL_ACTIVE")
    # priority 31
    allowed_from = cycle["first_harvest_allowed_date"]
    if allowed_from is not None and harvest_date < allowed_from:
        raise ApiError("ERR_HARVEST_TOO_EARLY")

    record = base_record()
    record.update({
        "crop_cycle_id": crop_cycle_id,
        "labor_task_id": labor_task_id,
        "harvest_date": harvest_date,
        "gross_weight_lbs": q2(gross),
        "grade_a_lbs": None,
        "grade_b_lbs": None,
        "cull_lbs": None,
        "pack_out_pct": None,
        "allocated_a_lbs": q2(0),
        "allocated_b_lbs": q2(0),
        "available_a_lbs": q2(0),
        "available_b_lbs": q2(0),
        "grading_status": "UNGRADED",
        "cold_chain_status": "AMBIENT",
        "pulp_temp_c": None,
        "graded_by_worker_id": None,
        "cold_chain_released_by_user_id": None,
        "regrade_count": 0,
    })
    db["harvest_lots"][record["id"]] = record
    calc.recompute_cumulative_harvest(cycle)
    touch(cycle)
    return created(public(record))


@bp.get("/harvest-lots")
@guard(ALL_ROLES)
def list_lots():
    rows = ordered("harvest_lots")
    rows = filter_equals(rows, "crop_cycle_id", request.args.get("crop_cycle_id"))
    rows = filter_equals(rows, "labor_task_id", request.args.get("labor_task_id"))
    rows = filter_equals(
        rows, "graded_by_worker_id", request.args.get("graded_by_worker_id")
    )
    rows = filter_equals(rows, "grading_status", request.args.get("grading_status"))
    rows = filter_equals(
        rows, "cold_chain_status", request.args.get("cold_chain_status")
    )
    rows = filter_equals(
        rows, "harvest_date", request.args.get("harvest_date"), fields.parse_date
    )
    return paginated(rows, public)


@bp.get("/harvest-lots/<lot_id>")
@guard(ALL_ROLES)
def get_lot(lot_id):
    return ok(public(fetch("harvest_lots", lot_id)))


def _mass_balance(lot, grade_a, grade_b, cull):
    if q2(grade_a) + q2(grade_b) + q2(cull) != D(lot["gross_weight_lbs"]):
        raise ApiError("ERR_MASS_BALANCE_MISMATCH")


def _pack_out_floor(lot, acknowledged):
    if D(lot["pack_out_pct"]) < const.MIN_PACK_OUT_PCT and not acknowledged:
        raise ApiError("ERR_PACK_OUT_BELOW_MINIMUM")


@bp.post("/harvest-lots/<lot_id>/grade")
@guard([HARVEST_SUPERVISOR], actor=True)
def grade_lot(lot_id):
    payload = body()
    grade_a = fields.number(payload, "grade_a_lbs", lo=0)
    grade_b = fields.number(payload, "grade_b_lbs", lo=0)
    cull = fields.number(payload, "cull_lbs", lo=0)
    acknowledged = fields.boolean(
        payload, "low_pack_out_acknowledged", required=False, default=False
    )
    lot = fetch("harvest_lots", lot_id)
    # priority 9 - a condemned or shipped lot's grade is settled
    terminal(lot["cold_chain_status"], const.COLD_CHAIN_TERMINAL)
    # priority 10 - a restatement must go through regrade
    transition({"UNGRADED": ("GRADED",)}, lot["grading_status"], "GRADED")
    # priority 22
    _mass_balance(lot, grade_a, grade_b, cull)

    snapshot = (lot["grade_a_lbs"], lot["grade_b_lbs"], lot["cull_lbs"],
                lot["pack_out_pct"], lot["available_a_lbs"], lot["available_b_lbs"],
                lot["allocated_a_lbs"], lot["allocated_b_lbs"])
    calc.apply_grading(lot, grade_a, grade_b, cull)
    try:
        # priority 24
        _pack_out_floor(lot, acknowledged)
    except ApiError:
        (lot["grade_a_lbs"], lot["grade_b_lbs"], lot["cull_lbs"],
         lot["pack_out_pct"], lot["available_a_lbs"], lot["available_b_lbs"],
         lot["allocated_a_lbs"], lot["allocated_b_lbs"]) = snapshot
        raise
    # low_pack_out_acknowledged is transient and never persisted on the lot.
    lot["grading_status"] = "GRADED"
    lot["graded_by_worker_id"] = g.user_id
    touch(lot)
    return ok(public(lot))


@bp.post("/harvest-lots/<lot_id>/regrade")
@guard([HARVEST_SUPERVISOR], actor=True)
def regrade_lot(lot_id):
    payload = body()
    grade_a = fields.number(payload, "grade_a_lbs", lo=0)
    grade_b = fields.number(payload, "grade_b_lbs", lo=0)
    cull = fields.number(payload, "cull_lbs", lo=0)
    expected = fields.integer(payload, "expected_lot_version")
    acknowledged = fields.boolean(
        payload, "low_pack_out_acknowledged", required=False, default=False
    )
    lot = fetch("harvest_lots", lot_id)
    # priority 8 - the stale-view guard runs ahead of every state check
    occ(lot, expected, "ERR_STALE_LOT_VERSION")
    # priority 9
    terminal(lot["cold_chain_status"], const.COLD_CHAIN_TERMINAL)
    # priority 16
    if lot["grading_status"] not in GRADED_STATES:
        raise ApiError("ERR_LOT_NOT_GRADED")
    # priority 22
    _mass_balance(lot, grade_a, grade_b, cull)
    # priority 23 - promised pounds cannot be graded away
    if q2(grade_a) < D(lot["allocated_a_lbs"]) or q2(grade_b) < D(lot["allocated_b_lbs"]):
        raise ApiError("ERR_ALLOCATED_EXCEEDS_GRADE")

    snapshot = (lot["grade_a_lbs"], lot["grade_b_lbs"], lot["cull_lbs"],
                lot["pack_out_pct"], lot["available_a_lbs"], lot["available_b_lbs"],
                lot["allocated_a_lbs"], lot["allocated_b_lbs"])
    calc.apply_grading(lot, grade_a, grade_b, cull)
    try:
        # priority 24
        _pack_out_floor(lot, acknowledged)
    except ApiError:
        (lot["grade_a_lbs"], lot["grade_b_lbs"], lot["cull_lbs"],
         lot["pack_out_pct"], lot["available_a_lbs"], lot["available_b_lbs"],
         lot["allocated_a_lbs"], lot["allocated_b_lbs"]) = snapshot
        raise
    lot["grading_status"] = "REGRADED"
    lot["graded_by_worker_id"] = g.user_id
    lot["regrade_count"] = lot["regrade_count"] + 1
    touch(lot)
    return ok(public(lot))


@bp.post("/harvest-lots/<lot_id>/cold-chain-events")
@guard([QUALITY_INSPECTOR])
def cold_chain_event(lot_id):
    payload = body()
    target = fields.enum_slot(payload, "to_status")
    pulp_temp = fields.number(payload, "pulp_temp_c")
    to_status_enum(target, const.COLD_CHAIN_STATUSES)
    lot = fetch("harvest_lots", lot_id)
    terminal(lot["cold_chain_status"], const.COLD_CHAIN_TERMINAL)
    transition(COLD_CHAIN_ALLOWED, lot["cold_chain_status"], target)

    if target == "RELEASED":
        # priority 16 - the other dimension must be settled first
        if lot["grading_status"] not in GRADED_STATES:
            raise ApiError("ERR_LOT_NOT_GRADED")
    if target == "PRECOOLED" and pulp_temp > const.PRECOOL_MAX_C:
        raise ApiError("ERR_COLD_CHAIN_BREACH")
    if target in ("COLD_HELD", "RELEASED") and pulp_temp > const.COLD_HOLD_MAX_C:
        raise ApiError("ERR_COLD_CHAIN_BREACH")

    lot["pulp_temp_c"] = q2(pulp_temp)
    lot["cold_chain_status"] = target
    if target == "RELEASED":
        lot["cold_chain_released_by_user_id"] = g.user_id
    touch(lot)

    if target == "REJECTED":
        # Four hops: allocations, lot pools, commitment weeks and program risk,
        # plus the crop cycle's yield ledger.
        rows = [
            r for r in ordered("lot_allocations")
            if r["lot_id"] == lot["id"] and r["status"] in ("PROVISIONAL", "CONFIRMED")
        ]
        lot_ids, week_ids = calc.revoke_rows(rows, const.REVOKE_REASON_COLD_CHAIN)
        calc.restore_lots(lot_ids, skip_lot_id=lot["id"])
        calc.recompute_lot_pools(lot)
        calc.restate_weeks(week_ids)
        cycle = db["crop_cycles"].get(lot["crop_cycle_id"])
        if cycle is not None:
            calc.recompute_cumulative_harvest(cycle)
            touch(cycle)
    return ok(public(lot))
