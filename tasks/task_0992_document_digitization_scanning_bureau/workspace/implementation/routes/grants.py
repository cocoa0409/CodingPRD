"""Access grants: get, revoke, documents list, download."""

from datetime import datetime, timezone

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_CLIENT_SUSPENDED,
    ERR_GRANT_EXPIRED,
    ERR_GRANT_VAULT_ONLY,
    ERR_SCOPE_INSUFFICIENT,
    ERR_DOCUMENT_NOT_DELIVERED,
)
from middleware import require_roles, check_client_user_scope
from response import success_object, success_list, parse_pagination, iso_ts
from util import get_body, bump, new_id
from services.serializers import access_grant_view, document_view

bp = Blueprint("grants", __name__)


def get_grant_or_404(grant_id):
    g = db.access_grants.get(grant_id)
    if not g:
        raise ApiError(ERR_NOT_FOUND, "Access grant not found", 404)
    return g


def _parse(iso):
    s = iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def lazy_expire(grant):
    """ACTIVE -> EXPIRED when the logical clock has passed expires_at."""
    if grant["status"] == "ACTIVE" and db.current_utc > _parse(grant["expires_at"]):
        grant["status"] = "EXPIRED"
        bump(grant)


def check_grant_usable(grant):
    """Lazy expiry + must be ACTIVE."""
    lazy_expire(grant)
    if grant["status"] == "EXPIRED":
        raise ApiError(ERR_GRANT_EXPIRED, "Access grant has expired", 409)
    if grant["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Access grant is not ACTIVE", 409)


def check_grant_client_active(grant):
    client = db.clients.get(grant["client_id"])
    if client and client["status"] == "SUSPENDED":
        raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)


@bp.route("/access-grants/<id>", methods=["GET"])
@require_roles("PlatformAdmin", "ComplianceOfficer", "ClientUser")
def get_grant(id, _user_id, _role):
    grant = get_grant_or_404(id)
    check_client_user_scope(_user_id, _role, grant["client_id"])
    lazy_expire(grant)
    return success_object(access_grant_view(grant))


@bp.route("/access-grants/<id>/revoke", methods=["POST"])
@require_roles("ClientUser")
def revoke_grant(id, _user_id, _role):
    grant = get_grant_or_404(id)
    get_body()
    check_client_user_scope(_user_id, _role, grant["client_id"])
    check_grant_client_active(grant)
    lazy_expire(grant)
    if grant["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Access grant is not ACTIVE", 409)
    grant["status"] = "REVOKED"
    bump(grant)
    return success_object(access_grant_view(grant))


@bp.route("/access-grants/<id>/documents", methods=["GET"])
@require_roles("ClientUser")
def grant_documents(id, _user_id, _role):
    grant = get_grant_or_404(id)
    check_client_user_scope(_user_id, _role, grant["client_id"])
    check_grant_client_active(grant)
    check_grant_usable(grant)
    limit, offset = parse_pagination(request.args)
    items = [d for d in db.documents.values() if d["batch_id"] == grant["batch_id"]]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([document_view(d) for d in page], limit, offset, total)


@bp.route("/access-grants/<id>/documents/<docId>/download", methods=["GET"])
@require_roles("ClientUser")
def download_document(id, docId, _user_id, _role):
    grant = get_grant_or_404(id)
    check_client_user_scope(_user_id, _role, grant["client_id"])
    check_grant_client_active(grant)
    doc = db.documents.get(docId)
    if not doc or doc["batch_id"] != grant["batch_id"]:
        raise ApiError(ERR_NOT_FOUND, "Document not found under this grant", 404)
    # State checks: grant usable; document DELIVERED
    check_grant_usable(grant)
    if doc["status"] != "DELIVERED":
        raise ApiError(ERR_DOCUMENT_NOT_DELIVERED, "Document is not DELIVERED", 409)
    # Business-safety: vault-only and scope
    if grant.get("vault_only"):
        raise ApiError(
            ERR_GRANT_VAULT_ONLY, "vault_only grant forbids the public download channel", 422
        )
    if grant["scope"] != "FULL_IMAGE":
        raise ApiError(ERR_SCOPE_INSUFFICIENT, "Download requires FULL_IMAGE scope", 403)
    payload = {
        "document_id": doc["id"],
        "download_url": f"https://download.digitization-bureau.local/{grant['id']}/{doc['id']}/{new_id()}",
        "expires_in_seconds": 300,
    }
    return success_object(payload)
