"""Routes: AgentAppointment and OfficerAppointment."""
from datetime import timedelta

from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_INVALID_REQUEST, ERR_ENTITY_NOT_FOUND, ERR_AGENT_NOT_FOUND,
    ERR_JURISDICTION_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND,
    ERR_ENTITY_ALREADY_DISSOLVED, ERR_AGENT_APPOINTMENT_OVERLAP,
    ERR_AGENT_COVERAGE_GAP, ERR_AGENT_APPOINTMENT_NOT_ACTIVE,
    ERR_AGENT_APPOINTMENT_NOT_NOTICE_PENDING, ERR_AGENT_RESIGNATION_NOTICE_UNRIPE,
    ERR_FORBIDDEN_ACTOR, ERR_APPOINTMENT_NOT_APPOINTED,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records
from routes_entities import get_entity_or_404

bp = Blueprint("appointments", __name__)

CS = ["CorporateSecretary"]


# ---------------------------------------------------------------------------
# Agent appointments
# ---------------------------------------------------------------------------
@bp.route("/api/entities/<entityId>/agent-appointments", methods=["POST"])
def create_agent_appointment(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    body = get_body()
    # Priority 3: body FK existence
    agent_id = body.get("agent_id")
    if agent_id is not None and agent_id not in store.registered_agents:
        raise_err(ERR_AGENT_NOT_FOUND)
    jurisdiction_id = body.get("jurisdiction_id")
    if jurisdiction_id is not None and jurisdiction_id not in store.jurisdictions:
        raise_err(ERR_JURISDICTION_NOT_FOUND)
    # Priority 4: schema
    if agent_id is None:
        raise_err(ERR_INVALID_REQUEST, "agent_id is required")
    if jurisdiction_id is None:
        raise_err(ERR_INVALID_REQUEST, "jurisdiction_id is required")
    start_date = body.get("start_date")
    if not svc.is_valid_date(start_date):
        raise_err(ERR_INVALID_REQUEST, "start_date must be an ISO date")
    agent = store.registered_agents[agent_id]
    if agent["jurisdiction_id"] != jurisdiction_id:
        raise_err(ERR_INVALID_REQUEST,
                  "Registered agent is not authorized in this jurisdiction")
    # Priority 5: parent entity not DISSOLVED
    if entity["status"] == "DISSOLVED":
        raise_err(ERR_ENTITY_ALREADY_DISSOLVED)
    svc.lazy_eval_entity(entity)
    incumbents = [a for a in svc.agent_appts_of(entity["id"])
                  if a["jurisdiction_id"] == jurisdiction_id]
    # Priority 8: overlap with an ACTIVE incumbent
    if any(a["status"] == "ACTIVE" for a in incumbents):
        raise_err(ERR_AGENT_APPOINTMENT_OVERLAP,
                  "An ACTIVE appointment already covers this entity and jurisdiction")
    # Priority 9: coverage continuity vs NOTICE_PENDING incumbents
    for a in incumbents:
        if a["status"] == "NOTICE_PENDING":
            if svc.parse_date(start_date) > svc.parse_date(a["effective_end_date"]):
                raise_err(ERR_AGENT_COVERAGE_GAP,
                          "Successor start_date is after the incumbent's effective_end_date")
    rec = store.new_record()
    rec.update({
        "entity_id": entity["id"],
        "agent_id": agent_id,
        "jurisdiction_id": jurisdiction_id,
        "start_date": start_date,
        "notice_date": None,
        "effective_end_date": None,
        "status": "ACTIVE",
    })
    store.agent_appointments[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/agent-appointments", methods=["GET"])
def list_agent_appointments():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.agent_appointments.values()))
    for param, field in (("entity_id", "entity_id"), ("agent_id", "agent_id"),
                         ("jurisdiction_id", "jurisdiction_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate([svc.serialize(r) for r in records], request.args)


def get_agent_appt_or_404(appointmentId):
    rec = store.agent_appointments.get(appointmentId)
    if rec is None:
        raise_err(ERR_APPOINTMENT_NOT_FOUND)
    return rec


@bp.route("/api/agent-appointments/<appointmentId>", methods=["GET"])
def get_agent_appointment(appointmentId):
    require_roles(ALL_ROLES)
    return ok_object(svc.serialize(get_agent_appt_or_404(appointmentId)))


@bp.route("/api/agent-appointments/<appointmentId>/file-resignation-notice", methods=["POST"])
def file_resignation_notice(appointmentId):
    user_id, _ = require_roles(["RegisteredAgentUser"])
    rec = get_agent_appt_or_404(appointmentId)
    get_body()
    if rec["status"] != "ACTIVE":
        raise_err(ERR_AGENT_APPOINTMENT_NOT_ACTIVE,
                  "file-resignation-notice requires status == ACTIVE")
    if user_id != rec["agent_id"]:
        raise_err(ERR_FORBIDDEN_ACTOR, "X-User-ID must equal the appointment's agent_id")
    today = store.today()
    jurisdiction = store.jurisdictions[rec["jurisdiction_id"]]
    rec["status"] = "NOTICE_PENDING"
    rec["notice_date"] = svc.fmt_date(today)
    rec["effective_end_date"] = svc.fmt_date(
        today + timedelta(days=jurisdiction["ra_resignation_notice_days"]))
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/agent-appointments/<appointmentId>/finalize-resignation", methods=["POST"])
def finalize_resignation(appointmentId):
    require_roles(CS)
    rec = get_agent_appt_or_404(appointmentId)
    get_body()
    entity = store.entities[rec["entity_id"]]
    svc.lazy_eval_entity(entity)
    if rec["status"] != "NOTICE_PENDING":
        raise_err(ERR_AGENT_APPOINTMENT_NOT_NOTICE_PENDING,
                  "finalize-resignation requires status == NOTICE_PENDING")
    if store.today() < svc.parse_date(rec["effective_end_date"]):
        raise_err(ERR_AGENT_RESIGNATION_NOTICE_UNRIPE,
                  "Resignation notice period has not elapsed")
    rec["status"] = "RESIGNED"
    store.touch(rec)
    svc.append_event(entity["id"], "AGENT_RESIGNED", {"appointment_id": rec["id"]})
    # Hop 1: posture recompute (coverage may be lost in this jurisdiction)
    svc.recompute_posture(entity)
    # Hop 2: QUALIFIED qualifications in this jurisdiction -> REVOKED
    for q in svc.quals_of(entity["id"]):
        if q["jurisdiction_id"] == rec["jurisdiction_id"] and q["status"] == "QUALIFIED":
            q["status"] = "REVOKED"
            store.touch(q)
            svc.append_event(entity["id"], "QUALIFICATION_REVOKED",
                             {"qualification_id": q["id"]})
            # Hop 3: withdraw that jurisdiction's SCHEDULED/PREPARED filings
            for f in svc.filings_of(entity["id"]):
                if (f["jurisdiction_id"] == rec["jurisdiction_id"]
                        and f["status"] in ("SCHEDULED", "PREPARED")):
                    f["status"] = "WITHDRAWN"
                    store.touch(f)
                    svc.append_event(entity["id"], "FILING_WITHDRAWN",
                                     {"filing_id": f["id"]})
    store.touch(entity)  # increments LegalEntity.version by 1
    return ok_object(svc.serialize(rec))


# ---------------------------------------------------------------------------
# Officer appointments
# ---------------------------------------------------------------------------
@bp.route("/api/officer-appointments", methods=["GET"])
def list_officer_appointments():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.officer_appointments.values()))
    for param, field in (("entity_id", "entity_id"), ("officer_id", "officer_id"),
                         ("resolution_id", "resolution_id"), ("status", "status"),
                         ("office_title", "office_title")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate([svc.serialize(r) for r in records], request.args)


def get_officer_appt_or_404(appointmentId):
    rec = store.officer_appointments.get(appointmentId)
    if rec is None:
        raise_err(ERR_APPOINTMENT_NOT_FOUND)
    return rec


@bp.route("/api/officer-appointments/<appointmentId>", methods=["GET"])
def get_officer_appointment(appointmentId):
    require_roles(ALL_ROLES)
    return ok_object(svc.serialize(get_officer_appt_or_404(appointmentId)))


@bp.route("/api/officer-appointments/<appointmentId>/resign", methods=["POST"])
def resign_officer_appointment(appointmentId):
    user_id, _ = require_roles(["AuthorizedOfficer"])
    rec = get_officer_appt_or_404(appointmentId)
    get_body()
    if rec["status"] != "APPOINTED":
        raise_err(ERR_APPOINTMENT_NOT_APPOINTED, "resign requires status == APPOINTED")
    if user_id != rec["officer_id"]:
        raise_err(ERR_FORBIDDEN_ACTOR, "X-User-ID must equal the appointment's officer_id")
    rec["status"] = "RESIGNED"
    rec["end_date"] = svc.fmt_date(store.today())
    store.touch(rec)
    svc.revoke_officer_grants(rec["entity_id"], rec["officer_id"])
    svc.append_event(rec["entity_id"], "OFFICER_RESIGNED", {"appointment_id": rec["id"]})
    return ok_object(svc.serialize(rec))
