"""The dispatch pipeline and its frozen verification findings."""

from flask import Blueprint

import engine
import rt
from core import (F, authenticate, check_owner, created, listing, ok, q,
                  q_instant, validate)
from errors import ApiError
from store import base_row, now, store, touch

bp = Blueprint("dispatch", __name__)

SUPERVISOR = ["PoliceDispatchSupervisor"]
READ_ROLES = ["ProgramAdministrator", "PoliceDispatchSupervisor",
              "FalseAlarmReviewOfficer", "PermitClerk", "HearingOfficer",
              "AlarmCompanyOperator", "AlarmUser"]

ALARM_TYPES = ("BURGLARY", "HOLDUP", "PANIC", "DURESS")
METHODS = ("NONE", "SINGLE_CALL", "TWO_CALL_ECV", "AUDIO_VIDEO", "GUARD_RESPONSE")
OUTCOMES = ("NO_ANSWER", "VOICEMAIL", "ANSWERED_UNVERIFIED", "ANSWERED_CANCELLED")
REFUSAL_REASONS = ("ECV_DEFICIENT", "RESPONSE_SUSPENDED",
                   "VERIFIED_RESPONSE_MISSING", "DUPLICATE_SIGNAL")
LIVE_COMPANY_STATUSES = ("ACTIVE", "PROBATION")
ECV_MINIMUM = 2

CREATE_FIELDS = [
    F("alarm_system_id", "uuid"),
    F("alarm_type", "enum", values=ALARM_TYPES),
    F("verification_method", "enum", values=METHODS),
    F("call_attempts", "array"),
    F("audio_video_evidence", "bool", required=False),
    F("guard_on_scene", "bool", required=False),
    F("occurred_at", "ts"),
    F("idempotency_key", "string", required=False),
]

REFUSE_FIELDS = [F("refusal_reason", "enum", values=REFUSAL_REASONS)]
CANCEL_FIELDS = [F("cancellation_reason", "string", required=False)]
CLOSE_FIELDS = [F("closing_notes", "string", required=False)]


def _distinct_ecv_contacts(system, attempts):
    """Eligible attempts only: live, callable, same premises, declared outcome."""
    seen = []
    for entry in attempts:
        if not isinstance(entry, dict):
            continue
        contact_id = entry.get("site_contact_id")
        if contact_id is None:
            continue
        contact = rt.resolve("SiteContact", contact_id)
        if contact.get("status") != "ACTIVE":
            continue
        if not contact.get("is_ecv_callable"):
            continue
        if contact.get("alarm_site_id") != system.get("alarm_site_id"):
            continue
        if entry.get("outcome") not in OUTCOMES:
            continue
        if contact_id not in seen:
            seen.append(contact_id)
    return len(seen)


def _ecv_sufficient(alarm_type, method, distinct_count, audio_video, guard):
    if alarm_type == "DURESS":
        return True
    if method == "TWO_CALL_ECV" and distinct_count >= ECV_MINIMUM:
        return True
    if method == "AUDIO_VIDEO" and audio_video:
        return True
    if method == "GUARD_RESPONSE" and guard:
        return True
    return False


def _posture_suspended(site):
    if site is None:
        return False
    engine.rollup_site(site, bump=False)
    return site.get("response_status") == "RESPONSE_SUSPENDED"


@bp.post("/dispatch-requests")
def create_request():
    ctx = authenticate(["AlarmCompanyOperator"])
    data = validate(ctx.body, CREATE_FIELDS)
    system = rt.resolve("AlarmSystem", data["alarm_system_id"])
    distinct_count = _distinct_ecv_contacts(system, data["call_attempts"])
    # Position 8 (identity) precedes position 22 (referential coherence): an
    # entity-backed caller reaching outside its own aggregate learns that first.
    check_owner(ctx, company_id=system.get("monitoring_company_id"))
    if system.get("monitoring_company_id") != ctx.user_id:
        raise ApiError("ERR_COMPANY_NOT_SYSTEM_MONITOR",
                       "The acting company does not monitor this system.")
    if system.get("status") in ("REJECTED", "DECOMMISSIONED"):
        raise ApiError("ERR_INVALID_STATE",
                       "A %s system may not request dispatch."
                       % system.get("status"))
    for req in engine.system_requests(system["id"]):
        if req.get("status") in engine.OPEN_REQUEST_STATUSES:
            raise ApiError("ERR_OPEN_DISPATCH_REQUEST_EXISTS",
                           "This system already has an open dispatch request.")
    company = store.alarm_companies.get(system.get("monitoring_company_id"))
    if company is None or company.get("status") not in LIVE_COMPANY_STATUSES:
        raise ApiError("ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED",
                       "This company may not lodge dispatch requests.")
    site = store.alarm_sites.get(system.get("alarm_site_id"))
    if _posture_suspended(site):
        raise ApiError("ERR_POLICE_RESPONSE_SUSPENDED",
                       "Police response is withdrawn from this premises.")
    if site is not None and len(engine.live_callable_contacts(site["id"])) \
            < ECV_MINIMUM:
        raise ApiError("ERR_INSUFFICIENT_ECV_CONTACTS",
                       "The premises cannot be called back for verification.")
    key = data.get("idempotency_key")
    if key is not None:
        for req in store.dispatch_requests.values():
            if req.get("monitoring_company_id") == company["id"] \
                    and req.get("idempotency_key") == key:
                raise ApiError("ERR_INVALID_FIELD_VALUE",
                               "idempotency_key has already been used.")

    audio_video = data.get("audio_video_evidence", False)
    guard = data.get("guard_on_scene", False)
    row = base_row()
    row["alarm_system_id"] = system["id"]
    row["alarm_site_id"] = system.get("alarm_site_id")
    row["monitoring_company_id"] = company["id"]
    row["alarm_type"] = data["alarm_type"]
    row["verification_method"] = data["verification_method"]
    row["call_attempts"] = data["call_attempts"]
    row["distinct_ecv_contact_count"] = distinct_count
    row["audio_video_evidence"] = audio_video
    row["guard_on_scene"] = guard
    row["occurred_at"] = data["occurred_at"]
    row["status"] = "SUBMITTED"
    row["ecv_sufficient"] = _ecv_sufficient(
        data["alarm_type"], data["verification_method"], distinct_count,
        audio_video, guard)
    row["system_permitted_at_occurrence"] = system.get("status") == "PERMITTED"
    row["refusal_reason"] = None
    row["validated_at"] = None
    row["validated_by_user_id"] = None
    row["dispatched_at"] = None
    row["idempotency_key"] = key
    store.dispatch_requests[row["id"]] = row
    engine.rollup_company(company)
    return created(row)


@bp.post("/dispatch-requests/<request_id>/validate")
def validate_request(request_id):
    ctx = authenticate(SUPERVISOR)
    req = rt.resolve("DispatchRequest", request_id)
    if req.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED request may be validated.")
    company = store.alarm_companies.get(req.get("monitoring_company_id"))
    if company is None or company.get("status") not in LIVE_COMPANY_STATUSES:
        raise ApiError("ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED",
                       "This company's dispatch privilege is withdrawn.")
    site = store.alarm_sites.get(req.get("alarm_site_id"))
    if _posture_suspended(site):
        raise ApiError("ERR_POLICE_RESPONSE_SUSPENDED",
                       "Police response is withdrawn from this premises.")
    if not req.get("ecv_sufficient"):
        raise ApiError("ERR_ECV_REQUIREMENT_NOT_MET",
                       "The frozen verification findings are insufficient.")
    system = store.alarm_systems.get(req.get("alarm_system_id")) or {}
    mode = system.get("verified_response_mode")
    if mode == "AUDIO_VIDEO_REQUIRED" and not req.get("audio_video_evidence"):
        raise ApiError("ERR_VERIFIED_RESPONSE_NOT_CONFIRMED",
                       "Recorded audio or video evidence is required.")
    if mode == "GUARD_REQUIRED" and not req.get("guard_on_scene"):
        raise ApiError("ERR_VERIFIED_RESPONSE_NOT_CONFIRMED",
                       "A guard on scene is required.")
    req["status"] = "VALIDATED"
    req["validated_at"] = now()
    req["validated_by_user_id"] = ctx.user_id
    touch(req)
    return ok(req)


@bp.post("/dispatch-requests/<request_id>/refuse")
def refuse_request(request_id):
    ctx = authenticate(SUPERVISOR)
    data = validate(ctx.body, REFUSE_FIELDS)
    req = rt.resolve("DispatchRequest", request_id)
    if req.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED request may be refused.")
    req["status"] = "REFUSED"
    req["refusal_reason"] = data["refusal_reason"]
    touch(req)
    return ok(req)


@bp.post("/dispatch-requests/<request_id>/record-dispatch")
def record_dispatch(request_id):
    authenticate(SUPERVISOR)
    req = rt.resolve("DispatchRequest", request_id)
    if req.get("status") != "VALIDATED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a VALIDATED request may be dispatched.")
    site = store.alarm_sites.get(req.get("alarm_site_id"))
    if _posture_suspended(site):
        raise ApiError("ERR_POLICE_RESPONSE_SUSPENDED",
                       "A suspension served since validation stops the patrol.")
    req["status"] = "DISPATCHED"
    req["dispatched_at"] = now()
    touch(req)
    return ok(req)


@bp.post("/dispatch-requests/<request_id>/cancel")
def cancel_request(request_id):
    ctx = authenticate(["AlarmCompanyOperator", "PoliceDispatchSupervisor"])
    validate(ctx.body, CANCEL_FIELDS)
    req = rt.resolve("DispatchRequest", request_id)
    check_owner(ctx, company_id=req.get("monitoring_company_id"))
    if req.get("status") != "VALIDATED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a VALIDATED request may be cancelled.")
    req["status"] = "CANCELLED"
    touch(req)
    return ok(req)


@bp.post("/dispatch-requests/<request_id>/close-valid")
def close_valid(request_id):
    ctx = authenticate(SUPERVISOR)
    validate(ctx.body, CLOSE_FIELDS)
    req = rt.resolve("DispatchRequest", request_id)
    if req.get("status") != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DISPATCHED request may be closed as valid.")
    if engine.incident_for_request(req["id"]) is not None:
        raise ApiError("ERR_INCIDENT_ALREADY_REPORTED",
                       "An incident already references this request.")
    req["status"] = "CLOSED_VALID"
    touch(req)
    return ok(req)


@bp.get("/dispatch-requests/<request_id>")
def get_request(request_id):
    ctx = authenticate(READ_ROLES)
    req = rt.resolve("DispatchRequest", request_id)
    check_owner(ctx, site_id=req.get("alarm_site_id"),
                company_id=req.get("monitoring_company_id"))
    return ok(req)


@bp.get("/dispatch-requests")
def list_requests():
    ctx = authenticate(READ_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("DispatchRequest"))
    for field in ("alarm_system_id", "alarm_site_id", "monitoring_company_id",
                  "status"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    occurred_from = q_instant("occurred_from")
    occurred_to = q_instant("occurred_to")
    if occurred_from is not None:
        rows = [r for r in rows if r.get("occurred_at") is not None
                and r["occurred_at"] >= occurred_from]
    if occurred_to is not None:
        rows = [r for r in rows if r.get("occurred_at") is not None
                and r["occurred_at"] <= occurred_to]
    return listing(rows, rt.fields("DispatchRequest"))
