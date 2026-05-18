"""Test-only reset endpoint. Wipes the in-memory store between tests so
state from prior test cases does not leak into the next. Not part of
the public PRD endpoint surface — only invoked by the test harness."""

from datetime import datetime, timezone

from flask import Blueprint

from db import store, Clock
from response import success

test_reset_bp = Blueprint("test_reset", __name__)


@test_reset_bp.post("/__test__/reset")
def test_reset():
    with store.lock:
        store.owners.clear()
        store.hearing_officers.clear()
        store.properties.clear()
        store.assessments.clear()
        store.exemption_applications.clear()
        store.appeals.clear()
        store.hearings.clear()
        store.tax_bills.clear()
        store.deferral_plans.clear()
        store.payments.clear()
        store.clock = Clock()
    return success({}, status_code=200)
