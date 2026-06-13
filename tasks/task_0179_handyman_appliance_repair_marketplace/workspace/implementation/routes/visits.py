"""Standalone WorkVisit reads (PRD §4)."""
from flask import Blueprint, request

from db import store
from middleware import require_role
from models import serialize, WORK_VISIT_FIELDS
from response import object_response, array_response
from services.lookup import get_or_404, paginate, sorted_by_creation

bp = Blueprint("visits", __name__)


@bp.get("/work-visits/<vid>")
@require_role({"PlatformAdmin", "Pro", "Dispatcher", "Customer"})
def get_visit(vid):
    visit = get_or_404(store.work_visits, vid)
    return object_response(serialize(visit, WORK_VISIT_FIELDS))


@bp.get("/work-visits")
@require_role({"PlatformAdmin", "Pro", "Dispatcher", "Customer"})
def list_visits():
    items = list(store.work_visits.values())
    job_id = request.args.get("job_id")
    dw_id = request.args.get("dispatch_window_id")
    if job_id is not None:
        items = [v for v in items if v["job_id"] == job_id]
    if dw_id is not None:
        items = [v for v in items if v["dispatch_window_id"] == dw_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(v, WORK_VISIT_FIELDS) for v in page],
                          limit, offset, total)
