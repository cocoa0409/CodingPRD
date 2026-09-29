"""Candidates, the compliance summary, proctors and the audit cycle."""
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

people_bp = Blueprint("people", __name__)

CERT_PREFERENCE = {"ISSUED": 0, "EXPIRED": 1, "REVOKED": 2}


# --- candidates ------------------------------------------------------------

@people_bp.post("/candidates")
def create_candidate():
    user_id, role = require(authz.PROVIDER_ADMIN)
    body = V.get_body()
    full_name = V.req_str(body, "full_name", 1)
    email = V.req_str(body, "email", 1)
    if "@" not in email:
        raise ApiError("ERR_INVALID_REQUEST", "email must contain @")
    preferred_language = V.req_enum(body, "preferred_language", V.LANGUAGES)
    provider_id = V.req_id(body, "training_provider_id")
    jurisdiction_id = V.req_id(body, "jurisdiction_id")
    if provider_id != user_id:
        deny_scope("a provider may only enrol its own candidates")
    find("provider", provider_id)
    find("jurisdiction", jurisdiction_id)
    for existing in store.candidates.values():
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique")
    row = store.base()
    row.update({
        "full_name": full_name,
        "email": email,
        "preferred_language": preferred_language,
        "training_provider_id": provider_id,
        "jurisdiction_id": jurisdiction_id,
        "security_hold": False,
        "substantiated_incident_count": 0,
        "compliance_status": "NOT_CERTIFIED",
    })
    store.candidates[row["id"]] = row
    return ok(row, 201)


def _candidate_scope(candidate, user_id, role):
    if role == authz.PROVIDER_ADMIN \
            and candidate["training_provider_id"] != user_id:
        deny_scope()
    if role == authz.CANDIDATE and candidate["id"] != user_id:
        deny_scope()
    if role == authz.HEALTH_OFFICER and candidate["jurisdiction_id"] != user_id:
        deny_scope()


@people_bp.get("/candidates/<candidate_id>")
def read_candidate(candidate_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.CANDIDATE)
    candidate = find("candidate", candidate_id)
    _candidate_scope(candidate, user_id, role)
    return ok(candidate)


@people_bp.get("/candidates")
def list_candidates():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    provider_filter = V.query_id("training_provider_id")
    if role == authz.PROVIDER_ADMIN:
        provider_filter = scoped_filter(provider_filter, user_id)
    jurisdiction_id = V.query_id("jurisdiction_id")
    security_hold = V.query_bool("security_hold")
    rows = [r for r in store.candidates.values()
            if match(r, "training_provider_id", provider_filter)
            and match(r, "jurisdiction_id", jurisdiction_id)
            and match(r, "security_hold", security_hold)]
    return paged(rows)


def _active_certificate(candidate_id):
    rows = [c for c in store.certificates.values()
            if c["candidate_id"] == candidate_id
            and c["status"] in CERT_PREFERENCE]
    if not rows:
        return None
    rows.sort(key=lambda c: (CERT_PREFERENCE[c["status"]],
                             -c["_seq"]))
    return rows[0]


@people_bp.get("/candidates/<candidate_id>/compliance-summary")
def candidate_compliance_summary(candidate_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.CANDIDATE, authz.HEALTH_OFFICER)
    candidate = find("candidate", candidate_id)
    _candidate_scope(candidate, user_id, role)
    certificate = _active_certificate(candidate["id"])
    registration_status = None
    if certificate is not None:
        filings = [r for r in store.registrations.values()
                   if r["certificate_id"] == certificate["id"]]
        if filings:
            filings.sort(key=lambda r: -r["_seq"])
            registration_status = filings[0]["status"]
    session_ids = set(s["id"] for s in store.sessions.values()
                      if s["candidate_id"] == candidate["id"])
    open_incidents = 0
    for incident in store.incidents.values():
        if incident["exam_session_id"] in session_ids \
                and incident["status"] in ("OPEN", "UNDER_REVIEW"):
            open_incidents += 1
    return ok({
        "candidate_id": candidate["id"],
        "compliance_status": candidate["compliance_status"],
        "active_certificate_id": certificate["id"] if certificate else None,
        "certificate_expires_at": certificate["expires_at"] if certificate else None,
        "recert_window_opens_at": certificate["recert_window_opens_at"]
        if certificate else None,
        "local_registration_status": registration_status,
        "reminder_tiers_sent": list(certificate["reminder_tiers_sent"])
        if certificate else [],
        "open_incident_count": open_incidents,
    })


# --- proctors --------------------------------------------------------------

@people_bp.post("/proctors")
def create_proctor():
    user_id, role = require(authz.PROVIDER_ADMIN)
    body = V.get_body()
    full_name = V.req_str(body, "full_name", 1)
    email = V.req_str(body, "email", 1)
    if "@" not in email:
        raise ApiError("ERR_INVALID_REQUEST", "email must contain @")
    provider_id = V.req_id(body, "training_provider_id")
    roles_held = V.req_enum_subset(body, "roles_held", V.PROCTOR_ROLES)
    languages = V.req_enum_subset(body, "languages_certified", V.LANGUAGES)
    remote_certified = V.opt_bool(body, "remote_certified", False)
    if provider_id != user_id:
        deny_scope("a provider may only register its own proctors")
    find("provider", provider_id)
    for existing in store.proctors.values():
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique")
    row = store.base()
    row.update({
        "full_name": full_name,
        "email": email,
        "training_provider_id": provider_id,
        "roles_held": roles_held,
        "languages_certified": languages,
        "remote_certified": remote_certified,
        "registration_status": "PENDING",
        "proctored_session_count": 0,
        "substantiated_incident_weight_total": 0,
        "risk_score": V.Decimal("0.00"),
        "risk_variant_applied": "ROLLING_WINDOW",
        "reserved_minutes": 0,
        "suspended_reason": None,
    })
    store.proctors[row["id"]] = row
    return ok(row, 201)


@people_bp.get("/proctors/<proctor_id>")
def read_proctor(proctor_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.PROCTOR)
    proctor = find("proctor", proctor_id)
    if role == authz.PROVIDER_ADMIN \
            and proctor["training_provider_id"] != user_id:
        deny_scope()
    if role == authz.PROCTOR and proctor["id"] != user_id:
        deny_scope()
    return ok(proctor)


@people_bp.get("/proctors")
def list_proctors():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    provider_filter = V.query_id("training_provider_id")
    if role == authz.PROVIDER_ADMIN:
        provider_filter = scoped_filter(provider_filter, user_id)
    status = V.query_enum("registration_status", V.REGISTRATION_STATUS)
    rows = [r for r in store.proctors.values()
            if match(r, "training_provider_id", provider_filter)
            and match(r, "registration_status", status)]
    return paged(rows)


@people_bp.post("/proctors/<proctor_id>/registration-decision")
def proctor_registration_decision(proctor_id):
    require(authz.PLATFORM_ADMIN)
    proctor = find("proctor", proctor_id)
    body = V.get_body()
    decision = V.req_enum(body, "decision", ["APPROVE", "REJECT"])
    V.opt_str(body, "decision_note", 1)
    if proctor["registration_status"] != "PENDING":
        raise ApiError("ERR_PROCTOR_STATE_INVALID",
                       "the registration is not PENDING")
    if decision == "APPROVE":
        proctor["registration_status"] = "REGISTERED"
        proctor["risk_score"] = V.Decimal("0.00")
        proctor["risk_variant_applied"] = "ROLLING_WINDOW"
    else:
        proctor["registration_status"] = "REJECTED"
    store.touch(proctor)
    return ok(proctor)


@people_bp.post("/proctors/<proctor_id>/audit-open")
def proctor_audit_open(proctor_id):
    require(authz.PLATFORM_ADMIN)
    proctor = find("proctor", proctor_id)
    body = V.get_body()
    V.req_str(body, "audit_reason", 1)
    if proctor["registration_status"] != "REGISTERED":
        raise ApiError("ERR_PROCTOR_STATE_INVALID",
                       "the registration is not REGISTERED")
    proctor["registration_status"] = "UNDER_AUDIT"
    proctor["risk_score"] = calc.rolling_window_risk(proctor["id"])
    proctor["risk_variant_applied"] = "ROLLING_WINDOW"
    store.touch(proctor)
    return ok(proctor)


@people_bp.post("/proctors/<proctor_id>/audit-close")
def proctor_audit_close(proctor_id):
    require(authz.PLATFORM_ADMIN)
    proctor = find("proctor", proctor_id)
    body = V.get_body()
    outcome = V.req_enum(body, "outcome", ["PASS", "SUSPEND", "REVOKE"])
    V.opt_str(body, "audit_note", 1)
    if proctor["registration_status"] != "UNDER_AUDIT":
        raise ApiError("ERR_PROCTOR_STATE_INVALID",
                       "the registration is not UNDER_AUDIT")
    proctor["risk_score"] = calc.lifetime_cumulative_risk(proctor)
    proctor["risk_variant_applied"] = "LIFETIME_CUMULATIVE"
    store.touch(proctor)
    if outcome == "PASS":
        if proctor["risk_score"] >= calc.RISK_SUSPENSION_THRESHOLD:
            cascade.suspend_proctor(proctor, "RISK_THRESHOLD_BREACH")
        else:
            proctor["registration_status"] = "REGISTERED"
            store.touch(proctor)
    elif outcome == "SUSPEND":
        cascade.suspend_proctor(proctor, "AUDIT_FAILURE")
    else:
        cascade.revoke_proctor(proctor)
    return ok(proctor)


@people_bp.post("/proctors/<proctor_id>/reinstatement")
def proctor_reinstatement(proctor_id):
    require(authz.PLATFORM_ADMIN)
    proctor = find("proctor", proctor_id)
    body = V.get_body()
    V.req_str(body, "remediation_ref", 1)
    if proctor["registration_status"] != "SUSPENDED":
        raise ApiError("ERR_PROCTOR_STATE_INVALID",
                       "the registration is not SUSPENDED")
    proctor["registration_status"] = "REGISTERED"
    proctor["suspended_reason"] = None
    store.touch(proctor)
    return ok(proctor)
