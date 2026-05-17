"""Vesting-snapshot creation & listing."""

import db
from config import PLAN_ACTIVE
from errors import AppError, ERR_PLAN_NOT_ACTIVE
from utils import stamp_ledger_create, days_between
from services.calculations import vested_percent, vested_balance_cents


def create_snapshot(plan: dict, participant: dict) -> dict:
    if plan["status"] != PLAN_ACTIVE:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE.", 409)
    clock = db.plan_clocks.get(plan["id"])
    current_date = clock["current_date"] if clock else None
    if current_date is None:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan clock not initialized.", 409)

    days = days_between(participant["hire_date"], current_date)
    if days < 0:
        days = 0
    service_years = days // 365
    pct = vested_percent(plan, participant, current_date)
    vested_bal = vested_balance_cents(int(participant.get("total_account_balance_cents", 0)), pct)

    snap = {
        "plan_id": plan["id"],
        "participant_id": participant["id"],
        "vesting_epoch": int(plan.get("current_vesting_epoch", 0)),
        "service_years_completed": int(service_years),
        "vested_pct": pct,
        "vested_balance_cents": int(vested_bal),
    }
    stamp_ledger_create(snap)
    db.vesting_snapshots[snap["id"]] = snap
    return snap


def list_snapshots(plan: dict, participant: dict, limit: int, offset: int):
    items = [v for v in db.vesting_snapshots.values()
             if v.get("plan_id") == plan["id"] and v.get("participant_id") == participant["id"]]
    items.sort(key=lambda v: v.get("created_at", ""))
    total = len(items)
    return items[offset:offset + limit], total
