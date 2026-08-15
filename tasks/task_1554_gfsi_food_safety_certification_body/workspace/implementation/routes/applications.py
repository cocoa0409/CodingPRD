"""Application endpoints: create, list, get, submit, review, audits."""

from flask import Blueprint, request

import db
from db import days, get_now, touch
from errors import (
    ApiError,
    ERR_APPLICATION_NOT_FOUND,
    ERR_INVALID_APPLICATION_STATE,
    ERR_DUPLICATE_APPLICATION,
    ERR_DUPLICATE_CERTIFICATION_SCOPE,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import (
    get_auth,
    require_role,
    forbid_ownership,
    body_preflight,
    get_body,
    req_string,
    req_enum,
    req_categories,
)
from response import success_object, success_list, parse_pagination, paginate
from services.core import (
    check_categories_supported,
    fee_quote,
    find_certificate_for_client_scheme,
)

bp = Blueprint("applications", __name__)


def _get_application_or_404(application_id):
    application = db.applications.get(application_id)
    if not application:
        raise ApiError(
            ERR_APPLICATION_NOT_FOUND, "Application path id does not exist", 404
        )
    return application


@bp.post("/applications")
def create_application():
    user_id, role = get_auth()
    require_role(role, ("ClientAdmin",))
    body = get_body()
    scheme_id = req_string(body, "scheme_id")
    site_name = req_string(body, "site_name")
    categories = req_categories(body, "product_categories")
    scope_text = req_string(body, "scope_text")

    # Body FK reference: the scheme must exist.
    scheme = db.schemes.get(scheme_id)
    if not scheme:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "Referenced scheme does not exist", 422
        )

    check_categories_supported(scheme, categories)

    # Only one open application per (client, scheme).
    for other in db.applications.values():
        if (
            other["client_id"] == user_id
            and other["scheme_id"] == scheme_id
            and other["status"] in ("DRAFT", "SUBMITTED")
        ):
            raise ApiError(
                ERR_DUPLICATE_APPLICATION,
                "Same (client, scheme) already has an application in DRAFT or SUBMITTED",
                409,
            )

    now = get_now()
    application = {
        "id": db.new_id(),
        "client_id": user_id,
        "scheme_id": scheme_id,
        "site_name": site_name,
        "product_categories": categories,
        "scope_text": scope_text,
        "status": "DRAFT",
        "provisional_fee_quote": None,
        "submitted_at": None,
        "reviewed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.applications[application["id"]] = application
    return success_object(db.serialize(application, "applications"), status=201)


@bp.get("/applications")
def list_applications():
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "DecisionMaker"))
    limit, offset = parse_pagination()
    items = list(db.applications.values())
    # A ClientAdmin sees only its own applications.
    if role == "ClientAdmin":
        items = [a for a in items if a["client_id"] == user_id]
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    scheme_id = request.args.get("scheme_id")
    if scheme_id is not None:
        items = [a for a in items if a["scheme_id"] == scheme_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    # created_at ASC (PRD §3.3). The logical clock makes created_at ties the
    # norm; a stable sort over the insertion-ordered store resolves ties by
    # creation order deterministically.
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(a, "applications") for a in page], total, limit, offset
    )


@bp.get("/applications/<application_id>")
def get_application(application_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker"))
    application = _get_application_or_404(application_id)
    if role == "ClientAdmin" and application["client_id"] != user_id:
        forbid_ownership("ClientAdmin may read only its own applications")
    return success_object(db.serialize(application, "applications"))


@bp.post("/applications/<application_id>/submit")
def submit_application(application_id):
    user_id, role = get_auth()
    require_role(role, ("ClientAdmin",))
    application = _get_application_or_404(application_id)
    # Ownership is checked first.
    if application["client_id"] != user_id:
        forbid_ownership("Only the owning client may submit the application")
    if application["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_APPLICATION_STATE,
            "Application status does not permit submission",
            409,
        )
    application["status"] = "SUBMITTED"
    application["submitted_at"] = get_now()
    touch(application)
    return success_object(db.serialize(application, "applications"))


@bp.post("/applications/<application_id>/review")
def review_application(application_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    body_preflight()
    application = _get_application_or_404(application_id)
    body = get_body()
    outcome = req_enum(body, "outcome", ("ACCEPTED", "REJECTED"))
    rejection_reason = body.get("rejection_reason")
    if rejection_reason is not None and not isinstance(rejection_reason, str):
        from middleware import invalid_request

        invalid_request("rejection_reason must be a string")

    if application["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_APPLICATION_STATE,
            "Application status does not permit review",
            409,
        )

    now = get_now()
    if outcome == "REJECTED":
        application["status"] = "REJECTED"
        application["reviewed_at"] = now
        application["rejection_reason"] = rejection_reason
        touch(application)
        return success_object(db.serialize(application, "applications"))

    # ACCEPTED — duplicate guards.
    for other in db.applications.values():
        if (
            other["id"] != application["id"]
            and other["client_id"] == application["client_id"]
            and other["scheme_id"] == application["scheme_id"]
            and other["status"] in ("DRAFT", "SUBMITTED")
        ):
            raise ApiError(
                ERR_DUPLICATE_APPLICATION,
                "Another application for the same (client, scheme) is in DRAFT or SUBMITTED",
                409,
            )
    if find_certificate_for_client_scheme(
        application["client_id"],
        application["scheme_id"],
        statuses={"ACTIVE", "SUSPENDED"},
    ):
        raise ApiError(
            ERR_DUPLICATE_CERTIFICATION_SCOPE,
            "A certificate in ACTIVE or SUSPENDED already exists for this (client, scheme)",
            409,
        )

    scheme = db.schemes.get(application["scheme_id"])
    application["status"] = "ACCEPTED"
    application["reviewed_at"] = now
    application["provisional_fee_quote"] = fee_quote(
        scheme, application["product_categories"]
    )
    touch(application)

    # Acceptance brings the INITIAL audit into existence.
    window_start = now + days(14)
    window_end = window_start + days(scheme["announced_max_window_days"])
    audit = {
        "id": db.new_id(),
        "application_id": application["id"],
        "auditor_id": None,
        "decision_maker_id": None,
        "sequence_number": 1,
        "audit_type": "INITIAL",
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "reported_score": None,
        "resolved_score": None,
        "audit_fee": None,
        "actual_days": None,
        "decision_outcome": None,
        "started_at": None,
        "reported_at": None,
        "decided_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.audits[audit["id"]] = audit
    return success_object(db.serialize(application, "applications"))


@bp.get("/applications/<application_id>/audits")
def list_application_audits(application_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker"))
    application = _get_application_or_404(application_id)
    if role == "ClientAdmin" and application["client_id"] != user_id:
        forbid_ownership("ClientAdmin may read only its own applications")
    limit, offset = parse_pagination()
    items = [
        a for a in db.audits.values() if a["application_id"] == application_id
    ]
    # sequence_number ASC (PRD §3.3); unique within an application's chain.
    items.sort(key=lambda a: a["sequence_number"])
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(a, "audits") for a in page], total, limit, offset)
