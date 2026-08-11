"""PremiumAllocation routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import fmt_ts
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    adjust_governance,
    body,
    compute_allocation_amount,
    get_captive,
    get_program,
    get_allocation,
    opt_num,
    parse_dt_field,
    recompute_captive_ledger,
    recompute_program_fronting_fees,
    recompute_program_loss_ratio,
    recompute_unit_loss_ratio,
    req_enum,
    stamp_new,
    touch,
    touch_captive,
)

bp = Blueprint("allocations", __name__)

READ_ROLES = ("CaptiveManager", "Underwriter", "Actuary")


def _chain(captiveId, programId):
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    return captive, program


def _recompute_program_premium(program: dict) -> None:
    from decimal import Decimal
    total = Decimal("0")
    for a in db.allocations.values():
        if a["program_id"] == program["id"] and a["status"] in (
                "PROVISIONAL", "AUDITED", "FINALIZED"):
            total += Decimal(str(a.get("allocated_amount_cents") or 0))
    program["premium_allocated_cents"] = int(total)


@bp.post("/api/captives/<captiveId>/programs/<programId>/allocations")
def create_allocation(captiveId, programId):
    user_id, role = require_roles("Underwriter")
    captive, program = _chain(captiveId, programId)
    data = body()

    unit_id = data.get("operating_unit_id")
    if not unit_id or not isinstance(unit_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "operating_unit_id is required")
    unit = db.units.get(unit_id)
    if unit is None or unit["captive_id"] != captiveId:
        raise ApiError("ERR_OPERATING_UNIT_MISMATCH",
                       "Operating unit does not belong to the same captive")

    method = req_enum(data, "allocation_method", C.ALLOCATION_METHODS)
    period_start = parse_dt_field(data, "allocation_period_start")
    period_end = parse_dt_field(data, "allocation_period_end")
    risk_weight = opt_num(data, "risk_weight", 1.0)
    if risk_weight < C.RISK_WEIGHT_MIN or risk_weight > C.RISK_WEIGHT_MAX:
        raise ApiError("ERR_INVALID_REQUEST",
                       "risk_weight must be between 0.1 and 5.0")

    manual_amount = data.get("allocated_amount_cents")
    if manual_amount is not None and (isinstance(manual_amount, bool)
                                      or not isinstance(manual_amount, (int, float))):
        raise ApiError("ERR_INVALID_REQUEST",
                       "allocated_amount_cents must be a number")

    amount = compute_allocation_amount(program, unit, method, risk_weight,
                                       manual_amount, provisional=True)

    # Budget / concentration guard.
    from decimal import Decimal
    existing_total = Decimal("0")
    for a in db.allocations.values():
        if a["program_id"] == programId and a["status"] in (
                "PROVISIONAL", "AUDITED", "FINALIZED"):
            existing_total += Decimal(str(a.get("allocated_amount_cents") or 0))
    budget = Decimal(str(program.get("premium_budget_cents") or 0))
    if existing_total + Decimal(amount) > budget:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_BUDGET",
                       "Total premium allocations exceed program premium budget")
    if Decimal(amount) > budget * Decimal(str(C.MAX_ALLOCATION_PCT)):
        raise ApiError("ERR_ALLOCATION_EXCEEDS_BUDGET",
                       "Allocation exceeds 50% of the program premium budget")

    alloc = stamp_new()
    alloc.update({
        "program_id": programId,
        "operating_unit_id": unit_id,
        "captive_id": captiveId,
        "allocation_method": method,
        "allocated_amount_cents": amount,
        "provisional_amount_cents": amount,
        "final_amount_cents": None,
        "adjustment_cents": None,
        "risk_weight": risk_weight,
        "allocation_period_start": fmt_ts(period_start),
        "allocation_period_end": fmt_ts(period_end),
        "status": "PROVISIONAL",
        "created_by": user_id,
    })
    db.allocations[alloc["id"]] = alloc
    _recompute_program_premium(program)
    unit["total_premium_allocated_cents"] = int(
        unit.get("total_premium_allocated_cents") or 0) + amount
    touch(program)
    touch(unit)
    recompute_unit_loss_ratio(unit)
    recompute_program_loss_ratio(program)
    recompute_program_fronting_fees(program)
    recompute_captive_ledger(captive)
    log(captiveId, "CALCULATION_RUN", "PremiumAllocation", alloc["id"], role,
        user_id, "Premium allocation created PROVISIONAL", None, "PROVISIONAL")
    return ok(alloc, 201)


@bp.get("/api/captives/<captiveId>/programs/<programId>/allocations")
def list_allocations(captiveId, programId):
    require_roles(*READ_ROLES)
    _chain(captiveId, programId)
    items = [a for a in db.allocations.values() if a["program_id"] == programId]
    unit_filter = request.args.get("operating_unit_id")
    if unit_filter:
        items = [a for a in items if a["operating_unit_id"] == unit_filter]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/programs/<programId>/allocations/<allocId>")
def get_allocation_route(captiveId, programId, allocId):
    require_roles(*READ_ROLES)
    _, program = _chain(captiveId, programId)
    return ok(get_allocation(program, allocId), 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/allocations/<allocId>/audit")
def audit_allocation(captiveId, programId, allocId):
    user_id, role = require_roles("Actuary")
    captive, program = _chain(captiveId, programId)
    alloc = get_allocation(program, allocId)
    if alloc["status"] != "PROVISIONAL":
        raise ApiError("ERR_ALLOCATION_NOT_PROVISIONAL",
                       "Premium allocation must be in PROVISIONAL state")
    prev = alloc["status"]
    # Recompute using audited (actual) figures with exact cent rounding.
    unit = db.units.get(alloc["operating_unit_id"])
    manual = alloc["allocated_amount_cents"] if alloc["allocation_method"] == "MANUAL" else None
    audited = compute_allocation_amount(program, unit, alloc["allocation_method"],
                                        alloc.get("risk_weight", 1.0), manual,
                                        provisional=False)
    alloc["allocated_amount_cents"] = audited
    alloc["status"] = "AUDITED"
    touch(alloc)
    _recompute_program_premium(program)
    touch(program)
    recompute_program_fronting_fees(program)
    recompute_captive_ledger(captive)
    log(captiveId, "CALCULATION_RUN", "PremiumAllocation", allocId, role,
        user_id, "Allocation audited; amounts recomputed", prev, "AUDITED")
    return ok(alloc, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/allocations/<allocId>/finalize")
def finalize_allocation(captiveId, programId, allocId):
    user_id, role = require_roles("Actuary")
    captive, program = _chain(captiveId, programId)
    alloc = get_allocation(program, allocId)
    if alloc["status"] != "AUDITED":
        raise ApiError("ERR_ALLOCATION_NOT_AUDITED",
                       "Premium allocation must be in AUDITED state")
    data = body()
    final_amount = data.get("final_amount_cents")
    if final_amount is None or isinstance(final_amount, bool) or not isinstance(
            final_amount, (int, float)):
        raise ApiError("ERR_ALLOCATION_NOT_COMPUTED",
                       "Final allocation amount has not been computed")
    final_amount = int(final_amount)
    prev = alloc["status"]
    adjustment = final_amount - int(alloc.get("provisional_amount_cents") or 0)
    alloc["final_amount_cents"] = final_amount
    alloc["adjustment_cents"] = adjustment
    alloc["allocated_amount_cents"] = final_amount
    alloc["status"] = "FINALIZED"
    touch(alloc)
    unit = db.units.get(alloc["operating_unit_id"])
    if unit:
        unit["total_premium_allocated_cents"] = int(
            unit.get("total_premium_allocated_cents") or 0) + adjustment
        touch(unit)
        recompute_unit_loss_ratio(unit)
    _recompute_program_premium(program)
    touch(program)
    recompute_program_loss_ratio(program)
    recompute_program_fronting_fees(program)
    recompute_captive_ledger(captive)
    log(captiveId, "CALCULATION_RUN", "PremiumAllocation", allocId, role,
        user_id, "Allocation finalized; adjustment applied to ledgers", prev,
        "FINALIZED")
    return ok(alloc, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/allocations/<allocId>/dispute")
def dispute_allocation(captiveId, programId, allocId):
    user_id, role = require_roles("CaptiveManager")
    captive, program = _chain(captiveId, programId)
    alloc = get_allocation(program, allocId)
    if alloc["status"] != "PROVISIONAL":
        raise ApiError("ERR_ALLOCATION_NOT_PROVISIONAL",
                       "Premium allocation must be in PROVISIONAL state")
    prev = alloc["status"]
    alloc["status"] = "DISPUTED"
    touch(alloc)
    adjust_governance(captive, -3)
    touch_captive(captive)
    log(captiveId, "GOVERNANCE_ACTION", "PremiumAllocation", allocId, role,
        user_id, "Allocation disputed; governance score reduced by 3", prev,
        "DISPUTED")
    return ok(alloc, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/allocations/<allocId>/resolve-dispute")
def resolve_dispute_allocation(captiveId, programId, allocId):
    user_id, role = require_roles("CaptiveManager")
    captive, program = _chain(captiveId, programId)
    alloc = get_allocation(program, allocId)
    if alloc["status"] != "DISPUTED":
        raise ApiError("ERR_ALLOCATION_NOT_DISPUTED",
                       "Premium allocation must be in DISPUTED state")
    prev = alloc["status"]
    alloc["status"] = "PROVISIONAL"
    touch(alloc)
    adjust_governance(captive, +3)
    touch_captive(captive)
    log(captiveId, "GOVERNANCE_ACTION", "PremiumAllocation", allocId, role,
        user_id, "Dispute resolved; governance score restored by 3", prev,
        "PROVISIONAL")
    return ok(alloc, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/allocations/<allocId>/cancel")
def cancel_allocation(captiveId, programId, allocId):
    user_id, role = require_roles("Underwriter")
    captive, program = _chain(captiveId, programId)
    alloc = get_allocation(program, allocId)
    if alloc["status"] not in ("PROVISIONAL", "DISPUTED"):
        raise ApiError("ERR_ALLOCATION_NOT_CANCELLABLE",
                       "Premium allocation must be in PROVISIONAL or DISPUTED state")
    prev = alloc["status"]
    alloc["status"] = "CANCELLED"
    touch(alloc)
    _recompute_program_premium(program)
    touch(program)
    recompute_program_fronting_fees(program)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "PremiumAllocation", allocId, role,
        user_id, "Allocation cancelled", prev, "CANCELLED")
    return ok(alloc, 200)
