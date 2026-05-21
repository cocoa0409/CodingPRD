"""CompanionCertificate endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object, ok_array
from ..store import store, new_uuid
from ..timeutil import clock, add_months
from ..services.common import (
    parse_pagination, paginate, bump_version,
    get_member_or_404, get_certificate_owned, enforce_member_ownership,
)
from ..services.serialize import serialize_certificate


certificates_bp = Blueprint("certificates", __name__)


@certificates_bp.get("/members/<member_id>/certificates")
@require_roles("Member", "ProgramAdmin")
def list_certificates(member_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    items = [
        c for c in store.companion_certificates.values()
        if c["member_id"] == member_id
        and (status_f is None or c["status"] == status_f)
    ]
    items.sort(key=lambda c: c["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_certificate(c) for c in page]
    return ok_array(data, limit, offset, total, has_more)


@certificates_bp.post("/members/<member_id>/certificates")
@require_roles("ProgramAdmin")
def grant_certificate(member_id):
    get_member_or_404(member_id)
    now = clock.now()
    cid = new_uuid()
    c = {
        "id": cid,
        "member_id": member_id,
        "status": "ACTIVE",
        "issued_at": now,
        "expires_at": add_months(now, 12),
        "reserved_for_booking_id": None,
        "used_on_booking_id": None,
        "issued_reason": "ADMIN_GRANT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.companion_certificates[cid] = c
    return ok_object(serialize_certificate(c), 201)


@certificates_bp.post("/members/<member_id>/certificates/<cert_id>/revoke")
@require_roles("ProgramAdmin")
def revoke_certificate(member_id, cert_id):
    get_member_or_404(member_id)
    c = get_certificate_owned(member_id, cert_id)
    if c["status"] not in ("ACTIVE", "RESERVED"):
        raise E.ApiError(E.ERR_CERTIFICATE_NOT_USABLE, 409, "Certificate cannot be revoked from this state.")
    c["status"] = "REVOKED"
    bump_version(c)
    return ok_object(serialize_certificate(c))
