"""Drop reconciliations (5 endpoints)."""

from flask import Blueprint

from core import clock, serialize
from core.constants import RECON_STATUSES, ROLES
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (body_fk, endpoint, enum_filter, free_filter,
                         gate_cycle_closed, gate_posted_ledger, pagination,
                         path_row, req_id, req_int, rung_occ)
from core.store import DB, touch
from services import reconciliation

bp = Blueprint("recon", __name__)
R5 = list(ROLES)


@bp.post("/drop-reconciliations")
@endpoint(["ClubAdmin", "FinanceOfficer"])
def create_reconciliation(ctx):
    drop_run = body_fk(ctx, "drop_run_id")                 # rung 5
    req_id(ctx, "drop_run_id")                             # rung 7
    req_int(ctx, "expected_drop_run_version")
    gate_cycle_closed(drop_run)                            # rung 9
    gate_posted_ledger(drop_run)                           # rung 12
    rung_occ(ctx, "expected_drop_run_version", drop_run)   # rung 25
    for existing in reconciliation.reconciliations_of(drop_run):
        if existing["status"] in ("BALANCED", "VARIANCE_HELD"):
            existing["status"] = "VOID"
            touch(existing)
    row = reconciliation.draft(drop_run, ctx.user_id)
    touch(drop_run)
    return created(serialize.drop_reconciliation(row))


@bp.get("/drop-reconciliations")
@endpoint(R5)
def list_reconciliations(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", RECON_STATUSES)
    drop_run_id = free_filter(ctx, "drop_run_id")
    rows = []
    for row in DB.all("DropReconciliation"):
        if drop_run_id is not None and row["drop_run_id"] != drop_run_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/drop-reconciliations/<drop_reconciliation_id>")
@endpoint(R5)
def read_reconciliation(ctx, drop_reconciliation_id):
    return ok(serialize.drop_reconciliation(
        path_row("drop_reconciliation_id", drop_reconciliation_id)))


@bp.post("/drop-reconciliations/<drop_reconciliation_id>/post")
@endpoint(["ClubAdmin", "FinanceOfficer"])
def post_reconciliation(ctx, drop_reconciliation_id):
    recon = path_row("drop_reconciliation_id", drop_reconciliation_id)   # rung 4
    gate_cycle_closed(recon)                               # rung 9
    if recon["status"] != "BALANCED":                      # rung 21
        raise ApiError("ERR_INVALID_RECONCILIATION_STATE")
    if ctx.user_id == recon["prepared_by_user_id"]:        # rung 46
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    drop_run = DB.get("DropRun", recon["drop_run_id"])
    cycle = DB.get("Cycle", drop_run["cycle_id"]) if drop_run else None
    if cycle is None or cycle["status"] != "DELIVERED":    # rung 47
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    recon["status"] = "POSTED"
    recon["posted_by_user_id"] = ctx.user_id
    recon["posted_at"] = clock.now_iso()
    touch(recon)
    return ok(serialize.drop_reconciliation(recon))


@bp.post("/drop-reconciliations/<drop_reconciliation_id>/resolve-variance")
@endpoint(["ClubAdmin", "FinanceOfficer"])
def resolve_variance(ctx, drop_reconciliation_id):
    recon = path_row("drop_reconciliation_id", drop_reconciliation_id)   # rung 4
    adjustment = req_int(ctx, "adjustment_cents")          # rung 7
    gate_cycle_closed(recon)                               # rung 9
    drop_run = DB.get("DropRun", recon["drop_run_id"])
    gate_posted_ledger(drop_run)                           # rung 12
    if recon["status"] != "VARIANCE_HELD":                 # rung 21
        raise ApiError("ERR_INVALID_RECONCILIATION_STATE")
    if adjustment != recon["variance_cents"]:              # rung 48
        raise ApiError("ERR_VARIANCE_UNRESOLVED")
    recon["club_margin_cents"] += adjustment
    recon["variance_cents"] = recon["member_charges_cents"] - (
        recon["supplier_cost_cents"] + recon["freight_alloc_cents"]
        + recon["reefer_alloc_cents"] + recon["commission_cents"]
        + recon["club_margin_cents"])
    recon["status"] = "BALANCED"
    touch(recon)
    return ok(serialize.drop_reconciliation(recon))
