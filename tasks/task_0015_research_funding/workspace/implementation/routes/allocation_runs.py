"""Indirect cost allocation runs."""

from flask import Blueprint

from common import get_json_body, require_field
from middleware import require_roles
from response import success
from services.indirect_cost import (
    get_run_or_404,
    run_allocation,
    serialize_allocation,
)


bp = Blueprint("allocation_runs", __name__)


@bp.route("/allocation-runs", methods=["POST"])
@require_roles("FinanceOfficer")
def post_run():
    body = get_json_body()
    allocation_base = require_field(body, "allocation_base", str)
    project_id = body.get("project_id")
    run_id, allocations = run_allocation(allocation_base, project_id=project_id)
    return success([serialize_allocation(a) for a in allocations], 201)


@bp.route("/allocation-runs/<run_id>", methods=["GET"])
@require_roles("Any")
def get_run(run_id):
    allocations = get_run_or_404(run_id)
    return success([serialize_allocation(a) for a in allocations], 200)
