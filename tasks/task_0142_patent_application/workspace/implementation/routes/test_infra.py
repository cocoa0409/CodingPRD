"""Test-only convenience endpoint.

The benchmark harness calls POST /__test__/reset between tests to wipe
in-memory state (entities + clock) so that each test starts from a
deterministic baseline. This route is NOT a PRD-required surface; it
exists exclusively to support the test harness.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint

from db import store
from response import success


test_infra_bp = Blueprint("test_infra", __name__)


@test_infra_bp.post("/__test__/reset")
def reset():
    """Wipe every in-memory table and reset the logical clock to UTC now.

    Auth is intentionally NOT required because the harness invokes this
    between tests as infrastructure, not as a PRD-modeled action.
    """
    with store.lock:
        store.applicants.clear()
        store.applications.clear()
        store.office_actions.clear()
        store.responses.clear()
        store.fee_transactions.clear()
        store.maintenance_fees.clear()
        store.pct_phases.clear()
        store.audit_events.clear()
        store.idempotency_cache.clear()
        # Reset the logical clock to an early sentinel instant so subsequent
        # tests can freely advance it forward to any anchor (including
        # calendar-clean fixtures dated in the past) without tripping the
        # "may only move forward" guard from PRD §2.8.
        store._clock = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return success({"reset": True})
