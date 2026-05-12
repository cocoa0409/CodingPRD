"""Test-driving endpoints (SystemOperator only): _clock/advance and _sweep/run.

Also exposes /_test/reset — a test-only hook (NOT part of PRD) that the
test harness invokes between tests to give each test a clean slate.
"""

from __future__ import annotations

import datetime as _dt

from flask import Blueprint, jsonify

from db import db
from errors import ERR_VALIDATION, raise_api_error
from middleware import require_roles
from response import success_response
from services.common import get_json_body, parse_iso8601_utc

bp = Blueprint("test_driving", __name__)


@bp.post("/_test/reset")
def test_reset():
    """Test-only hook: wipe in-memory state and reset the server clock.
    Not part of PRD; used by the test harness to isolate per-test state.
    Skips auth so the harness can call it without any headers."""
    db.communities.clear()
    db.households.clear()
    db.residents.clear()
    db.point_rules.clear()
    db.disposals.clear()
    db.points_transactions.clear()
    db.mall_items.clear()
    db.redemption_orders.clear()
    db.violations.clear()
    db.ranking_periods.clear()
    db.audit_logs.clear()
    # Reset the logical clock back to a deterministic baseline far in the
    # past so individual tests can advance it forward to any literal year.
    db._logical_now = _dt.datetime(2000, 1, 1, tzinfo=_dt.timezone.utc)
    return jsonify(success_response({})), 200


@bp.post("/_clock/advance")
@require_roles("SystemOperator")
def advance_clock():
    body = get_json_body()
    if "to" not in body or body["to"] is None:
        raise_api_error(ERR_VALIDATION, "Field 'to' is required.")
    target = parse_iso8601_utc(body["to"])
    new_now = db.advance_clock(target)
    return jsonify(success_response({"now": db.now_iso()})), 200


@bp.post("/_sweep/run")
@require_roles("SystemOperator")
def sweep_run():
    now = db.now()
    count = 0
    for r in db.residents.values():
        if r.get("account_status") != "RESTRICTED":
            continue
        until_raw = r.get("restricted_until")
        if not until_raw:
            continue
        until_utc = parse_iso8601_utc(until_raw)
        if until_utc <= now:
            r["account_status"] = "ACTIVE"
            db.stamp_update(r)
            count += 1
    return jsonify(success_response({"residents_unrestricted": count})), 200
