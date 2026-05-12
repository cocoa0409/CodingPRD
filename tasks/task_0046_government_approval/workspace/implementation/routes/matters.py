"""Matter and MatterVersion routes."""

from flask import Blueprint, request

from middleware import require_role
from response import parse_pagination, success, success_list
from services import catalog
from services.serializers import serialize_matter, serialize_matter_version

bp = Blueprint("matters", __name__)


@bp.post("/matters")
def create_matter():
    require_role("CatalogManager")
    record = catalog.create_matter(request.get_json(silent=True))
    return success(serialize_matter(record), 201)


@bp.get("/matters")
def list_matters():
    require_role("PlatformAdmin", "CatalogManager", "Reviewer",
                 "LeadReviewer", "CertificateOfficer", "Applicant")
    limit, offset = parse_pagination(request.args)
    filters = {
        "theme": request.args.get("theme"),
        "owning_department_id": request.args.get("owning_department_id"),
        "status": request.args.get("status"),
    }
    rows, total = catalog.list_matters(filters, limit, offset)
    return success_list([serialize_matter(r) for r in rows], total, limit, offset)


@bp.get("/matters/<matter_id>")
def get_matter(matter_id):
    require_role("PlatformAdmin", "CatalogManager", "Reviewer",
                 "LeadReviewer", "CertificateOfficer", "Applicant")
    record = catalog.get_matter(matter_id)
    return success(serialize_matter(record), 200)


@bp.post("/matters/<matter_id>/versions")
def create_version(matter_id):
    require_role("CatalogManager")
    record = catalog.create_matter_version(matter_id, request.get_json(silent=True))
    return success(serialize_matter_version(record), 201)


@bp.get("/matters/<matter_id>/versions/<version_id>")
def get_version(matter_id, version_id):
    require_role("PlatformAdmin", "CatalogManager", "Reviewer",
                 "LeadReviewer", "CertificateOfficer", "Applicant")
    record = catalog.get_matter_version(matter_id, version_id)
    return success(serialize_matter_version(record), 200)


@bp.post("/matters/<matter_id>/versions/<version_id>/publish")
def publish_version(matter_id, version_id):
    require_role("CatalogManager")
    record = catalog.publish_matter_version(matter_id, version_id,
                                            request.get_json(silent=True) or {})
    return success(serialize_matter_version(record), 200)


@bp.post("/matters/<matter_id>/versions/<version_id>/retire")
def retire_version(matter_id, version_id):
    require_role("CatalogManager")
    record = catalog.retire_matter_version(matter_id, version_id,
                                           request.get_json(silent=True) or {})
    return success(serialize_matter_version(record), 200)
