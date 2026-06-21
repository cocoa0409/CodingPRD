"""Certificate endpoints (PRD §3.8)."""

from flask import Blueprint

import errors
import serialize
from common import parse_pagination, paginate
from db import db
from middleware import require_roles
from response import success_object, success_list
from routes.renewal_cycles import get_cycle_or_404

bp = Blueprint("certificates", __name__)


@bp.route("/certificates/<cert_id>", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def get_certificate(cert_id):
    cert = db.certificates.get(cert_id)
    if cert is None:
        raise errors.not_found(f"Certificate '{cert_id}' not found.")
    return success_object(serialize.certificate(cert), status=200)


@bp.route("/renewal-cycles/<cycle_id>/certificate", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def list_cycle_certificates(cycle_id):
    get_cycle_or_404(cycle_id)
    limit, offset = parse_pagination()
    items = [c for c in db.certificates.values() if c["cycle_id"] == cycle_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.certificate(c) for c in page], limit, offset, total, status=200,
    )
