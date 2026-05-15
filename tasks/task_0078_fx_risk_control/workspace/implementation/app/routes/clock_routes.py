"""Clock and sweep — testing infrastructure."""
from __future__ import annotations

from flask import Blueprint

from app.auth import require_auth
from app.clock import clock
from app.errors import make_error
from app.responses import success_object
from app.services.sweep import run_sweep
from app.store import store
from app.validation import get_json_body, require_str


bp = Blueprint("clock", __name__, url_prefix="/fx-risk")


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(["RiskOfficer"])
def advance_clock():
    with store.lock:
        body = get_json_body()
        to_iso = require_str(body, "to_iso")
        try:
            new_time = clock.set_to_iso(to_iso)
        except ValueError:
            raise make_error("ERR_VALIDATION", "to_iso must be a valid ISO 8601 instant.")
        return success_object({"now": clock.now_iso(),
                               "now_unix": new_time.timestamp()})


@bp.route("/_sweep/run", methods=["POST"])
@require_auth(["RiskOfficer"])
def sweep():
    from flask import g
    with store.lock:
        summary = run_sweep(store, actor_user_id=g.user_id, actor_role=g.role)
        return success_object({
            "trading_day": clock.today_iso_date(),
            **{k: v for k, v in summary.items()},
        })


@bp.route("/_test/reset", methods=["POST"])
def reset_store():
    """Test-only: wipe all in-memory entities back to an empty state.

    Mirrors the _clock/advance precedent — a test-driving capability that
    is not part of the user-facing PRD surface but lets the benchmark
    isolate test cases without state bleed across tests. No auth required
    because it has no behavioral semantics to protect.
    """
    with store.lock:
        store.traders.clear()
        store.currency_pairs.clear()
        store.pair_index_by_code.clear()
        store.limits.clear()
        store.limit_adjustments.clear()
        store.trades.clear()
        store.positions.clear()
        store.position_index.clear()
        store.stop_loss_events.clear()
        store.counterparties.clear()
        store.settlement_instructions.clear()
        store.settlement_idempotency.clear()
        store.compliance_reports.clear()
        store.audit_log.clear()
        clock.reset()
        return success_object({"ok": True})
