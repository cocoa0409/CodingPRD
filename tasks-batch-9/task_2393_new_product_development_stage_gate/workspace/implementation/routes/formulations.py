"""Formulation revisions and the depth-four supersede cascade (PRD §3.7)."""

from flask import Blueprint

import calc
import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("formulations", __name__)


@bp.post("/innovation-projects/<project_id>/formulations")
def create_formulation(project_id):
    M.authenticate("RnDLead")
    project = common.project(project_id)
    data = V.body()
    expected_version = V.int_field(data, "expected_project_version")
    spec_summary = V.string_field(data, "spec_summary", max_len=2000)
    allergen_regime = V.enum_field(data, "allergen_regime", V.ALLERGEN_REGIMES)
    target_shelf_life = V.int_field(data, "target_shelf_life_days", minimum=1)
    unit_cost = V.number_field(data, "unit_cost_usd", minimum=0, places=4)

    if project["dev_status"] not in ("IDEA", "SCREENED", "PILOT_QUALIFIED",
                                    "LAUNCH_READY"):
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "dev_status %s does not admit a formulation revision."
               % project["dev_status"])
    if expected_version != project["version"]:
        E.fail(E.ERR_PROJECT_VERSION_CONFLICT,
               "expected_project_version %s does not match stored version %s."
               % (expected_version, project["version"]))

    previous = core.current_formulation(project["id"])
    revision = len(core.project_formulations(project["id"])) + 1

    row = core.new_row(db.formulations, {
        "project_id": project["id"],
        "revision": revision,
        "spec_summary": spec_summary,
        "allergen_regime": allergen_regime,
        "target_shelf_life_days": target_shelf_life,
        "unit_cost_usd": unit_cost,
        "status": "DRAFT",
        "best_pilot_yield_pct": calc.money(0),
    })

    if previous is not None:
        core.supersede_cascade(project, previous)

    return R.object_response(row, 201)


@bp.get("/innovation-projects/<project_id>/formulations")
def list_formulations(project_id):
    M.reader()
    project = common.project(project_id)
    rows = core.project_formulations(project["id"])
    rows = M.apply_filters(rows, {"status": "status"})
    rows = M.order(rows, [(M.by("revision"), False)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/formulations/<formulation_id>")
def read_formulation(formulation_id):
    M.reader()
    return R.object_response(common.formulation(formulation_id))
