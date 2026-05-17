"""Vesting epoch refresh & vesting snapshot service (§2.12, §3.4)."""

from services.calculations import vested_percent, vested_balance_cents
from services import lookups
import db


def get_current_date_for_plan(plan: dict):
    """Returns PlanClock.current_date or None when no clock yet."""
    clock = db.plan_clocks.get(plan["id"])
    return clock["current_date"] if clock else None


def lazy_refresh_vested_snapshot(plan: dict, participant: dict) -> None:
    """Lazy vesting epoch refresh per §2.12.

    Recomputes vested_pct_snapshot when vesting_epoch_at_snapshot != plan.current_vesting_epoch
    (which is also forced to refresh when the loan-default cascade has set
    vesting_epoch_at_snapshot to -1).
    """
    plan_epoch = int(plan.get("current_vesting_epoch", 0))
    snap_epoch = int(participant.get("vesting_epoch_at_snapshot", 0))
    if snap_epoch == plan_epoch:
        return

    current_date = get_current_date_for_plan(plan)
    if current_date is None:
        # No clock means the plan isn't ACTIVE yet — fall back to 0.0
        participant["vested_pct_snapshot"] = 0.0
        participant["vesting_epoch_at_snapshot"] = plan_epoch
        return

    pct = vested_percent(plan, participant, current_date)
    participant["vested_pct_snapshot"] = pct
    participant["vesting_epoch_at_snapshot"] = plan_epoch


def current_vested_balance_cents(plan: dict, participant: dict) -> int:
    """Used for computations (NOT writing to participant) — uses fresh vested_pct."""
    current_date = get_current_date_for_plan(plan)
    if current_date is None:
        return 0
    pct = vested_percent(plan, participant, current_date)
    return vested_balance_cents(int(participant.get("total_account_balance_cents", 0)), pct)
