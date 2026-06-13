"""DestructionCertificate read + void endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import db, touch
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    serialize, paginate, sort_by_created, get_certificate_or_404,
)

bp = Blueprint("certificates", __name__)


@bp.get("/certificates/<cert_id>")
def get_certificate(cert_id):
    _, role = get_auth()
    require_role(role, {"AccountManager", "ComplianceOfficer"})
    c = get_certificate_or_404(cert_id)
    return object_response(serialize(c), 200)


@bp.get("/certificates")
def list_certificates():
    _, role = get_auth()
    require_role(role, {"AccountManager", "ComplianceOfficer"})
    items = list(db.certificates.values())
    order_id = request.args.get("order_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(c) for c in page], limit, offset, total, 200)


@bp.post("/certificates/<cert_id>/void")
def void_certificate(cert_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    c = get_certificate_or_404(cert_id)
    c["status"] = "VOIDED"
    touch(c)
    return object_response(serialize(c), 200)
