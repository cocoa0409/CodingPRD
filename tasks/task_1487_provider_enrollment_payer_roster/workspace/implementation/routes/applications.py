"""Enrollment applications: draft lifecycle, info-request loop, approval with
record creation + claim-release cascade."""
from datetime import timedelta

from flask import Blueprint, request

from db import base_fields, store, touch
from errors import (
    ApiError,
    ERR_APPLICATION_IN_FLIGHT,
    ERR_CAQH_ATTESTATION_NOT_CURRENT,
    ERR_ENROLLMENT_OVERLAP,
    ERR_PROVIDER_TERMINATED,
    ERR_RETRO_WINDOW_EXCEEDED,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, require_roles
from response import list_response, success_object
from serializers import pub
from services import (
    ACTIVE_RECORD_STATES,
    IN_FLIGHT_APP_STATES,
    compute_effective_date,
    create_enrollment_record,
    enrollment_overlap_exists,
    profile_of,
    records_of,
)
from util import fmt_ts
from validate import body, req_date, req_enum, req_str

bp = Blueprint("applications", __name__)


def _get_app(aid):
    app = store.applications.get(aid)
    if app is None:
        raise not_found("EnrollmentApplication")
    return app


def _compliance_gates(app):
    """Provider must be ACTIVE; provider's CAQH profile must be ATTESTED or DUE."""
    prov = store.providers[app["provider_id"]]
    if prov["status"] != "ACTIVE":
        raise ApiError(ERR_PROVIDER_TERMINATED, 409, "Provider is TERMINATED")
    prof = profile_of(app["provider_id"])
    if prof is None or prof["status"] not in ("ATTESTED", "DUE"):
        raise ApiError(
            ERR_CAQH_ATTESTATION_NOT_CURRENT,
            409,
            "The provider's CAQH attestation is not current",
        )


@bp.post("/api/enrollment-applications")
@require_roles("EnrollmentSpecialist")
def create_application():
    b = body()
    # Existence (tier 3) for body foreign keys before schema (tier 4).
    pid_raw = b.get("provider_id")
    yid_raw = b.get("payer_id")
    if isinstance(pid_raw, str) and pid_raw not in store.providers:
        raise not_found("Provider")
    if isinstance(yid_raw, str) and yid_raw not in store.payers:
        raise not_found("Payer")
    pid = req_str(b, "provider_id")
    yid = req_str(b, "payer_id")
    scope = req_enum(b, "enrollment_scope", ("GROUP_LINK", "INDIVIDUAL"))
    req_eff = req_date(b, "requested_effective_date")
    # Temporal (tier 10): retro window of 90 days.
    floor = (store.clock.date() - timedelta(days=90)).isoformat()
    if req_eff < floor:
        raise ApiError(
            ERR_RETRO_WINDOW_EXCEEDED,
            422,
            "requested_effective_date is earlier than current date - 90 days",
        )
    # Uniqueness/overlap (tier 11): in-flight application, then active record.
    for a in store.applications.values():
        if (
            a["provider_id"] == pid
            and a["payer_id"] == yid
            and a["status"] in IN_FLIGHT_APP_STATES
        ):
            raise ApiError(
                ERR_APPLICATION_IN_FLIGHT,
                409,
                "An application is already in flight for this provider and payer",
            )
    if any(
        r["status"] in ACTIVE_RECORD_STATES for r in records_of(pid, yid)
    ):
        raise ApiError(
            ERR_ENROLLMENT_OVERLAP,
            409,
            "An active enrollment record exists for this provider and payer",
        )
    app = base_fields()
    app.update(
        {
            "provider_id": pid,
            "payer_id": yid,
            "enrollment_scope": scope,
            "requested_effective_date": req_eff,
            "status": "DRAFT",
            "submitted_at": None,
            "approved_at": None,
            "info_request_reason": None,
            "decision_reason": None,
        }
    )
    store.applications[app["id"]] = app
    return success_object(pub(app), 201)


@bp.get("/api/enrollment-applications/<aid>")
@require_roles(*ALL_ROLES)
def get_application(aid):
    return success_object(pub(_get_app(aid)))


@bp.get("/api/enrollment-applications")
@require_roles(*ALL_ROLES)
def list_applications():
    provider_id = request.args.get("provider_id")
    payer_id = request.args.get("payer_id")
    status = request.args.get("status")
    items = [
        a for a in store.applications.values()
        if (provider_id is None or a["provider_id"] == provider_id)
        and (payer_id is None or a["payer_id"] == payer_id)
        and (status is None or a["status"] == status)
    ]
    return list_response(items, pub)


@bp.post("/api/enrollment-applications/<aid>/submit")
@require_roles("EnrollmentSpecialist")
def submit_application(aid):
    app = _get_app(aid)
    if app["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT application can be submitted")
    _compliance_gates(app)
    app["status"] = "SUBMITTED"
    app["submitted_at"] = fmt_ts(store.clock)
    touch(app)
    return success_object(pub(app))


@bp.post("/api/enrollment-applications/<aid>/request-info")
@require_roles("PayerRepresentative")
def request_info(aid):
    app = _get_app(aid)
    b = body()
    reason = req_str(b, "reason")
    if app["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED application can receive an info request")
    app["status"] = "PENDING_INFO"
    app["info_request_reason"] = reason
    touch(app)
    return success_object(pub(app))


@bp.post("/api/enrollment-applications/<aid>/resubmit")
@require_roles("EnrollmentSpecialist")
def resubmit_application(aid):
    app = _get_app(aid)
    if app["status"] != "PENDING_INFO":
        raise invalid_state("Only a PENDING_INFO application can be resubmitted")
    _compliance_gates(app)
    app["status"] = "SUBMITTED"
    app["submitted_at"] = fmt_ts(store.clock)
    touch(app)
    return success_object(pub(app))


@bp.post("/api/enrollment-applications/<aid>/approve")
@require_roles("PayerRepresentative")
def approve_application(aid):
    app = _get_app(aid)
    if app["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED application can be approved")
    # Compliance gates re-checked at approval time.
    _compliance_gates(app)
    payer = store.payers[app["payer_id"]]
    approved_day = store.clock.date()
    effective_date = compute_effective_date(app, payer, approved_day)
    if enrollment_overlap_exists(app["provider_id"], app["payer_id"], effective_date):
        raise ApiError(
            ERR_ENROLLMENT_OVERLAP,
            409,
            "The computed effective date overlaps an existing enrollment interval",
        )
    app["status"] = "APPROVED"
    app["approved_at"] = fmt_ts(store.clock)
    touch(app)
    # Create the EnrollmentRecord (fires the claim-release cascade inside).
    benefit = "GROUP" if app["enrollment_scope"] == "GROUP_LINK" else "INDIVIDUAL"
    create_enrollment_record(
        app["provider_id"],
        app["payer_id"],
        app["enrollment_scope"],
        benefit,
        effective_date,
        payer,
        source_application_id=app["id"],
    )
    return success_object(pub(app))


@bp.post("/api/enrollment-applications/<aid>/reject")
@require_roles("PayerRepresentative")
def reject_application(aid):
    app = _get_app(aid)
    b = body()
    reason = req_str(b, "reason")
    if app["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED application can be rejected")
    app["status"] = "REJECTED"
    app["decision_reason"] = reason
    touch(app)
    return success_object(pub(app))


@bp.post("/api/enrollment-applications/<aid>/withdraw")
@require_roles("EnrollmentSpecialist")
def withdraw_application(aid):
    app = _get_app(aid)
    if app["status"] not in IN_FLIGHT_APP_STATES:
        raise invalid_state("Only a non-terminal application can be withdrawn")
    app["status"] = "WITHDRAWN"
    touch(app)
    return success_object(pub(app))
