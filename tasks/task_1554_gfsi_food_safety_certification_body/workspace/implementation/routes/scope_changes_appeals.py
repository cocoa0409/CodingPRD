"""ScopeChange decision and Appeal endpoints (create + decide)."""

from flask import Blueprint

import db
from db import days, get_now, touch
from errors import (
    ApiError,
    ERR_APPEAL_NOT_FOUND,
    ERR_APPEAL_NOT_INDEPENDENT,
    ERR_APPEAL_WINDOW_EXPIRED,
    ERR_DUPLICATE_APPEAL,
    ERR_INVALID_APPEAL_STATE,
    ERR_INVALID_CERTIFICATE_STATE,
    ERR_INVALID_SCOPE_CHANGE_STATE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SCOPE_CHANGE_NOT_FOUND,
)
from middleware import (
    get_auth,
    require_role,
    forbid_ownership,
    body_preflight,
    get_body,
    req_string,
    req_enum,
)
from response import success_object
from services.core import listing_for_certificate, scope_summary

bp = Blueprint("scope_changes_appeals", __name__)


# ---------------------------------------------------------------------------
# Scope-change decision
# ---------------------------------------------------------------------------


@bp.post("/scope-changes/<scope_change_id>/decision")
def decide_scope_change(scope_change_id):
    user_id, role = get_auth()
    require_role(role, ("DecisionMaker",))
    body_preflight()
    scope_change = db.scope_changes.get(scope_change_id)
    if not scope_change:
        raise ApiError(
            ERR_SCOPE_CHANGE_NOT_FOUND, "ScopeChange path id does not exist", 404
        )
    if scope_change["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_SCOPE_CHANGE_STATE,
            "ScopeChange status does not permit a decision",
            409,
        )
    body = get_body()
    outcome = req_enum(body, "outcome", ("APPROVED", "REJECTED"))

    now = get_now()
    scope_change["status"] = outcome
    scope_change["decided_by"] = user_id
    scope_change["decided_at"] = now
    touch(scope_change)

    if outcome == "APPROVED":
        certificate = db.certificates.get(scope_change["certificate_id"])
        if certificate is not None:
            # Approval replaces the certificate's product categories.
            certificate["product_categories"] = scope_change["requested_categories"]
            touch(certificate)
            # The directory listing's scope summary is regenerated from the
            # new product categories.
            listing = listing_for_certificate(certificate["id"])
            if listing is not None:
                listing["scope_summary"] = scope_summary(
                    certificate["product_categories"]
                )
                touch(listing)

    return success_object(db.serialize(scope_change, "scope_changes"))


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------


@bp.post("/appeals")
def create_appeal():
    user_id, role = get_auth()
    require_role(role, ("ClientAdmin",))
    body_preflight()
    body = get_body()
    certificate_id = req_string(body, "certificate_id")
    grounds = req_string(body, "grounds")

    # Priority 6 — body foreign-key reference must exist.
    certificate = db.certificates.get(certificate_id)
    if not certificate:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND,
            "Body foreign-key reference does not exist: certificate_id",
            422,
        )
    # Ownership: the certificate's client chain must equal X-User-ID.
    if certificate["client_id"] != user_id:
        forbid_ownership("Only the owning client may appeal the certificate")
    # State: the target certificate must be SUSPENDED or WITHDRAWN.
    if certificate["status"] not in ("SUSPENDED", "WITHDRAWN"):
        raise ApiError(
            ERR_INVALID_CERTIFICATE_STATE,
            "Appeals may be filed only against a SUSPENDED or WITHDRAWN certificate",
            409,
        )
    # Temporal: filing must land no later than appeal_window_days after
    # status_changed_at; the boundary is inclusive.
    scheme = db.schemes.get(certificate["scheme_id"])
    if scheme is not None and certificate.get("status_changed_at") is not None:
        deadline = certificate["status_changed_at"] + days(
            scheme["appeal_window_days"]
        )
        if get_now() > deadline:
            raise ApiError(
                ERR_APPEAL_WINDOW_EXPIRED,
                "Appeal filed after the appeal window has expired",
                422,
            )
    # Aggregate: at most one appeal in FILED status per certificate.
    for other in db.appeals.values():
        if other["certificate_id"] == certificate_id and other["status"] == "FILED":
            raise ApiError(
                ERR_DUPLICATE_APPEAL,
                "Certificate already has an appeal in FILED status",
                409,
            )

    now = get_now()
    appeal = {
        "id": db.new_id(),
        "certificate_id": certificate_id,
        "grounds": grounds,
        "status": "FILED",
        "decided_by": None,
        "decided_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.appeals[appeal["id"]] = appeal
    return success_object(db.serialize(appeal, "appeals"), status=201)


@bp.post("/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    user_id, role = get_auth()
    require_role(role, ("DecisionMaker",))
    body_preflight()
    appeal = db.appeals.get(appeal_id)
    if not appeal:
        raise ApiError(ERR_APPEAL_NOT_FOUND, "Appeal path id does not exist", 404)
    if appeal["status"] != "FILED":
        raise ApiError(
            ERR_INVALID_APPEAL_STATE,
            "Appeal status does not permit a decision",
            409,
        )
    body = get_body()
    outcome = req_enum(body, "outcome", ("UPHELD", "OVERTURNED"))

    # Independence (§2.7): the acting decision maker must be neither the
    # issuing audit's decision maker nor linked to that audit's auditor.
    certificate = db.certificates.get(appeal["certificate_id"])
    if certificate is not None:
        issuing_audit = db.audits.get(certificate.get("audit_id"))
        if issuing_audit is not None:
            if issuing_audit.get("decision_maker_id") == user_id:
                raise ApiError(
                    ERR_APPEAL_NOT_INDEPENDENT,
                    "Acting decision maker rendered the original decision of the certificate's issuing audit",
                    403,
                )
            dm = db.decision_makers.get(user_id)
            if (
                dm is not None
                and dm.get("linked_auditor_id") is not None
                and issuing_audit.get("auditor_id") is not None
                and dm["linked_auditor_id"] == issuing_audit["auditor_id"]
            ):
                raise ApiError(
                    ERR_APPEAL_NOT_INDEPENDENT,
                    "Acting decision maker is linked to the auditor of the certificate's issuing audit",
                    403,
                )

    now = get_now()
    appeal["status"] = outcome
    appeal["decided_by"] = user_id
    appeal["decided_at"] = now
    touch(appeal)

    if outcome == "OVERTURNED" and certificate is not None:
        # Reinstate: SUSPENDED -> ACTIVE or WITHDRAWN -> ACTIVE; the
        # suspension reason is cleared and the listing re-listed.
        certificate["status"] = "ACTIVE"
        certificate["suspension_reason"] = None
        certificate["status_changed_at"] = now
        touch(certificate)
        listing = listing_for_certificate(certificate["id"])
        if listing is not None:
            listing["status"] = "LISTED"
            listing["listed_at"] = now
            touch(listing)

    return success_object(db.serialize(appeal, "appeals"))
