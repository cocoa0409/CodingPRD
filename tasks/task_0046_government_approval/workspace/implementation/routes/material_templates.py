"""MaterialTemplate routes."""

from flask import Blueprint, request

from middleware import require_role
from response import parse_pagination, success, success_list
from services import catalog
from services.serializers import serialize_material_template

bp = Blueprint("material_templates", __name__)


@bp.post("/material-templates")
def create():
    require_role("CatalogManager")
    record = catalog.create_material_template(request.get_json(silent=True))
    return success(serialize_material_template(record), 201)


@bp.post("/material-templates/<template_id>/publish")
def publish(template_id):
    require_role("CatalogManager")
    record = catalog.publish_material_template(template_id,
                                               request.get_json(silent=True) or {})
    return success(serialize_material_template(record), 200)


@bp.get("/material-templates")
def list_():
    require_role("PlatformAdmin", "CatalogManager", "Reviewer",
                 "LeadReviewer", "CertificateOfficer", "Applicant")
    limit, offset = parse_pagination(request.args)
    filters = {
        "status": request.args.get("status"),
        "material_type": request.args.get("material_type"),
    }
    rows, total = catalog.list_material_templates(filters, limit, offset)
    return success_list([serialize_material_template(r) for r in rows],
                        total, limit, offset)
