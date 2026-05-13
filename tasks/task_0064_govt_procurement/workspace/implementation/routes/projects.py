"""Project + Tender Document routes."""

from flask import Blueprint, request

from common import get_json_body, get_pagination, slice_page
from middleware import require_roles
from response import paginated, success
from services import project as svc


bp = Blueprint("projects", __name__, url_prefix="/procurement")


@bp.post("/projects")
@require_roles("ProcurementOfficer")
def create_project():
    body = get_json_body()
    p = svc.create_project(body)
    return success(p, 201)


@bp.get("/projects/<pid>")
@require_roles("ProcurementOfficer", "Regulator", "Supplier", "EvaluationExpert")
def get_project(pid):
    return success(svc.get_project_or_404(pid), 200)


@bp.post("/projects/<pid>/tender-document")
@require_roles("ProcurementOfficer")
def create_tender(pid):
    body = get_json_body()
    doc = svc.create_tender_document(pid, body)
    return success(doc, 201)


@bp.post("/tender-documents/<did>/publish")
@require_roles("ProcurementOfficer")
def publish_tender(did):
    return success(svc.publish_tender_document(did), 200)


@bp.post("/tender-documents/<did>/clarify")
@require_roles("ProcurementOfficer")
def clarify_tender(did):
    body = get_json_body()
    return success(svc.clarify_tender_document(did, body), 200)


@bp.post("/tender-documents/<did>/finalize-clarification")
@require_roles("ProcurementOfficer")
def finalize_clarification(did):
    return success(svc.finalize_clarification(did), 200)


@bp.post("/tender-documents/<did>/begin-amendment")
@require_roles("ProcurementOfficer")
def tender_begin_amend(did):
    return success(svc.begin_tender_amendment(did), 200)


@bp.post("/projects/<pid>/open-bidding")
@require_roles("ProcurementOfficer")
def open_bidding(pid):
    return success(svc.open_bidding(pid), 200)


@bp.post("/projects/<pid>/close-bidding")
@require_roles("ProcurementOfficer")
def close_bidding(pid):
    return success(svc.close_bidding(pid), 200)


@bp.post("/projects/<pid>/cancel")
@require_roles("ProcurementOfficer")
def cancel_project(pid):
    return success(svc.cancel_project(pid), 200)


@bp.post("/projects/<pid>/prescreen-results")
@require_roles("ProcurementOfficer")
def prescreen_results(pid):
    return success(svc.prescreen_results(pid), 200)
