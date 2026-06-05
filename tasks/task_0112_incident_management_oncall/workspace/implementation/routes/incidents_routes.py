"""Incident hub: trigger, acknowledge, resolve, escalate, page-attempt lists."""
from flask import Blueprint, request

import response
from db import db
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body, get_pagination
from services.common import require_str, require_enum, stamp_create, touch
from services.lookups import get_service, get_policy, get_incident, get_page_attempt
from services.serializers import incident_out, page_attempt_out
from services import sla, escalation as esc, windows as win_svc, budget

bp = Blueprint("incidents", __name__)

ALL_ROLES = {"PlatformAdmin", "IncidentCommander", "ResponderUser"}
ADMIN_IC = {"PlatformAdmin", "IncidentCommander"}
SEVERITIES = {"SEV1", "SEV2", "SEV3", "SEV4"}


@bp.route("/incidents", methods=["POST"])
def trigger_incident():
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    body = get_json_body()
    service_id = require_str(body, "service_id")
    policy_id = require_str(body, "policy_id")
    with db.lock:
        svc = get_service(service_id)       # FK existence (priority 3)
        get_policy(policy_id)
        title = require_str(body, "title")   # shape (priority 4)
        severity = require_enum(body, "severity", SEVERITIES)

        now = db.clock.now()
        ack_deadline, res_deadline = sla.compute_deadlines(now, severity, svc)
        inc = stamp_create({
            "service_id": service_id,
            "policy_id": policy_id,
            "title": title,
            "severity": severity,
            "lifecycle_status": "TRIGGERED",
            "escalation_status": "PENDING",
            "current_tier_level": 0,
            "triggered_at": now,
            "acknowledged_at": None,
            "resolved_at": None,
            "ack_deadline_at": ack_deadline,
            "resolve_deadline_at": res_deadline,
            "counts_against_budget": True,
            "downtime_minutes": 0,
            "_tier_index": 0,
            "_round_index": 0,
        })

        if win_svc.active_window_covers(service_id):
            # Born suppressed: no page, no PageAttempt.
            inc["lifecycle_status"] = "SUPPRESSED"
            inc["counts_against_budget"] = False
            inc["escalation_status"] = "EXHAUSTED"
            db.incidents[inc["id"]] = inc
        else:
            # First page automatically — must reach a target or fail the whole
            # trigger (ERR_NO_ESCALATION_TARGET). Stage before committing.
            esc.first_page(inc)  # raises before any state stored
            db.incidents[inc["id"]] = inc
    return response.success(incident_out(inc), 201)


@bp.route("/incidents/<iid>", methods=["GET"])
def get_one_incident(iid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        inc = get_incident(iid)
        return response.success(incident_out(inc), 200)


@bp.route("/incidents/<iid>/acknowledge", methods=["POST"])
def acknowledge_incident(iid):
    user_id, role = require_user_context()
    require_role(role, {"ResponderUser"})
    with db.lock:
        inc = get_incident(iid)
        # state (priority 6)
        if inc["lifecycle_status"] != "TRIGGERED":
            raise ApiError("ERR_INCIDENT_NOT_TRIGGERED", "Incident is not TRIGGERED.")
        # safety (priority 8): acting responder must have been paged
        paged = any(
            pa["incident_id"] == iid and pa["responder_id"] == user_id
            for pa in db.page_attempts.values()
        )
        if not paged:
            raise ApiError("ERR_RESPONDER_NOT_PAGED", "Acting responder was not paged for this incident.")
        now = db.clock.now()
        inc["lifecycle_status"] = "ACKNOWLEDGED"
        inc["acknowledged_at"] = now
        if inc["escalation_status"] == "ESCALATING":
            inc["escalation_status"] = "EXHAUSTED"  # halt ladder; tier frozen
        touch(inc)
        return response.success(incident_out(inc), 200)


@bp.route("/incidents/<iid>/resolve", methods=["POST"])
def resolve_incident(iid):
    _, role = require_user_context()
    require_role(role, {"ResponderUser", "IncidentCommander"})
    with db.lock:
        inc = get_incident(iid)
        if inc["lifecycle_status"] != "ACKNOWLEDGED":
            raise ApiError("ERR_INCIDENT_NOT_ACKNOWLEDGED", "Incident is not ACKNOWLEDGED.")
        now = db.clock.now()
        inc["lifecycle_status"] = "RESOLVED"
        inc["resolved_at"] = now
        inc["downtime_minutes"] = budget.incident_downtime_minutes(inc)
        touch(inc)
        # CASCADE onto parent service: consumed -> remaining -> budget_status.
        # Each hop is an independent mutation of the service (updated_at +
        # version). Computed fields are derived on read; we bump version three
        # times to reflect the three independent recomputations (PRD 3.7).
        svc = db.services.get(inc["service_id"])
        if svc is not None:
            for _ in range(3):
                touch(svc)
        return response.success(incident_out(inc), 200)


@bp.route("/incidents/<iid>/escalate", methods=["POST"])
def escalate_incident(iid):
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    body = get_json_body()
    with db.lock:
        inc = get_incident(iid)
        # shape (priority 4): expected_incident_version required integer
        expected = body.get("expected_incident_version")
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError("ERR_INVALID_REQUEST", "expected_incident_version is required and must be an integer.")
        # state (priority 6): lifecycle must be TRIGGERED
        if inc["lifecycle_status"] != "TRIGGERED":
            raise ApiError("ERR_INCIDENT_NOT_TRIGGERED", "Incident is not TRIGGERED.")
        # OCC (priority: concurrency) — stale view rejected with 412
        if expected != inc["version"]:
            raise ApiError("ERR_STALE_VERSION", "expected_incident_version does not match.")
        # advance the ladder; ERR_NO_ESCALATION_TARGET raises before any change
        esc.manual_escalate(inc)
        touch(inc)
        return response.success(incident_out(inc), 200)


@bp.route("/incidents/<iid>/page-attempts", methods=["GET"])
def list_incident_page_attempts(iid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        get_incident(iid)
        rows = [pa for pa in db.page_attempts.values() if pa["incident_id"] == iid]
        return response.list_response(rows, limit, offset, page_attempt_out)


@bp.route("/page-attempts", methods=["GET"])
def list_page_attempts():
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    limit, offset = get_pagination()
    responder_id = request.args.get("responder_id")
    incident_id = request.args.get("incident_id")
    with db.lock:
        rows = list(db.page_attempts.values())
        if responder_id is not None:
            rows = [r for r in rows if r["responder_id"] == responder_id]
        if incident_id is not None:
            rows = [r for r in rows if r["incident_id"] == incident_id]
        return response.list_response(rows, limit, offset, page_attempt_out)


@bp.route("/page-attempts/<pid>", methods=["GET"])
def get_one_page_attempt(pid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    with db.lock:
        pa = get_page_attempt(pid)
        return response.success(page_attempt_out(pa), 200)
