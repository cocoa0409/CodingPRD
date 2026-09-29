"""Immutable hydrant flow test records (PRD 3.4)."""
from flask import Blueprint

import db
import guards
import helpers
import response
import validate
from middleware import ALL_ROLES, authenticate
from utils import _dec, fmt_dt

bp = Blueprint("flow_tests", __name__)


@bp.post("/flow-tests")
def create_flow_test():
    actor = authenticate(["DesignEngineer", "Contractor"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    guards.require_lead_engineer(actor, project)
    row = {
        "project_id": validate.req_str(data, "project_id"),
        "hydrant_tag": validate.req_str(data, "hydrant_tag"),
        "static_psi": validate.req_num(data, "static_psi", gt=0),
        "residual_psi": validate.req_num(data, "residual_psi", gt=0),
        "flow_gpm": validate.req_num(data, "flow_gpm", gt=0),
    }
    if _dec(row["residual_psi"]) >= _dec(row["static_psi"]):
        validate._bad("Field 'residual_psi' must be strictly below 'static_psi'.")
    row["tested_at"] = fmt_dt(validate.req_dt(data, "tested_at"))
    db.stamp_create(row, common_fields=False)
    db.flow_tests[row["id"]] = row
    return response.created(response.public(row))


@bp.get("/projects/<project_id>/flow-tests")
def list_project_flow_tests(project_id):
    authenticate(ALL_ROLES)
    guards.must("project", project_id)
    rows = [t for t in db.flow_tests.values() if t["project_id"] == project_id]
    return helpers.list_response(rows)
