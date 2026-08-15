"""Allocation runs: the revenue waterfall over settled invoices (PRD 3.10)."""
from flask import Blueprint, request

from authz import ADMIN, FINANCE, require_roles
from calc import allocation_waterfall
from db import store
from errors import date_range_invalid, invalid_state
from respond import success
from serialize import ser_allocation_run
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, req_temporal,
    sorted_by_creation, touch,
)
from timeutil import as_date, as_instant

bp = Blueprint("allocations", __name__)

ROLES = [FINANCE, ADMIN]


@bp.route("/buildings/<bid>/allocation-runs", methods=["POST"])
def create_allocation_run(bid):
    require_roles(ROLES)
    b = get_or_404(store.buildings, bid)
    data = json_body()
    period_start = req_temporal(data, "period_start")
    period_end = req_temporal(data, "period_end")
    if as_date(period_end) < as_date(period_start):
        raise date_range_invalid("period_end must not precede period_start")
    start_instant = as_instant(period_start)
    end_instant = as_instant(period_end)
    gross = 0
    for v in store.invoices.values():
        if v["status"] != "PAID" or v["paid_at"] is None:
            continue
        g = store.groups.get(v["group_id"])
        if g is None or g["building_id"] != bid:
            continue
        if start_instant <= v["paid_at"] < end_instant:
            gross += v["total_cents"]
    overhead, reserve, ops = allocation_waterfall(gross)
    r = {
        "id": new_id(),
        "_seq": next(store.seq),
        "building_id": bid,
        "period_start": period_start,
        "period_end": period_end,
        "gross_cents": gross,
        "overhead_cents": overhead,
        "reserve_cents": reserve,
        "ops_cents": ops,
        "status": "OPEN",
    }
    r.update(new_common_fields())
    store.allocation_runs[r["id"]] = r
    return success(ser_allocation_run(r), status=201)


@bp.route("/buildings/<bid>/allocation-runs", methods=["GET"])
def list_allocation_runs(bid):
    require_roles([ADMIN, FINANCE])
    get_or_404(store.buildings, bid)
    status = request.args.get("status")
    items = [r for r in store.allocation_runs.values()
             if r["building_id"] == bid and (status is None or r["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_allocation_run(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/allocation-runs/<rid>", methods=["GET"])
def get_allocation_run(rid):
    require_roles([ADMIN, FINANCE])
    return success(ser_allocation_run(get_or_404(store.allocation_runs, rid)))


@bp.route("/allocation-runs/<rid>/lock", methods=["POST"])
def lock_allocation_run(rid):
    require_roles(ROLES)
    r = get_or_404(store.allocation_runs, rid)
    if r["status"] != "OPEN":
        raise invalid_state("Allocation run must be OPEN to lock")
    r["status"] = "LOCKED"
    touch(r)
    return success(ser_allocation_run(r))
