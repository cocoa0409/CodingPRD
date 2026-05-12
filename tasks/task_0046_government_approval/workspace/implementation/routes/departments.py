"""Department routes."""

from flask import Blueprint, request

from middleware import require_role
from response import parse_pagination, success, success_list
from services import catalog
from services.serializers import serialize_department

bp = Blueprint("departments", __name__)


@bp.post("/departments")
def create():
    require_role("PlatformAdmin")
    record = catalog.create_department(request.get_json(silent=True))
    return success(serialize_department(record), 201)


@bp.get("/departments")
def list_():
    require_role("PlatformAdmin", "CatalogManager", "Reviewer",
                 "LeadReviewer", "CertificateOfficer", "Applicant")
    limit, offset = parse_pagination(request.args)
    filters = {
        "status": request.args.get("status"),
        "parent_department_id": request.args.get("parent_department_id"),
    }
    rows, total = catalog.list_departments(filters, limit, offset)
    return success_list([serialize_department(r) for r in rows], total, limit, offset)
