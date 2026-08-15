"""Nonconformity endpoints: get, submit-cap, review-cap."""

from flask import Blueprint

import db
from db import get_now, touch
from errors import (
    ApiError,
    ERR_NC_NOT_FOUND,
    ERR_INVALID_NC_STATE,
)
from middleware import (
    get_auth,
    require_role,
    forbid_ownership,
    body_preflight,
    get_body,
    req_string,
    req_enum,
    opt_string,
)
from response import success_object
from services.core import (
    application_of,
    scheme_of_audit,
    find_certificate_for_client_scheme,
    suspend_certificate,
)

bp = Blueprint("nonconformities", __name__)


def _get_nc_or_404(nc_id):
    nc = db.nonconformities.get(nc_id)
    if not nc:
        raise ApiError(ERR_NC_NOT_FOUND, "Nonconformity path id does not exist", 404)
    return nc


def _nc_context(nc):
    audit = db.audits.get(nc["audit_id"])
    application = application_of(audit) if audit else None
    return audit, application


@bp.get("/nonconformities/<nc_id>")
def get_nonconformity(nc_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker"))
    nc = _get_nc_or_404(nc_id)
    audit, application = _nc_context(nc)
    if role == "ClientAdmin" and application and application["client_id"] != user_id:
        forbid_ownership("ClientAdmin may read only findings of its own audits")
    if role == "Auditor" and audit and audit.get("auditor_id") is not None:
        if audit["auditor_id"] != user_id:
            forbid_ownership("Auditor may read only findings of its own audits")
    return success_object(db.serialize(nc, "nonconformities"))


@bp.post("/nonconformities/<nc_id>/submit-cap")
def submit_cap(nc_id):
    user_id, role = get_auth()
    require_role(role, ("ClientAdmin",))
    body_preflight()
    nc = _get_nc_or_404(nc_id)
    audit, application = _nc_context(nc)
    # Ownership first: the resource's client chain must equal X-User-ID.
    if not application or application["client_id"] != user_id:
        forbid_ownership("Only the owning client may submit a corrective-action plan")
    if nc["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError(
            ERR_INVALID_NC_STATE,
            "Nonconformity status does not permit CAP submission",
            409,
        )
    body = get_body()
    cap_text = req_string(body, "cap_text")
    nc["cap_text"] = cap_text
    nc["submitted_at"] = get_now()
    nc["status"] = "UNDER_REVIEW"
    touch(nc)
    return success_object(db.serialize(nc, "nonconformities"))


@bp.post("/nonconformities/<nc_id>/review-cap")
def review_cap(nc_id):
    user_id, role = get_auth()
    require_role(role, ("Auditor",))
    body_preflight()
    nc = _get_nc_or_404(nc_id)
    audit, application = _nc_context(nc)
    # Ownership: caller must be the auditor of the finding's audit.
    if audit and audit.get("auditor_id") is not None and audit["auditor_id"] != user_id:
        forbid_ownership("Caller is not the auditor of the finding's audit")
    if nc["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_NC_STATE,
            "Nonconformity status does not permit CAP review",
            409,
        )
    body = get_body()
    outcome = req_enum(body, "outcome", ("ACCEPT", "REJECT"))
    # review_notes is accepted and validated but not persisted — the
    # Nonconformity entity declares no such field.
    opt_string(body, "review_notes")

    now = get_now()
    nc["reviewed_at"] = now

    if outcome == "ACCEPT":
        nc["status"] = "CLOSED"
        touch(nc)
        return success_object(db.serialize(nc, "nonconformities"))

    # REJECT — back to OPEN, rejection_count + 1, possible suspension cascade.
    nc["status"] = "OPEN"
    nc["rejection_count"] = int(nc.get("rejection_count", 0)) + 1
    touch(nc)

    scheme = scheme_of_audit(audit) if audit else None
    if (
        scheme
        and application
        and nc["rejection_count"] >= scheme["max_cap_rejections"]
    ):
        active = find_certificate_for_client_scheme(
            application["client_id"], application["scheme_id"], statuses={"ACTIVE"}
        )
        if active:
            suspend_certificate(active[0], "CAP_REJECT_LIMIT", now)

    return success_object(db.serialize(nc, "nonconformities"))
