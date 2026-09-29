"""Local health-department registration and certificate posting."""
from datetime import timedelta

from flask import Blueprint

import authz
import validation as V
from authz import require, find, deny_scope
from envelope import ok
from errors import ApiError
from helpers import paged, scoped_filter, match
from store import store

registrations_bp = Blueprint("registrations", __name__)


def _registration_scope(registration, user_id, role):
    if role == authz.PROVIDER_ADMIN \
            and authz.provider_of_registration(registration) != user_id:
        deny_scope()
    if role == authz.HEALTH_OFFICER \
            and registration["jurisdiction_id"] != user_id:
        deny_scope()


def _deadline(filed_at, jurisdiction):
    days = jurisdiction["posting_deadline_days"] if jurisdiction else 30
    return filed_at + timedelta(days=days)


@registrations_bp.post("/local-registrations")
def file_registration():
    user_id, role = require(authz.PROVIDER_ADMIN)
    body = V.get_body()
    certificate_id = V.req_id(body, "certificate_id")
    establishment_name = V.req_str(body, "establishment_name", 1)
    establishment_address = V.req_str(body, "establishment_address", 1)
    certificate = find("certificate", certificate_id)
    if authz.provider_of_certificate(certificate) != user_id:
        deny_scope()
    if certificate["status"] != "ISSUED":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID",
                       "only an ISSUED certificate may be filed")
    jurisdiction = store.jurisdictions.get(certificate["jurisdiction_id"])
    if jurisdiction is not None and not jurisdiction["requires_local_registration"]:
        raise ApiError("ERR_LOCAL_REGISTRATION_NOT_REQUIRED",
                       "the jurisdiction does not require local registration")
    filed_at = store.clock
    row = store.base()
    row.update({
        "certificate_id": certificate_id,
        "jurisdiction_id": certificate["jurisdiction_id"],
        "establishment_name": establishment_name,
        "establishment_address": establishment_address,
        "posting_location": None,
        "filed_at": filed_at,
        "posting_deadline_at": _deadline(filed_at, jurisdiction),
        "posted_at": None,
        "status": "FILED",
        "rejection_reason": None,
        "verified_by_user_id": None,
        "refile_count": 0,
    })
    store.registrations[row["id"]] = row
    return ok(row, 201)


@registrations_bp.get("/local-registrations/<registration_id>")
def read_registration(registration_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.HEALTH_OFFICER)
    registration = find("registration", registration_id)
    _registration_scope(registration, user_id, role)
    return ok(registration)


@registrations_bp.get("/local-registrations")
def list_registrations():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.HEALTH_OFFICER)
    certificate_filter = V.query_id("certificate_id")
    jurisdiction_filter = V.query_id("jurisdiction_id")
    status = V.query_enum("status", V.LOCAL_REGISTRATION_STATUS)
    if role == authz.HEALTH_OFFICER:
        jurisdiction_filter = scoped_filter(jurisdiction_filter, user_id)
    rows = [r for r in store.registrations.values()
            if match(r, "certificate_id", certificate_filter)
            and match(r, "jurisdiction_id", jurisdiction_filter)
            and match(r, "status", status)]
    if role == authz.PROVIDER_ADMIN:
        rows = [r for r in rows
                if authz.provider_of_registration(r) == user_id]
    return paged(rows)


@registrations_bp.post("/local-registrations/<registration_id>/posting-confirmation")
def confirm_posting(registration_id):
    user_id, role = require(authz.PROVIDER_ADMIN)
    registration = find("registration", registration_id)
    _registration_scope(registration, user_id, role)
    body = V.get_body()
    posting_location = V.req_str(body, "posting_location", 1)
    certificate = store.certificates.get(registration["certificate_id"])
    if certificate is None or certificate["status"] != "ISSUED":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID",
                       "the owning certificate is not ISSUED")
    if registration["status"] not in ("FILED", "DELINQUENT"):
        raise ApiError("ERR_REGISTRATION_STATE_INVALID",
                       "the registration is neither FILED nor DELINQUENT")
    registration["status"] = "POSTED"
    registration["posted_at"] = store.clock
    registration["posting_location"] = posting_location
    store.touch(registration)
    return ok(registration)


@registrations_bp.post("/local-registrations/<registration_id>/verification")
def verify_registration(registration_id):
    user_id, role = require(authz.HEALTH_OFFICER)
    registration = find("registration", registration_id)
    _registration_scope(registration, user_id, role)
    body = V.get_body()
    decision = V.req_enum(body, "decision", ["VERIFY", "REJECT"])
    rejection_reason = V.opt_str(body, "rejection_reason", 1, None, None)
    certificate = store.certificates.get(registration["certificate_id"])
    if decision == "VERIFY" \
            and (certificate is None or certificate["status"] != "ISSUED"):
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID",
                       "the owning certificate is not ISSUED")
    if registration["status"] != "POSTED":
        raise ApiError("ERR_REGISTRATION_STATE_INVALID",
                       "the registration is not POSTED")
    if decision == "VERIFY":
        registration["status"] = "VERIFIED"
        registration["verified_by_user_id"] = user_id
    else:
        registration["status"] = "REJECTED"
        registration["rejection_reason"] = rejection_reason
        registration["posted_at"] = None
        registration["posting_location"] = None
    store.touch(registration)
    return ok(registration)


@registrations_bp.post("/local-registrations/<registration_id>/refiling")
def refile_registration(registration_id):
    user_id, role = require(authz.PROVIDER_ADMIN)
    registration = find("registration", registration_id)
    _registration_scope(registration, user_id, role)
    body = V.get_body()
    address = V.opt_str(body, "establishment_address", 1, None, None)
    certificate = store.certificates.get(registration["certificate_id"])
    if certificate is None or certificate["status"] != "ISSUED":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID",
                       "the owning certificate is not ISSUED")
    if registration["status"] != "REJECTED":
        raise ApiError("ERR_REGISTRATION_STATE_INVALID",
                       "only a REJECTED registration may be refiled")
    jurisdiction = store.jurisdictions.get(registration["jurisdiction_id"])
    filed_at = store.clock
    if address is not None:
        registration["establishment_address"] = address
    registration["status"] = "FILED"
    registration["filed_at"] = filed_at
    registration["posting_deadline_at"] = _deadline(filed_at, jurisdiction)
    registration["posted_at"] = None
    registration["rejection_reason"] = None
    registration["refile_count"] += 1
    store.touch(registration)
    return ok(registration)
