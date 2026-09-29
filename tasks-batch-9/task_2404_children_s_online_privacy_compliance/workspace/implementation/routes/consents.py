"""ConsentRequest endpoints (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, g

import calculations as calc
from constants import (
    CONSENT_METHODS,
    CONSENT_STATUSES,
    CONSENT_VERIFICATION_WINDOW_DAYS,
    INTENDED_USES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PARENT,
    ROLE_PRIVACY_ENGINEER,
    ROLE_SAFE_HARBOR_ASSESSOR,
)
from db import db, now, ordered, touch
from errors import fail
from helpers import (
    apply_filters,
    base_row,
    bump_service,
    check_service_version,
    disclosure_loss_cascade,
    resolve,
    resolve_body_fk,
    supersede_consent,
)
from middleware import authenticate, body, opt_string, req_enum, req_enum_list, req_string
from response import created, ok, paginate
from serializers import consent_out

bp = Blueprint("consents", __name__)

NON_TERMINAL_ON_CREATE = ("INITIATED", "NOTICE_DELIVERED", "PENDING_VERIFICATION")


@bp.post("/consent-requests")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def create_consent():
    data = body()
    service = resolve_body_fk("service", data, "service_id")
    notice = resolve_body_fk("notice", data, "notice_id")

    # Cross-parent coherence (PRD §2.8 / precedence step 6).
    if notice["service_id"] != service["id"]:
        fail("ERR_SERVICE_SCOPE_MISMATCH")

    check_service_version(data, service)

    parent_email = req_string(data, "parent_email")
    child_pseudonym = req_string(data, "child_pseudonym")
    intended_uses = req_enum_list(data, "intended_uses", INTENDED_USES, non_empty=True)
    consent_method = req_enum(data, "consent_method", CONSENT_METHODS)

    if calc.compliance_posture(service) == "FROZEN":
        fail("ERR_POSTURE_FROZEN")

    consent = base_row()
    consent.update(
        {
            "service_id": service["id"],
            "notice_id": notice["id"],
            "parent_email": parent_email,
            "child_pseudonym": child_pseudonym,
            "intended_uses": intended_uses,
            "consent_method": consent_method,
            "method_assurance_tier": calc.method_assurance_tier(consent_method),
            "required_tier_at_creation": calc.required_consent_tier(
                service["id"], intended_uses
            ),
            "status": "INITIATED",
            "notice_delivered_at": None,
            "verification_deadline_at": None,
            "secondary_confirmation_received": False,
            "verification_evidence_code": None,
            "granted_at": None,
            "revoked_at": None,
            "revocation_reason": None,
            "denial_reason": None,
        }
    )

    # A newer request supersedes the parent's earlier in-flight request.
    for other in db.consent_requests.values():
        if (
            other["service_id"] == service["id"]
            and other["parent_email"] == parent_email
            and other["child_pseudonym"] == child_pseudonym
            and other["status"] in NON_TERMINAL_ON_CREATE
        ):
            supersede_consent(other)

    db.consent_requests[consent["id"]] = consent
    bump_service(service)
    return created(consent_out(consent))


@bp.get("/consent-requests")
@authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PRIVACY_ENGINEER, ROLE_SAFE_HARBOR_ASSESSOR)
def list_consents():
    rows = ordered(list(db.consent_requests.values()))
    rows = apply_filters(
        rows,
        {
            "service_id": "service_id",
            "notice_id": "notice_id",
            "parent_email": "parent_email",
            "child_pseudonym": "child_pseudonym",
            "status": "status",
        },
    )
    return paginate(rows, consent_out)


@bp.get("/consent-requests/<consent_id>")
@authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PRIVACY_ENGINEER, ROLE_PARENT)
def get_consent(consent_id):
    # Parent ownership (precedence step 3) precedes path resolution (step 4).
    if g.role == ROLE_PARENT and consent_id != g.user_id:
        fail("ERR_NOT_CONSENT_HOLDER")
    consent = resolve("consent", consent_id)
    return ok(consent_out(consent))


@bp.post("/consent-requests/<consent_id>/status")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def set_consent_status(consent_id):
    consent = resolve("consent", consent_id)
    data = body()
    to_status = req_enum(data, "to_status", CONSENT_STATUSES)

    secondary_code = opt_string(data, "secondary_confirmation_code")
    evidence_code = None
    if to_status == "GRANTED":
        evidence_code = req_string(data, "verification_evidence_code")

    current = consent["status"]
    transition = (current, to_status)
    service = db.online_services[consent["service_id"]]

    if transition == ("INITIATED", "NOTICE_DELIVERED"):
        notice = db.parental_notices.get(consent["notice_id"])
        if notice is None or notice["status"] != "PUBLISHED":
            fail("ERR_NOTICE_NOT_PUBLISHED")
        if (
            consent["consent_method"] == "SCHOOL_AUTHORIZATION"
            and notice["delivery_channel"] != "SCHOOL_INTERMEDIARY"
        ):
            fail("ERR_NOTICE_CHANNEL_INCOMPATIBLE")
        consent["notice_delivered_at"] = now()
        consent["verification_deadline_at"] = consent["notice_delivered_at"] + timedelta(
            days=CONSENT_VERIFICATION_WINDOW_DAYS
        )
        consent["status"] = to_status
        touch(consent)
        return ok(consent_out(consent))

    if transition == ("NOTICE_DELIVERED", "PENDING_VERIFICATION"):
        if now() >= consent["verification_deadline_at"]:
            fail("ERR_CONSENT_WINDOW_EXPIRED")
        consent["status"] = to_status
        touch(consent)
        return ok(consent_out(consent))

    if transition == ("PENDING_VERIFICATION", "GRANTED"):
        # Consent-quality clauses (precedence step 13) precede the verification
        # window (step 17).
        if consent["method_assurance_tier"] < consent["required_tier_at_creation"]:
            fail("ERR_CONSENT_METHOD_TIER_INSUFFICIENT")
        if consent["consent_method"] == "EMAIL_PLUS" and secondary_code is None:
            fail("ERR_EMAIL_PLUS_CONFIRMATION_MISSING")
        if now() >= consent["verification_deadline_at"]:
            fail("ERR_CONSENT_WINDOW_EXPIRED")

        consent["status"] = "GRANTED"
        consent["granted_at"] = now()
        consent["verification_evidence_code"] = evidence_code
        if secondary_code is not None:
            consent["secondary_confirmation_received"] = True
        touch(consent)

        for other in db.consent_requests.values():
            if (
                other["id"] != consent["id"]
                and other["service_id"] == consent["service_id"]
                and other["parent_email"] == consent["parent_email"]
                and other["child_pseudonym"] == consent["child_pseudonym"]
                and other["status"] == "GRANTED"
            ):
                supersede_consent(other)

        bump_service(service)
        return ok(consent_out(consent))

    if transition == ("PENDING_VERIFICATION", "DENIED"):
        consent["status"] = "DENIED"
        consent["denial_reason"] = opt_string(data, "denial_reason")
        touch(consent)
        return ok(consent_out(consent))

    if transition == ("GRANTED", "REVOKED"):
        consent["status"] = "REVOKED"
        consent["revoked_at"] = now()
        consent["revocation_reason"] = "PARENT_REFUSAL"
        touch(consent)
        disclosure_loss_cascade(service)
        bump_service(service)
        return ok(consent_out(consent))

    fail("ERR_INVALID_STATE")
