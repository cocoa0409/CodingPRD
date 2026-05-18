"""Test-only convenience endpoint.

The benchmark harness calls POST /__test__/reset between tests to wipe
in-memory state (entities + logical clock) so each test starts from a
deterministic baseline. This route is NOT a PRD-required surface; it
exists exclusively to support the test harness.
"""
from __future__ import annotations

from flask import Blueprint

from db import store, _Clock
from response import success


bp = Blueprint("test_infra", __name__)


@bp.post("/__test__/reset")
def reset():
    with store.lock:
        store.agents.clear()
        store.listings.clear()
        store.buyers.clear()
        store.lockboxes.clear()
        store.lockbox_by_listing.clear()
        store.showings.clear()
        store.offers.clear()
        store.counters.clear()
        store.contingencies.clear()
        store.commission_splits.clear()
        store.active_license_numbers.clear()
        store.lockbox_serials.clear()
        # Reset logical clock to a fresh wall-clock anchor so subsequent
        # tests that build expires_at via wall-clock + offset see a
        # consistent baseline.
        store.clock = _Clock()
    return success({"reset": True}, 200)
