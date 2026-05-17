"""Test-only endpoints: /_clock/advance and /_sweep/run.

Per PRD §2.9 these are exempt from the authentication header check.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, jsonify

from ..clock import clock, iso_format, now
from ..errors import err_invalid_input
from ..helpers import parse_iso8601, require_json_object
from ..responses import success_envelope
from ..services.audit import write_audit
from ..store import reset_store, store

bp = Blueprint("test_infra", __name__)


@bp.route("/__test__/reset", methods=["POST"])
def test_reset():
    """Test-harness only: wipe the in-memory store and reset the clock.

    Not part of PRD surface; enables per-test isolation when the harness
    POSTs this between tests. Returns 200 with an empty envelope on
    success and is intentionally idempotent.
    """
    reset_store()
    return (jsonify(success_envelope({})), 200)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    body = require_json_object()
    seconds = body.get("seconds")
    to = body.get("to")
    if seconds is not None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise err_invalid_input("seconds must be a number")
        new_now = clock.advance_by_seconds(float(seconds))
    elif to is not None:
        dt = parse_iso8601(to, "to")
        new_now = clock.advance_to(dt)
    else:
        raise err_invalid_input("either seconds or to must be supplied")
    return (jsonify(success_envelope({"now": iso_format(new_now)})), 200)


@bp.route("/_sweep/run", methods=["POST"])
def sweep_run():
    s = store()
    no_show_count = 0
    expired_rx_count = 0
    expired_ref_count = 0
    with s.lock:
        t = now()
        # NO_SHOW sweep: SCHEDULED encounters where t > scheduled_end
        for enc in s.encounters.values():
            if enc["status"] == "SCHEDULED" and t > enc["scheduled_end"]:
                enc["status"] = "NO_SHOW"
                enc["updated_at"] = t
                enc["version"] = enc.get("version", 1) + 1
                no_show_count += 1
                write_audit(
                    actor_role="TestHarness",
                    actor_id="_sweep",
                    action="encounter.no_show",
                    target_entity="Encounter",
                    target_id=enc["id"],
                )
        # Prescription EXPIRED sweep: SIGNED or TRANSMITTED where t >= expires_at
        for rx in s.prescriptions.values():
            if rx["status"] in {"SIGNED", "TRANSMITTED"}:
                exp = rx.get("expires_at")
                if exp is not None and t >= exp:
                    rx["status"] = "EXPIRED"
                    rx["updated_at"] = t
                    rx["version"] = rx.get("version", 1) + 1
                    expired_rx_count += 1
        # Referral EXPIRED sweep: PENDING where t >= expires_at
        for ref in s.referrals.values():
            if ref["status"] == "PENDING":
                exp = ref.get("expires_at")
                if exp is not None and t >= exp:
                    ref["status"] = "EXPIRED"
                    ref["updated_at"] = t
                    ref["version"] = ref.get("version", 1) + 1
                    expired_ref_count += 1
    payload = {
        "no_show_count": no_show_count,
        "expired_prescription_count": expired_rx_count,
        "expired_referral_count": expired_ref_count,
    }
    return (jsonify(success_envelope(payload)), 200)
