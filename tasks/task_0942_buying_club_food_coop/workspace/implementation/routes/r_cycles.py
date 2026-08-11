"""The pre-order cycle and its lifecycle actions (11 endpoints)."""

from flask import Blueprint

from core import clock, serialize
from core.constants import CYCLE_STATUSES, ROLES
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (endpoint, enum_filter, gate_cycle_closed, pagination,
                         path_row, req_instant, req_str)
from core.store import DB
from services import cycle_ops, recompute, reconciliation
from services.lock_cascade import run_lock

bp = Blueprint("cycles", __name__)
R5 = list(ROLES)


@bp.post("/cycles")
@endpoint(["ClubAdmin"])
def create_cycle(ctx):
    code = req_str(ctx, "code")
    opens_raw, opens_at = req_instant(ctx, "opens_at")
    cutoff_raw, cutoff_at = req_instant(ctx, "cutoff_at")
    if cutoff_at <= opens_at:
        raise ApiError("ERR_VALIDATION", "cutoff_at must be strictly after opens_at.")
    for existing in DB.cycles.values():
        if existing["code"] == code:
            raise ApiError("ERR_VALIDATION", "code must be unique across cycles.")
    row = DB.insert("Cycle", {
        "code": code, "opens_at": opens_raw, "cutoff_at": cutoff_raw,
        "status": "OPEN", "locked_at": None, "received_at": None,
        "exception_deadline_at": None,
    })
    return created(serialize.cycle(row))


@bp.get("/cycles")
@endpoint(R5)
def list_cycles(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", CYCLE_STATUSES)
    rows = [c for c in DB.all("Cycle") if status is None or c["status"] == status]
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/cycles/<cycle_id>")
@endpoint(R5)
def read_cycle(ctx, cycle_id):
    return ok(serialize.cycle(path_row("cycle_id", cycle_id)))


def _action(cycle_id, from_states):
    cycle = path_row("cycle_id", cycle_id)
    gate_cycle_closed(cycle)                       # rung 9
    if cycle["status"] not in from_states:         # rung 15
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    return cycle


@bp.post("/cycles/<cycle_id>/lock")
@endpoint(["ClubAdmin"])
def lock_cycle(ctx, cycle_id):
    cycle = _action(cycle_id, ("OPEN",))
    run_lock(cycle)
    return ok(serialize.cycle(cycle))


@bp.post("/cycles/<cycle_id>/submit")
@endpoint(["ClubAdmin"])
def submit_cycle(ctx, cycle_id):
    cycle = _action(cycle_id, ("LOCKED",))
    qualified = [r for r in recompute.route_runs_of_cycle(cycle)
                 if r["status"] == "QUALIFIED"]
    if not qualified:                              # rung 49
        raise ApiError("ERR_ROUTE_MINIMUM_NOT_MET")
    cycle_ops.submit(cycle)
    return ok(serialize.cycle(cycle))


@bp.post("/cycles/<cycle_id>/receive")
@endpoint(["ClubAdmin", "WarehouseOperator"])
def receive_cycle(ctx, cycle_id):
    cycle = _action(cycle_id, ("SUBMITTED",))
    cycle_ops.receive(cycle)
    return ok(serialize.cycle(cycle))


@bp.post("/cycles/<cycle_id>/consolidate")
@endpoint(["ClubAdmin", "WarehouseOperator"])
def consolidate_cycle(ctx, cycle_id):
    cycle = _action(cycle_id, ("RECEIVED",))
    deadline = clock.parse(cycle["exception_deadline_at"])
    if deadline is None or clock.now() < deadline:   # rung 39
        raise ApiError("ERR_EXCEPTION_WINDOW_OPEN")
    for pallet in cycle_ops.pallets_of_cycle(cycle):  # rung 44
        if pallet["status"] != "SEALED":
            raise ApiError("ERR_PALLETS_NOT_SEALED")
    cycle_ops.consolidate(cycle)
    return ok(serialize.cycle(cycle))


@bp.post("/cycles/<cycle_id>/deliver")
@endpoint(["ClubAdmin", "WarehouseOperator"])
def deliver_cycle(ctx, cycle_id):
    cycle = _action(cycle_id, ("CONSOLIDATED",))
    cycle_ops.deliver(cycle)
    return ok(serialize.cycle(cycle))


@bp.post("/cycles/<cycle_id>/reconcile")
@endpoint(["ClubAdmin", "FinanceOfficer"])
def reconcile_cycle(ctx, cycle_id):
    cycle = _action(cycle_id, ("DELIVERED",))
    for drop_run in recompute.drop_runs_of_cycle(cycle):   # rung 50
        if drop_run["status"] != "SETTLED":
            continue
        posted = [r for r in reconciliation.reconciliations_of(drop_run)
                  if r["status"] == "POSTED"]
        if not posted:
            raise ApiError("ERR_DROP_RECONCILIATION_INCOMPLETE")
    cycle_ops.reconcile(cycle)
    return ok(serialize.cycle(cycle))


@bp.post("/cycles/<cycle_id>/close")
@endpoint(["ClubAdmin"])
def close_cycle(ctx, cycle_id):
    cycle = _action(cycle_id, ("RECONCILED",))
    cycle_ops.close(cycle)
    return ok(serialize.cycle(cycle))


@bp.post("/cycles/<cycle_id>/cancel")
@endpoint(["ClubAdmin"])
def cancel_cycle(ctx, cycle_id):
    cycle = _action(cycle_id, ("OPEN", "LOCKED"))
    cycle_ops.cancel(cycle)
    return ok(serialize.cycle(cycle))
