"""Coordinator commission accruals (3 endpoints)."""

from flask import Blueprint

from core import serialize
from core.constants import ACCRUAL_STATUSES, PAYOUT_MODES, ROLES
from core.envelope import ok, page
from core.errors import ApiError
from core.ladder import (endpoint, enum_body, enum_filter, free_filter,
                         gate_cycle_closed, pagination, path_row)
from core.store import DB, touch
from services import commission, credits, reconciliation

bp = Blueprint("commission", __name__)
R5 = list(ROLES)


@bp.get("/commission-accruals")
@endpoint(R5)
def list_accruals(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", ACCRUAL_STATUSES)
    drop_run_id = free_filter(ctx, "drop_run_id")
    coordinator_member_id = free_filter(ctx, "coordinator_member_id")
    rows = []
    for row in DB.all("CommissionAccrual"):
        if drop_run_id is not None and row["drop_run_id"] != drop_run_id:
            continue
        if coordinator_member_id is not None and row["coordinator_member_id"] != coordinator_member_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/commission-accruals/<commission_accrual_id>")
@endpoint(R5)
def read_accrual(ctx, commission_accrual_id):
    return ok(serialize.commission_accrual(
        path_row("commission_accrual_id", commission_accrual_id)))


@bp.post("/commission-accruals/<commission_accrual_id>/payout")
@endpoint(["ClubAdmin", "FinanceOfficer"])
def payout_accrual(ctx, commission_accrual_id):
    accrual = path_row("commission_accrual_id", commission_accrual_id)   # rung 4
    if "payout_mode" not in ctx.body or ctx.body["payout_mode"] is None:  # rung 7
        raise ApiError("ERR_VALIDATION", "payout_mode is required.")
    payout_mode = enum_body(ctx, "payout_mode", PAYOUT_MODES, required=True)  # rung 8
    gate_cycle_closed(accrual)                             # rung 9
    drop_run = DB.get("DropRun", accrual["drop_run_id"])
    posted = [r for r in reconciliation.reconciliations_of(drop_run)
              if r["status"] == "POSTED"] if drop_run else []
    if accrual["status"] not in ("ACCRUED", "ADJUSTED") or not posted:    # rung 22
        raise ApiError("ERR_INVALID_ACCRUAL_STATE")
    if payout_mode == "STORE_CREDIT" and not drop_run["volunteer_obligation_met"]:  # rung 54
        raise ApiError("ERR_VOLUNTEER_OBLIGATION_UNMET")
    credits.sweep(accrual["coordinator_member_id"])
    value = commission.payout_value(accrual["net_cents"], payout_mode)
    accrual["payout_mode"] = payout_mode
    accrual["payout_value_cents"] = value
    accrual["status"] = "PAID"
    touch(accrual)
    if payout_mode == "STORE_CREDIT":
        credits.mint(accrual["coordinator_member_id"], value,
                     credits.default_expiry_iso(), "COMMISSION")
    return ok(serialize.commission_accrual(accrual))
