"""Test-driving system endpoints: /_clock/advance, /_quarterly/run, /_settle/run."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_invalid_state
from middleware import require_auth
from response import list_success, success
from routes._helpers import get_json
from services.engine import (
    recompute_all_client_ages,
    settle_trade,
    start_rebalance_run,
    stamp_update,
)
from services.serializers import serialize_rebalance_run, serialize_trade
from utils import iso_now, parse_iso

bp = Blueprint("system_endpoints", __name__)


@bp.post("/_clock/advance")
@require_auth(["system"])
def clock_advance():
    body = get_json()
    target_iso = body.get("to_iso")
    with store.lock:
        if target_iso is None:
            store.clock.advance_tick()
        else:
            try:
                target = parse_iso(target_iso)
            except Exception:
                raise err_invalid_state("to_iso must be ISO 8601.")
            store.clock.advance_to(target)
        recompute_all_client_ages()
    return success({"now": iso_now(store.now())})


@bp.post("/_quarterly/run")
@require_auth(["system"])
def quarterly_run():
    """For each Account whose max_drift_pct >= 5.00 and no current-quarter run, start one."""
    now = store.now()
    cur_q = (now.month - 1) // 3 + 1
    quarter_key = f"{now.year}-Q{cur_q}"
    created = []
    with store.lock:
        for a in list(store.accounts.values()):
            if a["compliance_status"] != "ACTIVE":
                continue
            if (a.get("max_drift_pct") or 0) < 5.00:
                continue
            # Skip if a non-FAILED run already exists for this quarter on this account.
            exists = any(
                r for r in store.rebalance_runs.values()
                if r["account_id"] == a["id"]
                and r["quarter_key"] == quarter_key
                and r["status"] != "FAILED"
            )
            if exists:
                continue
            try:
                run = start_rebalance_run(a, quarter_key, force=False)
                created.append(run)
            except Exception:
                # Skip accounts that can't be started; don't fail the whole batch.
                continue
    return list_success(
        [serialize_rebalance_run(r) for r in created],
        limit=len(created) if created else 10,
        offset=0,
        total_count=len(created),
    )


@bp.post("/_settle/run")
@require_auth(["system"])
def settle_run():
    """Settle every EXECUTED Trade in a single batch."""
    settled = []
    with store.lock:
        to_settle = [t for t in list(store.trades.values()) if t["status"] == "EXECUTED"]
        # Sort by executed_at to keep results deterministic.
        to_settle.sort(key=lambda t: (t.get("executed_at") or "", t["id"]))
        for t in to_settle:
            a = store.accounts.get(t["account_id"])
            if not a:
                continue
            try:
                settle_trade(a, t)
                settled.append(t)
            except Exception:
                continue
    return list_success(
        [serialize_trade(t) for t in settled],
        limit=len(settled) if settled else 10,
        offset=0,
        total_count=len(settled),
    )
