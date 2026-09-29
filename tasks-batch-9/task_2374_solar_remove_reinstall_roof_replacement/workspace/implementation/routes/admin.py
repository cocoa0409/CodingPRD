"""Test-driving capabilities: the logical clock and the ledger perturbation."""

import services
from flask import Blueprint
from db import db
from middleware import endpoint
from response import iso, ok, ok_row
from routes.helpers import get_project, resolve_fk
from validation import datetime_field, get_body, int_field, str_field

bp = Blueprint("admin", __name__)


@bp.route("/reroof/_clock/set_current_utc", methods=["POST"])
@endpoint("ProjectCoordinator")
def set_clock():
    body = get_body()
    to_iso8601 = datetime_field(body, "to_iso8601", required=True)
    db.clock = to_iso8601
    return ok({"current_utc": iso(db.clock)})


@bp.route("/reroof/_ledger/perturb", methods=["POST"])
@endpoint("ProjectCoordinator")
def perturb_ledger():
    body = get_body()
    project = resolve_fk(body, "project_id", get_project)
    str_field(body, "project_id", required=True)
    released_delta_cents = int_field(body, "released_delta_cents", required=True)

    snapshot = services.project_snapshot(project)
    project["credit_released_cents"] += released_delta_cents
    services.commit_project(project, snapshot, force=True)
    return ok_row(project)
