"""CertificateTemplate routes."""

from flask import Blueprint, request

from middleware import require_role
from response import parse_pagination, success, success_list
from services import catalog
from services.serializers import serialize_certificate_template

bp = Blueprint("certificate_templates", __name__)


@bp.post("/certificate-templates")
def create():
    require_role("CertificateOfficer")
    record = catalog.create_certificate_template(request.get_json(silent=True))
    return success(serialize_certificate_template(record), 201)


@bp.post("/certificate-templates/<template_id>/publish")
def publish(template_id):
    require_role("CertificateOfficer")
    record = catalog.publish_certificate_template(template_id,
                                                  request.get_json(silent=True) or {})
    return success(serialize_certificate_template(record), 200)


@bp.get("/certificate-templates")
def list_():
    require_role("PlatformAdmin", "CatalogManager", "CertificateOfficer")
    limit, offset = parse_pagination(request.args)
    filters = {"status": request.args.get("status")}
    rows, total = catalog.list_certificate_templates(filters, limit, offset)
    return success_list([serialize_certificate_template(r) for r in rows],
                        total, limit, offset)
