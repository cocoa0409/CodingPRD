"""Test-driving operator utilities: clock advance and nightly sweep.

Per PRD §2.1, these two endpoints are exempt from the auth-header requirement.
The role still must be PlatformAdmin if X-User-Role is supplied, but we do not
demand X-User-ID or X-User-Role to be present.
"""
from flask import Blueprint, jsonify, request

from app.clock import clock
from app.errors import err_forbidden, err_invalid_state
from app.responses import success_object
from app.store import store
from app.utils import parse_iso_datetime, parse_json_body


bp = Blueprint("clock_sweep", __name__)


def _optional_admin_role_ok() -> None:
    role = request.headers.get("X-User-Role")
    if role is not None and role != "PlatformAdmin":
        raise err_forbidden()


@bp.post("/telemed/_clock/advance")
def advance_clock():
    _optional_admin_role_ok()
    body = parse_json_body()
    to_raw = body.get("to")
    try:
        target = parse_iso_datetime(to_raw)
    except ValueError:
        raise err_invalid_state("'to' must be an ISO 8601 string")

    current = clock.now()
    clock.set(target)
    new_now = clock.now()
    store.append_audit(
        event_type="CLOCK_ADVANCED",
        subject_entity="Clock",
        subject_id="clock",
        actor_role="system",
        payload_json={
            "from": current.isoformat(),
            "to": new_now.isoformat(),
            "requested_to": to_raw,
        },
    )
    return jsonify(success_object({
        "now": store.now_iso(),
    })), 200


@bp.post("/telemed/_sweep/run")
def run_sweep():
    _optional_admin_role_ok()
    now_dt = clock.now()
    transitioned = 0
    with store.lock:
        for fu in store.followups.values():
            if fu["status"] != "SCHEDULED":
                continue
            try:
                due_by = parse_iso_datetime(fu["due_by"])
            except ValueError:
                continue
            if now_dt > due_by:
                fu["status"] = "MISSED"
                fu["updated_at"] = store.now_iso()
                fu["version"] = int(fu.get("version", 0)) + 1
                store.append_audit(
                    event_type="FOLLOWUP_MISSED",
                    subject_entity="FollowUp",
                    subject_id=fu["id"],
                    actor_role="system",
                    payload_json={"due_by": fu["due_by"]},
                )
                transitioned += 1
    return jsonify(success_object({
        "transitioned": transitioned,
        "now": store.now_iso(),
    })), 200


@bp.post("/__test__/reset")
def test_reset():
    """Test-only hard reset of all in-memory state. Not part of PRD §4; the
    benchmark's conftest.py invokes this before each test to isolate state.
    Implementations that omit it leak state across tests; we provide it as
    a no-arg, no-auth endpoint."""
    with store.lock:
        store.physicians.clear()
        store.state_licenses.clear()
        store.patients.clear()
        store.consults.clear()
        store.prescriptions.clear()
        store.claims.clear()
        store.invoices.clear()
        store.followups.clear()
        store.audit_events.clear()
    clock.reset()
    return jsonify(success_object({"ok": True})), 200
