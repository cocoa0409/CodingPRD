"""Test-driving admin routes: clock advance, sweep run."""
from __future__ import annotations

from flask import Blueprint

import config as cfg
from db import store
from errors import err_validation
from middleware import require_auth
from response import success
from routes._helpers import get_json, require_int
from services.engine import apply_acat_time_gates


bp = Blueprint("admin", __name__)


# ── POST /brokerage/_clock/advance ─────────────────────────────────────────

@bp.post("/brokerage/_clock/advance")
@require_auth([cfg.ROLE_ADMIN])
def advance_clock():
    body = get_json()
    seconds = require_int(body, "seconds", minimum=0)
    with store.lock:
        store.clock.advance_seconds(seconds)
        apply_acat_time_gates(store.now())
    return success({}, 200)


# ── POST /brokerage/_sweep/run ─────────────────────────────────────────────

@bp.post("/brokerage/_sweep/run")
@require_auth([cfg.ROLE_ADMIN])
def run_sweep():
    with store.lock:
        apply_acat_time_gates(store.now())
        # Re-run PDT check across every account for completeness.
        from services.engine import evaluate_pdt

        for a in list(store.accounts.values()):
            evaluate_pdt(a, store.now())
    return success({}, 200)
