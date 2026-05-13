from flask import Blueprint, request

from clock import clock
from errors import err
from middleware import require_roles
from response import success
from services.assignments import expire_pending_assignments
from services.common import iso_format
from services.project_state import re_evaluate_project_state, re_evaluate_assignment_completion

bp = Blueprint("ops", __name__)


@bp.post("/_clock/advance")
@require_roles("ProjectManager")
def clock_advance():
    body = request.get_json(silent=True) or {}
    seconds = body.get("seconds")
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
        raise err("ERR_VALIDATION_FAILED", "seconds must be a positive integer.")
    new_now = clock.advance(seconds)
    # Auto-sweep
    expire_pending_assignments()
    return success({"now": iso_format(new_now)})


@bp.post("/_sweep/run")
@require_roles("ProjectManager")
def sweep_run():
    from db import store
    count = expire_pending_assignments()
    # Re-evaluate compound project states & assignment completion
    for project_id in list(store.projects.keys()):
        re_evaluate_project_state(project_id)
    for assignment_id in list(store.assignments.keys()):
        re_evaluate_assignment_completion(assignment_id)
    return success({"swept_count": count})
