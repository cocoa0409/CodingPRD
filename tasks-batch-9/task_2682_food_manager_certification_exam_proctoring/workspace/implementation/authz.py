"""Authentication, role membership and ownership-scope enforcement.

PRD 2.10 priority order: 1 headers -> 2 role membership -> 3 ownership scope.
Path identifiers must physically resolve before a scope comparison can be made,
so path resolution (priority 6) runs between steps 2 and 3 for path resources;
body foreign keys naming a provider directly are compared before resolution.
"""
from flask import g, request

from errors import ApiError
from store import store

PLATFORM_ADMIN = "PlatformAdmin"
PROVIDER_ADMIN = "ProviderAdmin"
PROCTOR = "Proctor"
CANDIDATE = "Candidate"
HEALTH_OFFICER = "HealthOfficer"

ROLES = [PLATFORM_ADMIN, PROVIDER_ADMIN, PROCTOR, CANDIDATE, HEALTH_OFFICER]

NOT_FOUND = {
    "jurisdiction": "ERR_JURISDICTION_NOT_FOUND",
    "provider": "ERR_TRAINING_PROVIDER_NOT_FOUND",
    "exam_form": "ERR_EXAM_FORM_NOT_FOUND",
    "testing_site": "ERR_TESTING_SITE_NOT_FOUND",
    "candidate": "ERR_CANDIDATE_NOT_FOUND",
    "proctor": "ERR_PROCTOR_NOT_FOUND",
    "batch": "ERR_ACCESS_CODE_BATCH_NOT_FOUND",
    "code": "ERR_ACCESS_CODE_NOT_FOUND",
    "accommodation": "ERR_ACCOMMODATION_REQUEST_NOT_FOUND",
    "session": "ERR_EXAM_SESSION_NOT_FOUND",
    "score_report": "ERR_SCORE_REPORT_NOT_FOUND",
    "incident": "ERR_SECURITY_INCIDENT_NOT_FOUND",
    "certificate": "ERR_CERTIFICATE_NOT_FOUND",
    "registration": "ERR_LOCAL_REGISTRATION_NOT_FOUND",
}

COLLECTIONS = {
    "jurisdiction": "jurisdictions",
    "provider": "providers",
    "exam_form": "exam_forms",
    "testing_site": "testing_sites",
    "candidate": "candidates",
    "proctor": "proctors",
    "batch": "batches",
    "code": "codes",
    "accommodation": "accommodations",
    "session": "sessions",
    "score_report": "score_reports",
    "incident": "incidents",
    "certificate": "certificates",
    "registration": "registrations",
}


def require(*allowed):
    """Priority 1 then 2. Returns (user_id, role) and stashes them on g."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a known role")
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED",
                       "role %s may not call this endpoint" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def deny_scope(detail="resource is outside the caller's ownership scope"):
    raise ApiError("ERR_FORBIDDEN_RESOURCE_SCOPE", detail)


def find(kind, identifier):
    """Priority 6/7 resolution with the entity-specific not-found error."""
    if identifier is None:
        raise ApiError(NOT_FOUND[kind], "%s could not be found" % kind)
    row = getattr(store, COLLECTIONS[kind]).get(identifier)
    if row is None:
        raise ApiError(NOT_FOUND[kind], "%s could not be found" % kind)
    return row


def maybe(kind, identifier):
    if identifier is None:
        return None
    return getattr(store, COLLECTIONS[kind]).get(identifier)


# --- ownership chain resolution -------------------------------------------

def provider_of_candidate(candidate):
    return candidate["training_provider_id"]


def provider_of_batch(batch):
    return batch["training_provider_id"]


def provider_of_code(code):
    batch = store.batches.get(code["batch_id"])
    return batch["training_provider_id"] if batch else None


def candidate_of_code(code):
    return code["candidate_id"]


def provider_of_session(session):
    candidate = store.candidates.get(session["candidate_id"])
    return candidate["training_provider_id"] if candidate else None


def provider_of_accommodation(accommodation):
    candidate = store.candidates.get(accommodation["candidate_id"])
    return candidate["training_provider_id"] if candidate else None


def session_of_report(report):
    return store.sessions.get(report["exam_session_id"])


def provider_of_report(report):
    session = session_of_report(report)
    return provider_of_session(session) if session else None


def candidate_of_report(report):
    session = session_of_report(report)
    return session["candidate_id"] if session else None


def provider_of_certificate(certificate):
    candidate = store.candidates.get(certificate["candidate_id"])
    return candidate["training_provider_id"] if candidate else None


def provider_of_registration(registration):
    certificate = store.certificates.get(registration["certificate_id"])
    return provider_of_certificate(certificate) if certificate else None


def candidate_of_registration(registration):
    certificate = store.certificates.get(registration["certificate_id"])
    return certificate["candidate_id"] if certificate else None


def provider_of_incident(incident):
    session = store.sessions.get(incident["exam_session_id"])
    return provider_of_session(session) if session else None
