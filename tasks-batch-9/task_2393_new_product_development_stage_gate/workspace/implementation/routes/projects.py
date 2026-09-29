"""Idea intake, gate-1 screening, concept testing and the readiness read."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("projects", __name__)


# ---------------------------------------------------------------------------
# intake and reads
# ---------------------------------------------------------------------------
@bp.post("/innovation-projects")
def create_project():
    user_id = M.authenticate("InnovationLead")
    data = V.body()
    name = V.string_field(data, "name", min_len=1, max_len=120)
    brand = V.string_field(data, "brand")
    category = V.enum_field(data, "category", V.CATEGORIES)
    project_type = V.enum_field(data, "project_type", V.PROJECT_TYPES)
    strategic_fit = V.number_field(data, "strategic_fit_score", minimum=0, maximum=10)
    consumer_need = V.number_field(data, "consumer_need_score", minimum=0, maximum=10)
    target_margin = V.number_field(data, "target_gross_margin_pct",
                                   minimum=0, maximum=100)
    attractiveness = V.number_field(data, "category_attractiveness_score",
                                    minimum=0, maximum=10)
    budget_cap = V.number_field(data, "development_budget_cap_usd", minimum=0)

    row = core.new_row(db.projects, {
        "name": name,
        "brand": brand,
        "category": category,
        "project_type": project_type,
        "owner_user_id": user_id,
        "strategic_fit_score": strategic_fit,
        "consumer_need_score": consumer_need,
        "target_gross_margin_pct": target_margin,
        "category_attractiveness_score": attractiveness,
        "development_budget_cap_usd": budget_cap,
        "development_budget_committed_usd": calc.money(0),
        "screening_score": None,
        "screening_decision": "PENDING",
        "dev_status": "IDEA",
        "commercial_status": "NOT_STARTED",
        "next_gate_number": 2,
        "recycle_count": 0,
        "open_gate_conditions": False,
        "launch_date": None,
        "shelf_reset_window_id": None,
        "launch_readiness_pct": calc.money(0),
        "authorized_acv_pct": calc.money(0),
        "post_launch_decision": None,
    })
    row["_dt_launch_date"] = None
    return R.object_response(row, 201)


@bp.get("/innovation-projects")
def list_projects():
    M.reader()
    rows = M.apply_filters(db.rows(db.projects), {
        "dev_status": "dev_status",
        "commercial_status": "commercial_status",
        "category": "category",
        "shelf_reset_window_id": "shelf_reset_window_id",
    })
    rows = M.order(rows)
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/innovation-projects/<project_id>")
def read_project(project_id):
    M.reader()
    return R.object_response(common.project(project_id))


@bp.get("/innovation-projects/<project_id>/launch-readiness")
def read_launch_readiness(project_id):
    M.reader()
    project = common.project(project_id)
    pct, blocking = core.readiness_picture(project)
    earliest = clock.current_dt() + timedelta(days=calc.LOCK_LEAD_DAYS)
    return R.object_response({
        "launch_readiness_pct": pct,
        "blocking_deliverable_types": blocking,
        "authorized_acv_pct": project["authorized_acv_pct"],
        "launch_date": project["launch_date"],
        "earliest_lockable_date": clock.format_dt(earliest),
    })


# ---------------------------------------------------------------------------
# gate 1: idea screening
# ---------------------------------------------------------------------------
@bp.post("/innovation-projects/<project_id>/screen")
def screen_project(project_id):
    M.authenticate("GateChair")
    project = common.project(project_id)
    if project["dev_status"] != "IDEA":
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "Screening admits dev_status IDEA only.")
    data = V.body()
    V.string_field(data, "screening_notes", required=False)

    score = calc.screening_score(
        project["project_type"],
        project["strategic_fit_score"],
        project["consumer_need_score"],
        project["target_gross_margin_pct"],
        project["category_attractiveness_score"],
    )

    if score >= calc.SCREENING_PASS_FLOOR:
        gate = core.gate_for(project["category"], 2)
        if gate is None:
            E.fail(E.ERR_STAGE_GATE_NOT_FOUND,
                   "No gate 2 is registered for category %s." % project["category"])
        core.apply(project, {
            "screening_score": score,
            "screening_decision": "PASSED",
            "dev_status": "SCREENED",
            "next_gate_number": 2,
        })
        core.create_checklist(project, gate)
    else:
        core.apply(project, {
            "screening_score": score,
            "screening_decision": "REJECTED",
            "dev_status": "KILLED",
        })

    return R.object_response(project, 200)


# ---------------------------------------------------------------------------
# concept tests
# ---------------------------------------------------------------------------
@bp.post("/innovation-projects/<project_id>/concept-tests")
def create_concept_test(project_id):
    M.authenticate("InnovationLead")
    project = common.project(project_id)
    data = V.body()
    test_type = V.enum_field(data, "test_type", V.TEST_TYPES)
    sample_size = V.int_field(data, "sample_size", minimum=1)
    intent = V.number_field(data, "purchase_intent_top2_pct", minimum=0, maximum=100)
    uniqueness = V.number_field(data, "uniqueness_pct", minimum=0, maximum=100)
    fielded_raw, fielded_dt = V.datetime_field(data, "fielded_at")

    row = core.new_row(db.concept_tests, {
        "project_id": project["id"],
        "test_type": test_type,
        "sample_size": sample_size,
        "purchase_intent_top2_pct": intent,
        "uniqueness_pct": uniqueness,
        "fielded_at": fielded_raw,
        "concept_score": calc.concept_score(intent, uniqueness, sample_size),
        "is_authoritative": True,
    })
    row["_dt_fielded_at"] = fielded_dt

    core.refresh_concept_authority(project["id"])
    core.auto_approve(project["id"], "CONSUMER_CONCEPT_TEST")
    return R.object_response(row, 201)


@bp.get("/innovation-projects/<project_id>/concept-tests")
def list_concept_tests(project_id):
    M.reader()
    project = common.project(project_id)
    rows = db.children(db.concept_tests, "project_id", project["id"])
    rows = M.order(rows, [(lambda r: r["_dt_fielded_at"], True)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)
