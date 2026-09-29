"""Renovation and turn projects: the budget ledger and the scope lock."""
from flask import Blueprint

import calc
import cascades
import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import F, authorize, body_json, must_find, validate

bp = Blueprint("projects", __name__)

PROJECT_READ = ["OperationsManager", "PortfolioAdmin", "RegionalDirector",
                "AcquisitionAnalyst", "LeasingAgent"]
SUMMARY_READ = ["OperationsManager", "PortfolioAdmin", "RegionalDirector", "AcquisitionAnalyst"]

LIVE_PROJECT_STATUSES = {"SCOPING", "IN_PROGRESS"}


@bp.post("/renovation-projects")
def create_project():
    data = validate(body_json(), [
        F("home_id", "string"),
        F("project_type", "string", enum=["ACQUISITION_RENOVATION", "TURN"]),
        F("approved_budget_cents", "money", minimum=1),
    ])
    authorize(["OperationsManager"])
    home = must_find("homes", data["home_id"], "ERR_HOME_NOT_FOUND")
    for existing in cascades.home_projects(home["id"]):
        if existing["status"] in LIVE_PROJECT_STATUSES:
            fail("ERR_DUPLICATE_PROJECT_FOR_HOME")
    if cascades.approved_case(home["id"]) is None:
        fail("ERR_CASE_NOT_APPROVED")
    row = store.base_row()
    row.update({
        "home_id": home["id"],
        "project_type": data["project_type"],
        "approved_budget_cents": data["approved_budget_cents"],
        "committed_cost_cents": 0,
        "budget_remaining_cents": data["approved_budget_cents"],
        "turn_started_on": "",
        "rent_ready_on": "",
        "turn_days": None,
        "overage_days": None,
        "gross_turn_cost_cents": None,
        "holdback_rate_bps": None,
        "vendor_holdback_cents": None,
        "net_turn_cost_cents": None,
        "status": "SCOPING",
    })
    store.insert("renovation_projects", row)
    return created(views.public(row))


@bp.get("/renovation-projects/<project_id>")
def read_project(project_id):
    authorize(PROJECT_READ)
    row = must_find("renovation_projects", project_id, "ERR_RENOVATION_PROJECT_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/renovation-projects")
def list_projects():
    authorize(PROJECT_READ)
    rows = views.filtered("renovation_projects", [
        ("home_id", "home_id", "string"),
        ("status", "status", "string"),
        ("project_type", "project_type", "string"),
    ])
    return paginate(rows, views.public)


@bp.post("/renovation-projects/<project_id>/budget")
def revise_budget(project_id):
    data = validate(body_json(), [F("approved_budget_cents", "money", minimum=1)])
    authorize(["OperationsManager", "RegionalDirector"])
    project = must_find("renovation_projects", project_id, "ERR_RENOVATION_PROJECT_NOT_FOUND")
    if int(data["approved_budget_cents"]) < int(project["committed_cost_cents"]):
        fail("ERR_BUDGET_BELOW_COMMITTED")
    project["approved_budget_cents"] = data["approved_budget_cents"]
    project["budget_remaining_cents"] = (int(data["approved_budget_cents"])
                                        - int(project["committed_cost_cents"]))
    store.touch(project)
    return ok(views.public(project))


@bp.post("/renovation-projects/<project_id>/lock-scope")
def lock_scope(project_id):
    data = validate(body_json(), [F("turn_started_on", "date")])
    authorize(["OperationsManager"])
    project = must_find("renovation_projects", project_id, "ERR_RENOVATION_PROJECT_NOT_FOUND")
    if project["status"] != "SCOPING":
        fail("ERR_INVALID_STATE")
    home = store.get("homes", project["home_id"])
    if home["asset_status"] != "ACQUIRED":
        fail("ERR_HOME_NOT_ACQUIRED")
    orders = [w for w in cascades.project_work_orders(project["id"]) if w["status"] != "VOIDED"]
    if not orders:
        fail("ERR_PROJECT_SCOPE_EMPTY")

    project["status"] = "IN_PROGRESS"
    project["turn_started_on"] = data["turn_started_on"]
    store.touch(project)
    home["asset_status"] = "RENOVATING"
    store.touch(home)
    cascades.recompute_posture(home)
    return ok(views.public(project))


@bp.get("/renovation-projects/<project_id>/benchmark-summary")
def benchmark_summary(project_id):
    authorize(SUMMARY_READ)
    project = must_find("renovation_projects", project_id, "ERR_RENOVATION_PROJECT_NOT_FOUND")
    home = store.get("homes", project["home_id"])
    market = cascades.market_of(home)
    orders = [w for w in cascades.project_work_orders(project["id"]) if w["status"] != "VOIDED"]
    lines = []
    per_line = []
    for order in orders:
        template = store.get("scope_templates", order["scope_template_id"])
        line = {"benchmark_unit_cost_cents": template["benchmark_unit_cost_cents"],
                "quantity": order["quantity"]}
        lines.append(line)
        per_line.append(calc.line_benchmark(line, market["cost_index_bps"]))
    return ok({
        "project_id": project["id"],
        "line_count": len(orders),
        "per_line_benchmark_cents": per_line,
        "scope_benchmark_total_cents": sum(per_line),
        "index_the_sum_total_cents": calc.index_the_sum_total(lines, market["cost_index_bps"]),
        "quoted_total_cents": sum(int(w["quoted_cost_cents"]) for w in orders),
        "committed_cost_cents": int(project["committed_cost_cents"]),
        "budget_remaining_cents": int(project["budget_remaining_cents"]),
    })
