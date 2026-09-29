"""Enrollment registration, consent, the amendment cycle and withdrawal."""
from flask import Blueprint

import services as svc
from errors import fail
from middleware import endpoint, get_body, v_bool, v_date, v_str, v_ts
from response import object_response
from store import base_row, db, iso, now, public, touch

bp = Blueprint("enroll", __name__)

PROGRAM_TYPES = ("PRIVATE_FAMILY", "PUBLIC_DONATION")
TERMINAL_LIFECYCLE = ("CLOSED", "WITHDRAWN")


@bp.route("/cbb/enrollments", methods=["POST"])
@endpoint("IntakeCoordinator", "PlatformAdmin")
def create_enrollment(user_id, role):
    body = get_body()
    from middleware import v_enum
    program_type = v_enum(body, "program_type", PROGRAM_TYPES)
    name = v_str(body, "primary_parent_name", min_len=1, max_len=120)
    delivery = v_date(body, "expected_delivery_date")
    site = v_str(body, "collection_site_code", min_len=1, max_len=20)
    research = v_bool(body, "research_use_authorized", default=False)
    hla = v_bool(body, "hla_typing_consent", default=False)

    row = base_row()
    row.update({
        "program_type": program_type,
        "primary_parent_name": name,
        "expected_delivery_date": iso(delivery),
        "collection_site_code": site,
        "research_use_authorized": research,
        "hla_typing_consent": hla,
        "lifecycle_status": "CONSENT_PENDING",
        "consent_status": "PENDING",
        "consent_version": 0,
        "consent_amendment_count": 0,
        "consent_signed_at": None,
        "withdrawal_reason_code": None,
    })
    db.enrollments[row["id"]] = row
    return object_response(public(row), 201)


@bp.route("/cbb/enrollments/<eid>/consent", methods=["POST"])
@endpoint("ParentGuardian", "IntakeCoordinator", "PlatformAdmin")
def sign_consent(user_id, role, eid):
    svc.require_pg_enrollment(user_id, role, eid)
    body = get_body()
    v_str(body, "consent_document_hash", min_len=1)
    research = v_bool(body, "research_use_authorized")
    hla = v_bool(body, "hla_typing_consent")
    enrollment = svc.get_enrollment(eid)

    if enrollment["lifecycle_status"] in TERMINAL_LIFECYCLE:
        fail("ERR_INVALID_ENROLLMENT_STATE")
    if enrollment["consent_status"] not in ("PENDING", "AMENDMENT_PENDING"):
        fail("ERR_INVALID_ENROLLMENT_STATE")

    was_amendment = enrollment["consent_status"] == "AMENDMENT_PENDING"
    enrollment["consent_status"] = "CONSENTED"
    enrollment["consent_version"] = enrollment["consent_version"] + 1
    enrollment["consent_signed_at"] = iso(now())
    if research is not None:
        enrollment["research_use_authorized"] = research
    if hla is not None:
        enrollment["hla_typing_consent"] = hla
    if enrollment["lifecycle_status"] == "CONSENT_PENDING":
        enrollment["lifecycle_status"] = "ACTIVE"
    touch(enrollment)
    if was_amendment:
        svc.cascade_reconsent(enrollment)
    return object_response(public(enrollment))


@bp.route("/cbb/enrollments/<eid>/consent-amendment", methods=["POST"])
@endpoint("ParentGuardian", "IntakeCoordinator", "PlatformAdmin")
def open_amendment(user_id, role, eid):
    svc.require_pg_enrollment(user_id, role, eid)
    body = get_body()
    v_str(body, "amendment_reason_code", min_len=1)
    enrollment = svc.get_enrollment(eid)

    if enrollment["lifecycle_status"] in TERMINAL_LIFECYCLE:
        fail("ERR_INVALID_ENROLLMENT_STATE")
    if enrollment["consent_status"] != "CONSENTED":
        fail("ERR_INVALID_ENROLLMENT_STATE")
    if enrollment["consent_amendment_count"] >= 3:
        fail("ERR_CONSENT_AMENDMENT_LIMIT")

    enrollment["consent_status"] = "AMENDMENT_PENDING"
    enrollment["consent_amendment_count"] = enrollment["consent_amendment_count"] + 1
    touch(enrollment)
    svc.cascade_consent_amendment(enrollment)
    return object_response(public(enrollment))


@bp.route("/cbb/enrollments/<eid>/withdraw", methods=["POST"])
@endpoint("ParentGuardian", "IntakeCoordinator", "PlatformAdmin")
def withdraw(user_id, role, eid):
    svc.require_pg_enrollment(user_id, role, eid)
    body = get_body()
    reason = v_str(body, "withdrawal_reason_code", min_len=1)
    enrollment = svc.get_enrollment(eid)

    prior = enrollment["lifecycle_status"]
    if prior not in ("CONSENT_PENDING", "ACTIVE", "KIT_DISPATCHED", "COLLECTED"):
        fail("ERR_INVALID_ENROLLMENT_STATE")
    if prior == "COLLECTED":
        for unit in svc.enrollment_units(eid):
            if unit["availability_status"] in ("RESERVED", "RELEASED"):
                fail("ERR_INVALID_UNIT_STATE")

    enrollment["lifecycle_status"] = "WITHDRAWN"
    if enrollment["consent_status"] in ("PENDING", "CONSENTED", "AMENDMENT_PENDING"):
        enrollment["consent_status"] = "REVOKED"
    enrollment["withdrawal_reason_code"] = reason
    touch(enrollment)
    svc.withdraw_cascade(enrollment, prior)
    return object_response(public(enrollment))
