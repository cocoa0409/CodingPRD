"""Certificate endpoints: list, get, suspend, reinstate, withdraw,
scope-changes (create + list), appeals list, directory-listing."""

from flask import Blueprint, request

import db
from db import get_now, touch
from errors import (
    ApiError,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_INVALID_CERTIFICATE_STATE,
    ERR_OPEN_NCS_REMAIN,
    ERR_SCOPE_CATEGORY_UNSUPPORTED,
    ERR_STALE_CERTIFICATE_VERSION,
)
from middleware import (
    get_auth,
    require_role,
    forbid_ownership,
    invalid_request,
    body_preflight,
    get_body,
    req_string,
    req_categories,
)
from response import success_object, success_list, parse_pagination, paginate
from services.core import (
    application_of,
    listing_for_certificate,
    reinstate_certificate,
    suspend_certificate,
    withdraw_certificate,
)

bp = Blueprint("certificates", __name__)


def _get_certificate_or_404(certificate_id):
    certificate = db.certificates.get(certificate_id)
    if not certificate:
        raise ApiError(
            ERR_CERTIFICATE_NOT_FOUND, "Certificate path id does not exist", 404
        )
    return certificate


def _check_certificate_read_ownership(user_id, role, certificate):
    if role == "ClientAdmin" and certificate["client_id"] != user_id:
        forbid_ownership("ClientAdmin may read only its own certificates")


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------


@bp.get("/certificates")
def list_certificates():
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "DecisionMaker"))
    limit, offset = parse_pagination()
    items = list(db.certificates.values())
    # A ClientAdmin sees only its own certificates.
    if role == "ClientAdmin":
        items = [c for c in items if c["client_id"] == user_id]
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [c for c in items if c["client_id"] == client_id]
    scheme_id = request.args.get("scheme_id")
    if scheme_id is not None:
        items = [c for c in items if c["scheme_id"] == scheme_id]
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [c for c in items if c["application_id"] == application_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    # created_at ASC (PRD §3.8); stable sort keeps creation order on ties.
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(c, "certificates") for c in page], total, limit, offset
    )


@bp.get("/certificates/<certificate_id>")
def get_certificate(certificate_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker"))
    certificate = _get_certificate_or_404(certificate_id)
    _check_certificate_read_ownership(user_id, role, certificate)
    return success_object(db.serialize(certificate, "certificates"))


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


@bp.post("/certificates/<certificate_id>/suspend")
def suspend_certificate_endpoint(certificate_id):
    _, role = get_auth()
    require_role(role, ("DecisionMaker",))
    body_preflight()
    certificate = _get_certificate_or_404(certificate_id)
    if certificate["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_CERTIFICATE_STATE,
            "Certificate status does not permit suspension",
            409,
        )
    body = get_body()
    # Manual suspension: the caller supplies a free-text reason; the recorded
    # suspension_reason is the MANUAL marker per §3.8.
    req_string(body, "reason")
    suspend_certificate(certificate, "MANUAL", get_now())
    return success_object(db.serialize(certificate, "certificates"))


@bp.post("/certificates/<certificate_id>/reinstate")
def reinstate_certificate_endpoint(certificate_id):
    _, role = get_auth()
    require_role(role, ("DecisionMaker",))
    certificate = _get_certificate_or_404(certificate_id)
    if certificate["status"] != "SUSPENDED":
        raise ApiError(
            ERR_INVALID_CERTIFICATE_STATE,
            "Certificate status does not permit reinstatement",
            409,
        )
    # NC-triggered suspensions first require every nonconformity raised on
    # audits of the same (client, scheme) to be CLOSED. A MANUAL suspension
    # carries no NC guard.
    if certificate.get("suspension_reason") in ("NC_OVERDUE", "CAP_REJECT_LIMIT"):
        for audit in db.audits.values():
            application = application_of(audit)
            if (
                not application
                or application["client_id"] != certificate["client_id"]
                or application["scheme_id"] != certificate["scheme_id"]
            ):
                continue
            for nc in db.nonconformities.values():
                if nc["audit_id"] == audit["id"] and nc["status"] != "CLOSED":
                    raise ApiError(
                        ERR_OPEN_NCS_REMAIN,
                        "Every nonconformity of the (client, scheme) must be CLOSED before reinstatement",
                        422,
                    )
    reinstate_certificate(certificate, get_now())
    return success_object(db.serialize(certificate, "certificates"))


@bp.post("/certificates/<certificate_id>/withdraw")
def withdraw_certificate_endpoint(certificate_id):
    _, role = get_auth()
    require_role(role, ("DecisionMaker",))
    certificate = _get_certificate_or_404(certificate_id)
    if certificate["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            ERR_INVALID_CERTIFICATE_STATE,
            "Certificate status does not permit withdrawal",
            409,
        )
    withdraw_certificate(certificate, get_now())
    return success_object(db.serialize(certificate, "certificates"))


# ---------------------------------------------------------------------------
# Scope changes against a certificate (OCC-guarded)
# ---------------------------------------------------------------------------


@bp.post("/certificates/<certificate_id>/scope-changes")
def create_scope_change(certificate_id):
    user_id, role = get_auth()
    require_role(role, ("ClientAdmin",))
    body_preflight()
    certificate = _get_certificate_or_404(certificate_id)
    # Ownership first: the certificate's client must equal X-User-ID.
    if certificate["client_id"] != user_id:
        forbid_ownership("Only the owning client may request a scope change")
    # State before body parsing: the certificate must be ACTIVE.
    if certificate["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_CERTIFICATE_STATE,
            "Scope changes may be requested only on an ACTIVE certificate",
            409,
        )
    body = get_body()
    requested = req_categories(body, "requested_categories")
    reason = req_string(body, "reason")
    if "expected_certificate_version" not in body or body["expected_certificate_version"] is None:
        invalid_request("Missing required field: expected_certificate_version")
    expected = body["expected_certificate_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        invalid_request("expected_certificate_version must be an integer")
    # Priority 5 — OCC guard: the requested certificate version must match
    # the current one.
    if expected != certificate["version"]:
        raise ApiError(
            ERR_STALE_CERTIFICATE_VERSION,
            "expected_certificate_version does not match the certificate's current version",
            412,
        )
    scheme = db.schemes.get(certificate["scheme_id"])
    if scheme:
        supported = set(scheme["supported_category_codes"])
        for cat in requested:
            if cat.get("category_code") not in supported:
                raise ApiError(
                    ERR_SCOPE_CATEGORY_UNSUPPORTED,
                    "Category code %s is not supported by the scheme"
                    % cat.get("category_code"),
                    422,
                )

    now = get_now()
    scope_change = {
        "id": db.new_id(),
        "certificate_id": certificate["id"],
        "requested_categories": requested,
        "reason": reason,
        "status": "PENDING",
        "decided_by": None,
        "decided_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.scope_changes[scope_change["id"]] = scope_change
    # Creating a scope change itself touches the certificate record.
    touch(certificate)
    return success_object(db.serialize(scope_change, "scope_changes"), status=201)


@bp.get("/certificates/<certificate_id>/scope-changes")
def list_scope_changes(certificate_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "DecisionMaker"))
    certificate = _get_certificate_or_404(certificate_id)
    _check_certificate_read_ownership(user_id, role, certificate)
    limit, offset = parse_pagination()
    items = [
        s for s in db.scope_changes.values() if s["certificate_id"] == certificate_id
    ]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    items.sort(key=lambda s: s["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(s, "scope_changes") for s in page], total, limit, offset
    )


# ---------------------------------------------------------------------------
# Appeals of a certificate
# ---------------------------------------------------------------------------


@bp.get("/certificates/<certificate_id>/appeals")
def list_certificate_appeals(certificate_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "DecisionMaker"))
    certificate = _get_certificate_or_404(certificate_id)
    _check_certificate_read_ownership(user_id, role, certificate)
    limit, offset = parse_pagination()
    items = [a for a in db.appeals.values() if a["certificate_id"] == certificate_id]
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(a, "appeals") for a in page], total, limit, offset
    )


# ---------------------------------------------------------------------------
# Directory listing of a certificate
# ---------------------------------------------------------------------------


@bp.get("/certificates/<certificate_id>/directory-listing")
def get_certificate_directory_listing(certificate_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "DecisionMaker"))
    certificate = _get_certificate_or_404(certificate_id)
    _check_certificate_read_ownership(user_id, role, certificate)
    limit, offset = parse_pagination()
    listing = listing_for_certificate(certificate_id)
    items = [listing] if listing else []
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(l, "directory_listings") for l in page], total, limit, offset
    )
