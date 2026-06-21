"""Tip declarations, pools, and waterfall distribution (PRD §3.5)."""
from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_role
from response import object_response, array_response
from util import (
    as_int, as_str, body, paginate, pagination, parse_date_str, public, public_list,
)
from services.helpers import get_or_404

bp = Blueprint("tips", __name__)


def _recompute_pool_totals(pool):
    """pooled_cents = sum of declared_cents over declarations whose pool_id ==
    this pool (SCAFFOLD §1.1)."""
    pooled = 0
    for td in db.tip_declarations.values():
        if td.get("pool_id") == pool["id"]:
            pooled += td.get("declared_cents", 0)
    pool["pooled_cents"] = pooled


# ---------------------------------------------------------------------------
# Tip declarations
# ---------------------------------------------------------------------------
@bp.post("/tip-declarations")
def create_tip_declaration():
    require_role("Supervisor", "Employee")
    data = body()
    employee_id = as_str(data, "employee_id", required=True)
    workday_date = parse_date_str(data, "workday_date", required=True)
    declared_cents = as_int(data, "declared_cents", required=True)
    pool_id = as_str(data, "pool_id", required=False)

    # Negative cents -> ERR_VALIDATION (priority 24).
    if declared_cents < 0:
        raise err("ERR_VALIDATION", "declared_cents must be non-negative.")

    # Existence left-to-right (priority 4).
    get_or_404(db.employees, employee_id)
    pool = None
    if pool_id is not None:
        pool = get_or_404(db.tip_pools, pool_id)

    # Employee acting on own declarations (ownership) (priority 6).
    if g.user_role == "Employee" and g.user_id != employee_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "Acting employee can only declare their own tips.")

    record = db.base_fields()
    record.update({
        "employee_id": employee_id,
        "workday_date": workday_date,
        "declared_cents": declared_cents,
        "pool_id": pool_id,
    })
    db.tip_declarations[record["id"]] = record

    # Recompute owning pool's pooled_cents when pool_id set.
    if pool is not None:
        _recompute_pool_totals(pool)
        db.touch(pool)

    return object_response(public(record), 201)


@bp.get("/tip-declarations")
def list_tip_declarations():
    require_role("PayrollAdmin", "Supervisor", "Employee")
    limit, offset = pagination()
    employee_id = request.args.get("employee_id")
    pool_id = request.args.get("pool_id")
    workday_date = request.args.get("workday_date")
    matches = list(db.tip_declarations.values())
    if employee_id is not None:
        matches = [t for t in matches if t.get("employee_id") == employee_id]
    if pool_id is not None:
        matches = [t for t in matches if t.get("pool_id") == pool_id]
    if workday_date is not None:
        matches = [t for t in matches if t.get("workday_date") == workday_date]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/tip-declarations/<declaration_id>")
def get_tip_declaration(declaration_id):
    require_role("PayrollAdmin", "Supervisor", "Employee")
    record = get_or_404(db.tip_declarations, declaration_id)
    return object_response(public(record))


# ---------------------------------------------------------------------------
# Tip pools
# ---------------------------------------------------------------------------
@bp.post("/tip-pools")
def create_tip_pool():
    require_role("Supervisor")
    data = body()
    worksite_id = as_str(data, "worksite_id", required=True)
    workday_date = parse_date_str(data, "workday_date", required=True)

    get_or_404(db.worksites, worksite_id)

    record = db.base_fields()
    record.update({
        "worksite_id": worksite_id,
        "workday_date": workday_date,
        "status": "OPEN",
        "pooled_cents": 0,
        "distributed_cents": 0,
    })
    db.tip_pools[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/tip-pools")
def list_tip_pools():
    require_role("PayrollAdmin", "Supervisor")
    limit, offset = pagination()
    worksite_id = request.args.get("worksite_id")
    workday_date = request.args.get("workday_date")
    matches = list(db.tip_pools.values())
    if worksite_id is not None:
        matches = [p for p in matches if p.get("worksite_id") == worksite_id]
    if workday_date is not None:
        matches = [p for p in matches if p.get("workday_date") == workday_date]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/tip-pools/<pool_id>")
def get_tip_pool(pool_id):
    require_role("PayrollAdmin", "Supervisor")
    record = get_or_404(db.tip_pools, pool_id)
    return object_response(public(record))


@bp.post("/tip-pools/<pool_id>/distribute")
def distribute_tip_pool(pool_id):
    require_role("Supervisor")
    pool = get_or_404(db.tip_pools, pool_id)

    # State: only from OPEN (priority 7).
    if pool.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Tip pool is not OPEN.")

    # Contributing declarations.
    contributing = [
        td for td in db.tip_declarations.values() if td.get("pool_id") == pool_id
    ]
    pooled_cents = sum(td.get("declared_cents", 0) for td in contributing)

    # Per contributing employee weight = sum of worked_minutes over CLOSED,
    # non-VOIDED punches whose workday_date == pool.workday_date.
    pool_day = pool.get("workday_date")
    employee_ids = []
    for td in contributing:
        if td["employee_id"] not in employee_ids:
            employee_ids.append(td["employee_id"])

    weights = {}
    for emp_id in employee_ids:
        weight = 0
        for p in db.punches.values():
            if p.get("employee_id") != emp_id:
                continue
            if p.get("status") != "CLOSED":
                continue
            if p.get("workday_date") == pool_day:
                weight += p.get("worked_minutes", 0)
        weights[emp_id] = weight

    total_weight = sum(weights.values())

    # Require >=1 contributing declaration with positive total weight
    # (priority 17 / ERR_EMPTY_TIP_POOL).
    if not contributing or total_weight <= 0:
        raise err("ERR_EMPTY_TIP_POOL",
                  "Tip pool has no contributing declaration with positive weight.")

    # Waterfall allocation: floor then distribute remainder (PRD §3.5).
    floors = {}
    for emp_id, w in weights.items():
        raw = pooled_cents * w  # numerator
        floors[emp_id] = raw // total_weight  # floor of raw/total_weight
    remainder = pooled_cents - sum(floors.values())

    # Distribute leftover cents one at a time, ordered by weight DESC,
    # tie-break employee created_at ASC (never by id).
    def order_key(emp_id):
        emp = db.employees.get(emp_id, {})
        return (-weights[emp_id], emp.get("created_at", ""), emp.get("_seq", 0))

    ordered = sorted(employee_ids, key=order_key)
    i = 0
    while remainder > 0 and ordered:
        floors[ordered[i % len(ordered)]] += 1
        remainder -= 1
        i += 1

    pool["distributed_cents"] = pooled_cents
    pool["pooled_cents"] = pooled_cents
    pool["status"] = "DISTRIBUTED"
    db.touch(pool)
    return object_response(public(pool))


@bp.post("/tip-pools/<pool_id>/cancel")
def cancel_tip_pool(pool_id):
    require_role("Supervisor")
    pool = get_or_404(db.tip_pools, pool_id)
    # Only from OPEN (priority 7).
    if pool.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Tip pool is not OPEN.")
    # Detach contributing declarations (pool_id -> null).
    for td in db.tip_declarations.values():
        if td.get("pool_id") == pool_id:
            td["pool_id"] = None
            db.touch(td)
    pool["status"] = "CANCELLED"
    db.touch(pool)
    return object_response(public(pool))
