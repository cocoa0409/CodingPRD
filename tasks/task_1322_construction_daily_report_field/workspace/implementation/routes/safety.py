"""SafetyObservation and Incident routes."""
import json
from flask import Blueprint, request

from auth import ctx, need
from calc import (
    bump_report,
    touch,
    apply_hold_cascade,
    osha_deadline,
    is_recordable,
)
from clock import clock
from db import store
from envelope import success
from errors import ApiError, bad
from route_helpers import stamp, list_response
from serializers import ser_safety_observation, ser_incident
from routes.daily_reports import get_report, require_editable
from routes.setup_resources import get_work_area
from validate import (
    body,
    req_str,
    opt_str,
    req_int,
    opt_int,
    req_enum,
    req_dt,
    opt_date,
)

bp = Blueprint("safety", __name__)

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")
OBS_STATUSES = ("OPEN", "MITIGATED", "VERIFIED_CLOSED", "ESCALATED")
SEVERITIES = (
    "FIRST_AID",
    "NEAR_MISS",
    "PROPERTY_DAMAGE",
    "MEDICAL_TREATMENT",
    "LOST_TIME",
    "FATALITY",
)
INCIDENT_STATUSES = (
    "REPORTED",
    "UNDER_INVESTIGATION",
    "OSHA_NOTIFIED",
    "CLOSED_RECORDABLE",
    "CLOSED_NOT_RECORDABLE",
)
NARRATIVE_MIN = 50


def get_observation(oid):
    o = store.safety_observations.get(oid)
    if o is None:
        raise ApiError("ERR_OBSERVATION_NOT_FOUND", 404, "SafetyObservation not found")
    return o


def get_incident(iid):
    i = store.incidents.get(iid)
    if i is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND", 404, "Incident not found")
    return i


def _check_report_not_locked(report):
    if report["status"] == "LOCKED":
        raise ApiError(
            "ERR_INCIDENT_ON_LOCKED_REPORT",
            409,
            "Incident operations are forbidden on a LOCKED report",
        )


def _create_incident(report_id, work_area_id, occurred_at, severity, narrative,
                     injured_count, days_away, safety_observation_id, created_by):
    rec = stamp(
        {
            "report_id": report_id,
            "work_area_id": work_area_id,
            "safety_observation_id": safety_observation_id,
            "occurred_at": occurred_at,
            "severity": severity,
            "injured_count": injured_count,
            "days_away": days_away,
            "narrative": narrative,
            "recordable": is_recordable(severity),
            "osha_notification_deadline": osha_deadline(severity, occurred_at),
            "osha_notified_at": None,
            "status": "REPORTED",
            "created_by_user_id": created_by,
        }
    )
    store.incidents[rec["id"]] = rec
    report = get_report(report_id)
    apply_hold_cascade(report)
    bump_report(report)
    return rec


def _fingerprint(path, b):
    return json.dumps(b, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# safety observations
# ---------------------------------------------------------------------------

@bp.post("/safety-observations")
def create_observation():
    uid, role = ctx()
    need(role, ["SafetyOfficer"])
    b = body()
    report_id = req_str(b, "report_id")
    work_area_id = req_str(b, "work_area_id")
    description = req_str(b, "description")
    risk_level = req_enum(b, "risk_level", RISK_LEVELS)
    corrective_action = opt_str(b, "corrective_action")
    due_date = opt_date(b, "due_date")
    media_attachment_id = opt_str(b, "media_attachment_id")
    # priority 5: body FK existence
    report = get_report(report_id)
    area = get_work_area(work_area_id)
    media = None
    if media_attachment_id is not None:
        media = store.media_attachments.get(media_attachment_id)
        if media is None:
            raise ApiError("ERR_MEDIA_NOT_FOUND", 404, "MediaAttachment not found")
    # priority 6.1: posture gate
    require_editable(report)
    # priority 7: HIGH risk requires media
    if risk_level == "HIGH" and media_attachment_id is None:
        raise ApiError(
            "ERR_HIGH_RISK_OBSERVATION_REQUIRES_MEDIA",
            422,
            "risk_level HIGH requires media_attachment_id",
        )
    # priority 10: work area open
    if area["status"] != "OPEN":
        raise ApiError("ERR_WORK_AREA_CLOSED", 409, "WorkArea is CLOSED")
    # priority 10.2: media ACTIVE and on same report
    if media is not None and (
        media["status"] != "ACTIVE" or media["report_id"] != report_id
    ):
        raise ApiError(
            "ERR_MEDIA_REPORT_MISMATCH",
            422,
            "Media must be ACTIVE and belong to the same report",
        )
    rec = stamp(
        {
            "report_id": report_id,
            "work_area_id": work_area_id,
            "description": description,
            "risk_level": risk_level,
            "corrective_action": corrective_action,
            "due_date": due_date,
            "media_attachment_id": media_attachment_id,
            "status": "OPEN",
            "created_by_user_id": uid,
            "incident_id": None,
        }
    )
    store.safety_observations[rec["id"]] = rec
    bump_report(report)
    return success(ser_safety_observation(rec), 201)


@bp.get("/safety-observations/<oid>")
def get_one_observation(oid):
    ctx()
    return success(ser_safety_observation(get_observation(oid)), 200)


@bp.get("/safety-observations")
def list_observations():
    ctx()
    report_id = request.args.get("report_id")
    work_area_id = request.args.get("work_area_id")
    status = request.args.get("status")
    risk_level = request.args.get("risk_level")
    incident_id = request.args.get("incident_id")
    media_attachment_id = request.args.get("media_attachment_id")
    if status is not None and status not in OBS_STATUSES:
        bad("Invalid status filter")
    if risk_level is not None and risk_level not in RISK_LEVELS:
        bad("Invalid risk_level filter")
    rows = list(store.safety_observations.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if work_area_id is not None:
        rows = [r for r in rows if r["work_area_id"] == work_area_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if risk_level is not None:
        rows = [r for r in rows if r["risk_level"] == risk_level]
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if media_attachment_id is not None:
        rows = [r for r in rows if r["media_attachment_id"] == media_attachment_id]
    return list_response(rows, ser_safety_observation)


def _obs_transition(oid, from_state, to_state):
    _, role = ctx()
    need(role, ["SafetyOfficer"])
    o = get_observation(oid)
    if o["status"] != from_state:
        raise ApiError(
            "ERR_OBSERVATION_INVALID_TRANSITION",
            409,
            "SafetyObservation status does not allow this transition",
        )
    o["status"] = to_state
    touch(o)
    bump_report(get_report(o["report_id"]))
    return success(ser_safety_observation(o), 200)


@bp.post("/safety-observations/<oid>/mitigate")
def mitigate_observation(oid):
    return _obs_transition(oid, "OPEN", "MITIGATED")


@bp.post("/safety-observations/<oid>/verify-close")
def verify_close_observation(oid):
    uid, role = ctx()
    need(role, ["SafetyOfficer"])
    o = get_observation(oid)
    if o["status"] != "MITIGATED":
        raise ApiError(
            "ERR_OBSERVATION_INVALID_TRANSITION",
            409,
            "SafetyObservation must be MITIGATED",
        )
    if uid == o["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "Verifier must differ from the observation creator",
        )
    o["status"] = "VERIFIED_CLOSED"
    touch(o)
    bump_report(get_report(o["report_id"]))
    return success(ser_safety_observation(o), 200)


@bp.post("/safety-observations/<oid>/reopen")
def reopen_observation(oid):
    return _obs_transition(oid, "MITIGATED", "OPEN")


@bp.post("/safety-observations/<oid>/escalate")
def escalate_observation(oid):
    uid, role = ctx()
    need(role, ["SafetyOfficer"])
    o = get_observation(oid)
    if o["status"] != "OPEN":
        raise ApiError(
            "ERR_OBSERVATION_INVALID_TRANSITION",
            409,
            "SafetyObservation must be OPEN to escalate",
        )
    # priority 6.2: locked-report gate (carve-out from posture gate)
    report = get_report(o["report_id"])
    _check_report_not_locked(report)
    inc = _create_incident(
        report_id=o["report_id"],
        work_area_id=o["work_area_id"],
        occurred_at=clock.now(),
        severity="MEDICAL_TREATMENT",
        narrative=o["description"],
        injured_count=0,
        days_away=0,
        safety_observation_id=o["id"],
        created_by=uid,
    )
    o["status"] = "ESCALATED"
    o["incident_id"] = inc["id"]
    touch(o)
    return success(ser_safety_observation(o), 200)


# ---------------------------------------------------------------------------
# incidents
# ---------------------------------------------------------------------------

@bp.post("/incidents")
def create_incident():
    uid, role = ctx()
    need(role, ["SafetyOfficer"])
    b = body()
    report_id = req_str(b, "report_id")
    work_area_id = req_str(b, "work_area_id")
    occurred_at = req_dt(b, "occurred_at")
    severity = req_enum(b, "severity", SEVERITIES)
    narrative = req_str(b, "narrative")
    injured_count = opt_int(b, "injured_count", 0, mn=0)
    days_away = opt_int(b, "days_away", 0, mn=0)
    safety_observation_id = opt_str(b, "safety_observation_id")
    idempotency_key = opt_str(b, "idempotency_key")
    # priority 5: body FK existence
    report = get_report(report_id)
    area = get_work_area(work_area_id)
    if safety_observation_id is not None:
        get_observation(safety_observation_id)
    # priority 6.2: locked-report gate (carve-out from posture gate)
    _check_report_not_locked(report)
    # priority 7.1: narrative >= 50 chars for recordable severities
    if severity in ("MEDICAL_TREATMENT", "LOST_TIME", "FATALITY") and len(
        narrative
    ) < NARRATIVE_MIN:
        raise ApiError(
            "ERR_INCIDENT_NARRATIVE_REQUIRED",
            422,
            "narrative must be at least 50 characters for this severity",
        )
    # priority 8.5: idempotency
    if idempotency_key is not None:
        ikey = ("/incidents", uid, idempotency_key)
        prior = store.idempotency.get(ikey)
        if prior is not None:
            if prior["fingerprint"] != _fingerprint("/incidents", b):
                raise ApiError(
                    "ERR_IDEMPOTENCY_CONFLICT",
                    409,
                    "idempotency_key reused with a different request body",
                )
            return success(
                ser_incident(store.incidents[prior["entity_id"]]), 201
            )
    # priority 9.3: occurred_at must not be in the future
    if occurred_at > clock.now():
        raise ApiError(
            "ERR_INCIDENT_OCCURRED_IN_FUTURE",
            422,
            "occurred_at is after the logical current time",
        )
    # priority 10: work area open
    if area["status"] != "OPEN":
        raise ApiError("ERR_WORK_AREA_CLOSED", 409, "WorkArea is CLOSED")
    rec = _create_incident(
        report_id=report_id,
        work_area_id=work_area_id,
        occurred_at=occurred_at,
        severity=severity,
        narrative=narrative,
        injured_count=injured_count,
        days_away=days_away,
        safety_observation_id=safety_observation_id,
        created_by=uid,
    )
    if idempotency_key is not None:
        store.idempotency[("/incidents", uid, idempotency_key)] = {
            "fingerprint": _fingerprint("/incidents", b),
            "entity_id": rec["id"],
        }
    return success(ser_incident(rec), 201)


@bp.get("/incidents/<iid>")
def get_one_incident(iid):
    ctx()
    return success(ser_incident(get_incident(iid)), 200)


@bp.get("/incidents")
def list_incidents():
    ctx()
    report_id = request.args.get("report_id")
    work_area_id = request.args.get("work_area_id")
    status = request.args.get("status")
    recordable = request.args.get("recordable")
    safety_observation_id = request.args.get("safety_observation_id")
    if status is not None and status not in INCIDENT_STATUSES:
        bad("Invalid status filter")
    rec_filter = None
    if recordable is not None:
        if recordable not in ("true", "false"):
            bad("Invalid recordable filter")
        rec_filter = recordable == "true"
    rows = list(store.incidents.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if work_area_id is not None:
        rows = [r for r in rows if r["work_area_id"] == work_area_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if rec_filter is not None:
        rows = [r for r in rows if r["recordable"] == rec_filter]
    if safety_observation_id is not None:
        rows = [r for r in rows if r["safety_observation_id"] == safety_observation_id]
    return list_response(rows, ser_incident)


@bp.post("/incidents/<iid>/begin-investigation")
def begin_investigation(iid):
    _, role = ctx()
    need(role, ["SafetyOfficer"])
    inc = get_incident(iid)
    if inc["status"] != "REPORTED":
        raise ApiError(
            "ERR_INCIDENT_INVALID_TRANSITION",
            409,
            "Incident must be REPORTED to begin investigation",
        )
    inc["status"] = "UNDER_INVESTIGATION"
    touch(inc)
    bump_report(get_report(inc["report_id"]))
    return success(ser_incident(inc), 200)


@bp.post("/incidents/<iid>/notify-osha")
def notify_osha(iid):
    _, role = ctx()
    need(role, ["SafetyOfficer"])
    inc = get_incident(iid)
    if inc["status"] not in ("REPORTED", "UNDER_INVESTIGATION"):
        raise ApiError(
            "ERR_INCIDENT_INVALID_TRANSITION",
            409,
            "Incident status does not allow OSHA notification",
        )
    # priority 7.5: recordable only
    if not inc["recordable"]:
        raise ApiError(
            "ERR_OSHA_NOT_APPLICABLE",
            409,
            "OSHA notification applies only to recordable incidents",
        )
    inc["status"] = "OSHA_NOTIFIED"
    inc["osha_notified_at"] = clock.now()
    touch(inc)
    bump_report(get_report(inc["report_id"]))
    return success(ser_incident(inc), 200)


@bp.post("/incidents/<iid>/close")
def close_incident(iid):
    uid, role = ctx()
    need(role, ["SafetyOfficer"])
    inc = get_incident(iid)
    b = body()
    outcome = req_enum(b, "outcome", ("RECORDABLE", "NOT_RECORDABLE"))
    # priority 6: state per outcome
    if outcome == "NOT_RECORDABLE":
        allowed = ("REPORTED", "UNDER_INVESTIGATION")
    else:
        allowed = ("REPORTED", "UNDER_INVESTIGATION", "OSHA_NOTIFIED")
    if inc["status"] not in allowed:
        raise ApiError(
            "ERR_INCIDENT_INVALID_TRANSITION",
            409,
            "Incident status does not allow this close outcome",
        )
    if outcome == "RECORDABLE":
        # priority 7.2: linked ACTIVE media required
        has_media = any(
            m["linked_incident_id"] == inc["id"] and m["status"] == "ACTIVE"
            for m in store.media_attachments.values()
        )
        if not has_media:
            raise ApiError(
                "ERR_INCIDENT_MEDIA_REQUIRED",
                409,
                "A RECORDABLE close requires an ACTIVE linked MediaAttachment",
            )
        # priority 7.3: OSHA notification when a deadline exists
        if (
            inc["osha_notification_deadline"] is not None
            and inc["osha_notified_at"] is None
        ):
            raise ApiError(
                "ERR_OSHA_NOTIFICATION_REQUIRED",
                409,
                "OSHA notification is required before a RECORDABLE close",
            )
    # priority 7.4: outcome must agree with computed recordability
    if outcome == "RECORDABLE" and not inc["recordable"]:
        raise ApiError(
            "ERR_INCIDENT_RECORDABLE_MISMATCH",
            422,
            "Outcome RECORDABLE conflicts with computed recordability",
        )
    if outcome == "NOT_RECORDABLE" and inc["recordable"]:
        raise ApiError(
            "ERR_INCIDENT_RECORDABLE_MISMATCH",
            422,
            "Outcome NOT_RECORDABLE conflicts with computed recordability",
        )
    # priority 8: segregation of duties
    if uid == inc["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "Closer must differ from the incident creator",
        )
    inc["status"] = (
        "CLOSED_RECORDABLE" if outcome == "RECORDABLE" else "CLOSED_NOT_RECORDABLE"
    )
    touch(inc)
    report = get_report(inc["report_id"])
    apply_hold_cascade(report)
    bump_report(report)
    return success(ser_incident(inc), 200)
