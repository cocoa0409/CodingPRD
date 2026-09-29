"""Exam-security incidents, the invalidation cascade and the compliance run."""
from datetime import timedelta

from flask import Blueprint

import authz
import calc
import cascade
import validation as V
from authz import require, find, deny_scope
from envelope import ok
from errors import ApiError
from helpers import paged, scoped_filter, match
from store import store

incidents_bp = Blueprint("incidents", __name__)


def _incident_scope(incident, user_id, role):
    if role == authz.PROVIDER_ADMIN \
            and authz.provider_of_incident(incident) != user_id:
        deny_scope()
    if role == authz.PROCTOR:
        session = store.sessions.get(incident["exam_session_id"])
        owns = incident["reported_by_proctor_id"] == user_id
        assigned = session is not None and session["proctor_id"] == user_id
        if not owns and not assigned:
            deny_scope()


@incidents_bp.post("/security-incidents")
def report_incident():
    user_id, role = require(authz.PROCTOR)
    body = V.get_body()
    session_id = V.req_id(body, "exam_session_id")
    reporter_id = V.req_id(body, "reported_by_proctor_id")
    category = V.req_enum(body, "category", V.INCIDENT_CATEGORIES)
    severity = V.req_enum(body, "severity", V.INCIDENT_SEVERITIES)
    narrative = V.req_str(body, "narrative", 10, 2000)
    if reporter_id != user_id:
        deny_scope("a proctor may only file under its own identity")
    session = find("session", session_id)
    find("proctor", reporter_id)
    if session["session_status"] not in ("SUBMITTED", "CLOSED"):
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "only a SUBMITTED or CLOSED sitting may be reported")
    deadline = session["submitted_at"] \
        + timedelta(hours=calc.INCIDENT_WINDOW_HOURS)
    if store.clock > deadline:
        raise ApiError("ERR_INCIDENT_WINDOW_CLOSED",
                       "the incident filing window has closed")
    row = store.base()
    row.update({
        "exam_session_id": session_id,
        "reported_by_proctor_id": reporter_id,
        "category": category,
        "severity": severity,
        "narrative": narrative,
        "severity_weight": V.SEVERITY_WEIGHT[severity],
        "status": "OPEN",
        "resolved_by_user_id": None,
        "resolution_note": None,
    })
    store.incidents[row["id"]] = row
    return ok(row, 201)


@incidents_bp.get("/security-incidents/<incident_id>")
def read_incident(incident_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.PROCTOR)
    incident = find("incident", incident_id)
    _incident_scope(incident, user_id, role)
    return ok(incident)


@incidents_bp.get("/security-incidents")
def list_incidents():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.PROCTOR)
    session_filter = V.query_id("exam_session_id")
    reporter_filter = V.query_id("reported_by_proctor_id")
    status = V.query_enum("status", V.INCIDENT_STATUS)
    if role == authz.PROCTOR:
        reporter_filter = scoped_filter(reporter_filter, user_id)
    rows = [r for r in store.incidents.values()
            if match(r, "exam_session_id", session_filter)
            and match(r, "reported_by_proctor_id", reporter_filter)
            and match(r, "status", status)]
    if role == authz.PROVIDER_ADMIN:
        rows = [r for r in rows if authz.provider_of_incident(r) == user_id]
    return paged(rows)


@incidents_bp.post("/security-incidents/<incident_id>/review-open")
def incident_review_open(incident_id):
    require(authz.PLATFORM_ADMIN)
    incident = find("incident", incident_id)
    V.get_body()
    if incident["status"] != "OPEN":
        raise ApiError("ERR_INCIDENT_STATE_INVALID", "the incident is not OPEN")
    session = store.sessions.get(incident["exam_session_id"])
    if session is None \
            or session["proctoring_status"] not in ("ATTESTED", "CLEARED"):
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "the sitting may not be taken into review")
    if session["proctoring_status"] == "CLEARED":
        deadline = session["submitted_at"] \
            + timedelta(hours=calc.INCIDENT_WINDOW_HOURS)
        if store.clock > deadline:
            raise ApiError("ERR_INCIDENT_WINDOW_CLOSED",
                           "the incident filing window has closed")
    incident["status"] = "UNDER_REVIEW"
    store.touch(incident)
    session["proctoring_status"] = "INCIDENT_UNDER_REVIEW"
    store.touch(session)
    return ok(incident)


@incidents_bp.post("/security-incidents/<incident_id>/resolution")
def incident_resolution(incident_id):
    user_id, role = require(authz.PLATFORM_ADMIN)
    incident = find("incident", incident_id)
    body = V.get_body()
    outcome = V.req_enum(body, "outcome", ["SUBSTANTIATE", "DISMISS"])
    resolution_note = V.opt_str(body, "resolution_note", 1, None, None)
    if incident["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENT_STATE_INVALID",
                       "the incident is not UNDER_REVIEW")
    session = store.sessions.get(incident["exam_session_id"])
    for report in store.score_reports.values():
        if session is not None \
                and report["exam_session_id"] == session["id"] \
                and report["finalized_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the operator who released the score may not "
                           "adjudicate this incident")
    if session is not None and session["accommodation_request_id"]:
        accommodation = store.accommodations.get(
            session["accommodation_request_id"])
        if accommodation is not None \
                and accommodation["reviewed_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the operator who reviewed the accommodation may "
                           "not adjudicate this incident")
    if outcome == "SUBSTANTIATE":
        cascade.substantiate(incident, session, user_id, resolution_note)
    else:
        cascade.dismiss(incident, session, user_id, resolution_note)
    return ok(incident)


# --- the compliance run ----------------------------------------------------

MID_EXAM_STATUSES = ("CHECKED_IN", "IN_PROGRESS")


def _sessions_holding(code_id):
    return store.ordered([s for s in store.sessions.values()
                          if s["access_code_id"] == code_id])


def _expire_inventory(run_epoch):
    expired_batches = 0
    for batch in store.ordered(list(store.batches.values())):
        if batch["status"] not in ("ACTIVE", "DEPLETED"):
            continue
        if not (batch["expires_at"] < run_epoch):
            continue
        for code in store.ordered(cascade.batch_codes(batch["id"])):
            if code["status"] == "AVAILABLE":
                code["status"] = "EXPIRED"
                store.touch(code)
                continue
            if code["status"] != "ASSIGNED":
                continue
            holders = _sessions_holding(code["id"])
            if any(s["session_status"] in MID_EXAM_STATUSES for s in holders):
                continue
            code["status"] = "EXPIRED"
            store.touch(code)
            for session in holders:
                if session["session_status"] != "SCHEDULED":
                    continue
                cascade.release_interval(session, session["allowed_minutes"])
                session["session_status"] = "CANCELLED"
                store.touch(session)
        cascade.recount_batch(batch)
        batch["status"] = "EXPIRED"
        store.touch(batch)
        expired_batches += 1
    return expired_batches


def _expire_certificates(run_epoch):
    expired = 0
    for certificate in store.ordered(list(store.certificates.values())):
        if certificate["status"] != "ISSUED":
            continue
        if certificate["expires_at"] > run_epoch:
            continue
        certificate["status"] = "EXPIRED"
        store.touch(certificate)
        candidate = store.candidates.get(certificate["candidate_id"])
        if candidate is not None:
            cascade.set_compliance(candidate, "LAPSED")
        cascade.withdraw_registrations(certificate)
        expired += 1
    return expired


def _mark_delinquent(run_epoch):
    delinquent = 0
    for registration in store.ordered(list(store.registrations.values())):
        if registration["status"] != "FILED":
            continue
        if registration["posted_at"] is not None:
            continue
        if not (registration["posting_deadline_at"] < run_epoch):
            continue
        registration["status"] = "DELINQUENT"
        store.touch(registration)
        delinquent += 1
    return delinquent


def _due_tier(certificate, run_epoch):
    expires_at = certificate["expires_at"]
    if run_epoch >= expires_at:
        return "T_LAPSED"
    if run_epoch >= expires_at - timedelta(days=30):
        return "T_30"
    if run_epoch >= expires_at - timedelta(days=90):
        return "T_90"
    if run_epoch >= certificate["recert_window_opens_at"]:
        return "T_180"
    return None


def _dispatch_reminders(run_epoch):
    notified = []
    candidates = [c for c in store.certificates.values()
                  if c["status"] in ("ISSUED", "EXPIRED")
                  and c["recert_authorized_at"] is None
                  and c["superseded_by_certificate_id"] is None]
    candidates.sort(key=lambda c: (c["expires_at"], c["created_at"], c["_seq"]))
    for certificate in candidates:
        tier = _due_tier(certificate, run_epoch)
        if tier is None or tier in certificate["reminder_tiers_sent"]:
            continue
        certificate["reminder_tiers_sent"].append(tier)
        store.touch(certificate)
        notified.append(certificate["id"])
    return notified


@incidents_bp.post("/compliance-runs")
def compliance_run():
    require(authz.PLATFORM_ADMIN)
    V.get_body()
    run_epoch = store.clock
    batches_expired_count = _expire_inventory(run_epoch)
    certificates_expired_count = _expire_certificates(run_epoch)
    registrations_delinquent_count = _mark_delinquent(run_epoch)
    notified_certificate_ids = _dispatch_reminders(run_epoch)
    return ok({
        "run_epoch": run_epoch,
        "certificates_expired_count": certificates_expired_count,
        "registrations_delinquent_count": registrations_delinquent_count,
        "batches_expired_count": batches_expired_count,
        "reminder_notices_sent_count": len(notified_certificate_ids),
        "notified_certificate_ids": notified_certificate_ids,
    }, 201)
