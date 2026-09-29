"""Financing scenarios and homeowner change orders."""
from decimal import Decimal

from flask import Blueprint, g, request

from common import (
    ALL_ROLES, DB, authorize, body_json, fail, get_change_order, get_project, get_scenario,
    listing, new_row, ok, ser, touch, v_array, v_enum, v_int, v_str, D,
)
import calc
import services

bp = Blueprint("finance", __name__)

PRODUCT_TYPES = ("HELOC", "CASH_OUT_REFI", "RENOVATION_LOAN", "CONSTRUCTION_LOAN")
APPRAISAL_APPROACHES = ("SALES_COMPARISON", "INCOME_CAPITALIZATION")


# ---------------------------------------------------------------------------
# Financing scenarios
# ---------------------------------------------------------------------------
@bp.post("/adu-projects/<pid>/financing-scenarios")
@authorize("FinanceAdvisor")
def create_scenario(pid):
    project = get_project(pid)
    body = body_json()
    expected = v_int(body, "expected_adu_project_version")
    product_type = v_enum(body, "product_type", PRODUCT_TYPES)
    appraisal_approach = v_enum(body, "appraisal_approach", APPRAISAL_APPROACHES)
    comparable_adjustment_cents = v_int(body, "comparable_adjustment_cents", minimum=0)
    projected_monthly_rent_cents = v_int(body, "projected_monthly_rent_cents", minimum=0)

    if expected != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION", "Project version has moved on.")

    for existing in services.project_scenarios(project["id"]):
        if existing["status"] == "ACTIVE":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    prop = DB.properties[project["property_id"]]
    row = new_row()
    row.update(
        adu_project_id=project["id"],
        product_type=product_type,
        appraisal_approach=appraisal_approach,
        comparable_adjustment_cents=comparable_adjustment_cents,
        projected_monthly_rent_cents=projected_monthly_rent_cents,
        status="ACTIVE",
    )
    row.update(calc.financing_capacity(row, project, prop))
    DB.scenarios[row["id"]] = row

    if project["financing_state"] == "UNFUNDED":
        project["financing_state"] = "PRE_QUALIFIED"
    touch(project)
    return ok(ser(row), 201)


@bp.get("/adu-projects/<pid>/financing-scenarios")
@authorize("PlatformAdmin", "DesignLead", "ProjectManager", "FinanceAdvisor", "Homeowner")
def list_scenarios(pid):
    get_project(pid)
    rows = [s for s in DB.scenarios.values() if s["adu_project_id"] == pid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    approach = request.args.get("appraisal_approach")
    if approach:
        rows = [r for r in rows if r["appraisal_approach"] == approach]
    return listing(rows)


@bp.get("/financing-scenarios/<sid>")
@authorize("PlatformAdmin", "ProjectManager", "FinanceAdvisor", "Homeowner")
def read_scenario(sid):
    return ok(ser(get_scenario(sid)))


@bp.post("/financing-scenarios/<sid>/commit")
@authorize("FinanceAdvisor")
def commit_scenario(sid):
    scenario = get_scenario(sid)
    if scenario["status"] != "ACTIVE":
        fail("ERR_SCENARIO_STATE_INVALID", "Scenario is not ACTIVE.")
    if scenario["funding_gap_cents"] != 0:
        fail("ERR_FUNDING_GAP_OPEN", "Scenario carries an open funding gap.")

    project = DB.projects[scenario["adu_project_id"]]
    for other in services.project_scenarios(project["id"]):
        if other["id"] != scenario["id"] and other["status"] == "COMMITTED":
            other["status"] = "SUPERSEDED"
            touch(other)

    scenario["status"] = "COMMITTED"
    touch(scenario)

    project["financing_state"] = "COMMITTED"
    touch(project)
    return ok(ser(scenario))


# ---------------------------------------------------------------------------
# Change orders
# ---------------------------------------------------------------------------
@bp.post("/adu-projects/<pid>/change-orders")
@authorize("Homeowner")
def create_change_order(pid):
    project = get_project(pid)
    body = body_json()

    raw_supersedes = body.get("supersedes_change_order_id")
    if isinstance(raw_supersedes, str):
        get_change_order(raw_supersedes)

    if g.user_id != project["property_id"]:
        fail("ERR_NOT_PROJECT_OWNER", "Homeowner does not own this project.")

    expected = v_int(body, "expected_adu_project_version")
    title = v_str(body, "title")
    scope_items = v_array(body, "scope_items", item_type=str)
    cost_delta_cents = v_int(body, "cost_delta_cents")
    schedule_delta_days = v_int(body, "schedule_delta_days", minimum=-30, maximum=120)
    supersedes = v_str(body, "supersedes_change_order_id", required=False, default=None)
    if supersedes is not None:
        get_change_order(supersedes)

    if expected != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION", "Project version has moved on.")

    if len(scope_items) == 0 and cost_delta_cents == 0 and schedule_delta_days == 0:
        fail("ERR_EMPTY_CHANGE_ORDER", "A change order must carry substance.")

    row = new_row()
    row.update(
        adu_project_id=project["id"],
        supersedes_change_order_id=supersedes,
        title=title,
        scope_items=scope_items,
        cost_delta_cents=cost_delta_cents,
        schedule_delta_days=schedule_delta_days,
        status="DRAFT",
        builder_fee_cents=0,
        cumulative_change_pct_before=0,
        cumulative_change_pct_after=0,
        authored_by_user_id=g.user_id,
        decided_by_user_id=None,
    )
    DB.change_orders[row["id"]] = row
    touch(project)
    return ok(ser(row), 201)


@bp.get("/change-orders")
@authorize("PlatformAdmin", "DesignLead", "ProjectManager", "PlanChecker",
           "FinanceAdvisor", "Homeowner")
def list_change_orders():
    rows = list(DB.change_orders.values())
    pid = request.args.get("adu_project_id")
    if pid:
        rows = [r for r in rows if r["adu_project_id"] == pid]
    sup = request.args.get("supersedes_change_order_id")
    if sup:
        rows = [r for r in rows if r["supersedes_change_order_id"] == sup]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


@bp.get("/change-orders/<cid>")
@authorize("PlatformAdmin", "DesignLead", "ProjectManager", "PlanChecker",
           "FinanceAdvisor", "Homeowner")
def read_change_order(cid):
    return ok(ser(get_change_order(cid)))


@bp.post("/change-orders/<cid>/submit")
@authorize("Homeowner")
def submit_change_order(cid):
    co = get_change_order(cid)
    project = DB.projects[co["adu_project_id"]]
    if g.user_id != project["property_id"]:
        fail("ERR_NOT_PROJECT_OWNER", "Homeowner does not own this project.")

    if co["status"] == "DRAFT":
        co["status"] = "SUBMITTED"
    elif co["status"] == "REVISION_REQUESTED":
        co["status"] = "DRAFT"
        co["decided_by_user_id"] = None
    else:
        fail("ERR_CHANGE_ORDER_STATE_INVALID", "Change order cannot be submitted from %s."
             % co["status"])
    touch(co)
    return ok(ser(co))


@bp.post("/change-orders/<cid>/decide")
@authorize("ProjectManager")
def decide_change_order(cid):
    co = get_change_order(cid)
    body = body_json()
    decision = v_enum(body, "decision", ("APPROVE", "REJECT", "REQUEST_REVISION"))

    if co["status"] != "SUBMITTED":
        fail("ERR_CHANGE_ORDER_STATE_INVALID", "Change order is not SUBMITTED.")

    project = DB.projects[co["adu_project_id"]]

    if decision == "REQUEST_REVISION":
        co["status"] = "REVISION_REQUESTED"
        co["decided_by_user_id"] = g.user_id
        touch(co)
        return ok(ser(co))

    if decision == "REJECT":
        co["status"] = "REJECTED"
        co["decided_by_user_id"] = g.user_id
        touch(co)
        return ok(ser(co))

    # APPROVE
    if project["status"] not in ("PERMITTED", "UNDER_CONSTRUCTION"):
        fail("ERR_PROJECT_PHASE_INVALID", "Change orders may only be approved on a permitted "
                                          "or under-construction project.")

    builder_fee, pct_before, pct_after, new_price = calc.change_order_reconciliation(project, co)
    if D(pct_after) > calc.CHANGE_ORDER_CAP_PCT:
        fail("ERR_CHANGE_CAP_EXCEEDED", "Cumulative change would exceed the 25.00%% cap.")

    count_before = project["approved_change_order_count"]

    co["status"] = "APPROVED"
    co["builder_fee_cents"] = builder_fee
    co["cumulative_change_pct_before"] = pct_before
    co["cumulative_change_pct_after"] = pct_after
    co["decided_by_user_id"] = g.user_id
    touch(co)

    project["contract_price_current_cents"] = new_price
    project["approved_change_days"] = project["approved_change_days"] + co["schedule_delta_days"]
    project["approved_change_order_count"] = count_before + 1
    touch(project)

    services.reprice_committed_scenario(project)

    if count_before == 0 and co["cost_delta_cents"] != 0:
        services.revert_separate_utility_decisions(project)

    return ok(ser(co))


@bp.post("/change-orders/<cid>/void")
@authorize("ProjectManager")
def void_change_order(cid):
    co = get_change_order(cid)
    if co["status"] != "APPROVED":
        fail("ERR_CHANGE_ORDER_STATE_INVALID", "Only an APPROVED change order may be voided.")

    project = DB.projects[co["adu_project_id"]]
    if project["status"] == "FINALED":
        fail("ERR_PROJECT_PHASE_INVALID", "Project is already FINALED.")

    schedule_delta = co["schedule_delta_days"]
    co["status"] = "VOIDED"
    co["builder_fee_cents"] = 0
    co["cumulative_change_pct_before"] = 0
    co["cumulative_change_pct_after"] = 0
    touch(co)

    project["contract_price_current_cents"] = calc.recompute_contract_price(project)
    project["approved_change_days"] = project["approved_change_days"] - schedule_delta
    project["approved_change_order_count"] = project["approved_change_order_count"] - 1
    touch(project)

    services.reprice_committed_scenario(project)
    return ok(ser(co))
