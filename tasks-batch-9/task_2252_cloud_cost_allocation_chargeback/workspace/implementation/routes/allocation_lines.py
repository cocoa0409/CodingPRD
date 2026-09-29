"""Read-only allocation line discovery (PRD 3.5)."""
from flask import Blueprint

from db import db
from middleware import authorize
from routes.common import lookup, serve, serve_list

bp = Blueprint("allocation_lines", __name__)

READERS = ("FinOpsAnalyst", "FinOpsController", "PlatformAdmin", "BusinessUnitOwner")


@bp.route("/finops/allocation-lines", methods=["GET"])
@authorize(*READERS)
def list_lines():
    return serve_list(
        db.allocation_lines.values(),
        {
            "allocation_run_id": "allocation_run_id",
            "business_unit_id": "business_unit_id",
            "shared_cost_pool_id": "shared_cost_pool_id",
            "line_kind": "line_kind",
        },
    )


@bp.route("/finops/allocation-lines/<line_id>", methods=["GET"])
@authorize(*READERS)
def get_line(line_id):
    return serve(lookup("allocation_lines", line_id))
