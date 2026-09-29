"""Substantial-improvement projects, working-capital plans and penalties."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import derive
from core import (
    API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN,
    ZERO2, ZERO4, authenticate, fail, get, insert, month_key, must_get, must_ref,
    now_logical, pagination, q2, rows, touch,
)
from schema import F, parse_body
from support import guard_state, listing, manager_scope, one

bp = Blueprint("project_routes", __name__, url_prefix=API_PREFIX)

AGGREGATION_METHODS = ("ASSET_BY_ASSET", "AGGREGATED_GROUP")
EXPENDITURE_KINDS = ("CAPITALIZED_IMPROVEMENT", "OPERATING_WORKING_CAPITAL",
                     "LAND_ACQUISITION")
CURE_BASES = ("REASONABLE_CAUSE", "TREATED_AS_FAILURE")
DECISIONS = ("APPROVE", "DENY")
ONE_DAY = timedelta(days=1)


def _fund_of_asset(asset):
    return get("funds", asset["fund_id"])


def _fund_of_business(business):
    return get("funds", business["fund_id"])


# ---------------------------------------------------------------------------
# Improvement projects
# ---------------------------------------------------------------------------

@bp.post("/improvement-projects")
def create_project():
    authenticate((ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("fund_asset_id", "string", non_blank=True),
        F("window_start", "datetime"),
        F("aggregation_method", "enum", enum=AGGREGATION_METHODS),
        F("group_key", "string", required=False, min_len=1, max_len=40,
          non_blank=True),
    ])
    asset = must_ref("fund_assets", body["fund_asset_id"])
    fund = _fund_of_asset(asset)
    if fund is not None:
        manager_scope(fund)
    # Priority 14 still bars a disposed asset; the HELD precondition of the
    # HELD -> IMPROVING transition governs the side effect only, because
    # priority 22 explicitly measures the new window against sibling projects
    # that are still OPEN -- which is only reachable while the asset is
    # already IMPROVING.
    if asset["status"] == "DISPOSED":
        fail("ERR_ALREADY_TERMINAL",
             "Resource is already in terminal state 'DISPOSED'")
    if asset["original_use_in_zone"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Property whose original use in the zone began with the fund needs"
             " no improvement")
    window_start = body["window_start"]
    window_end = calc.improvement_window_end(window_start)
    closed_end = window_end - ONE_DAY
    for other in rows("improvement_projects", lambda p: (
            p["fund_asset_id"] == asset["id"]
            and p["status"] in ("OPEN", "SATISFIED"))):
        other_closed_end = other["window_end"] - ONE_DAY
        if window_start <= other_closed_end and other["window_start"] <= closed_end:
            fail("ERR_IMPROVEMENT_WINDOW_OVERLAP",
                 "The closed improvement window collides with project '%s'"
                 % other["id"])
    group_key = body["group_key"]
    supplied = "group_key" in body["_present"]
    if body["aggregation_method"] == "AGGREGATED_GROUP":
        if not supplied:
            fail("ERR_AGGREGATION_GROUP_INVALID",
                 "group_key is required under AGGREGATED_GROUP")
        for sibling in rows("improvement_projects",
                            lambda p: p["group_key"] == group_key):
            other_asset = get("fund_assets", sibling["fund_asset_id"])
            if other_asset is not None and other_asset["fund_id"] != asset["fund_id"]:
                fail("ERR_AGGREGATION_GROUP_INVALID",
                     "group_key '%s' already spans another fund" % group_key)
    elif supplied:
        fail("ERR_AGGREGATION_GROUP_INVALID",
             "group_key is forbidden under ASSET_BY_ASSET")
    project = insert("improvement_projects", {
        "fund_asset_id": asset["id"],
        "window_start": window_start,
        "window_end": window_end,
        "aggregation_method": body["aggregation_method"],
        "group_key": group_key,
        "basis_at_acquisition": asset["unadjusted_cost_basis"],
        "qualified_additions_total": ZERO2,
        "improvement_ratio_pct": ZERO4,
        "status": "OPEN",
        "evaluated_at": None,
    })
    if asset["status"] == "HELD":
        derive.set_asset_qualification(asset, "IMPROVEMENT_PENDING", "IMPROVING")
    if fund is not None:
        derive.recompute_fund_aggregates(fund)
    return one(project, 201)


@bp.get("/improvement-projects/<project_id>")
def read_project(project_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    return one(must_get("improvement_projects", project_id))


@bp.get("/improvement-projects")
def list_projects():
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    return listing("improvement_projects",
                   [("fund_asset_id", "fund_asset_id"), ("status", "status"),
                    ("group_key", "group_key"),
                    ("aggregation_method", "aggregation_method")], page)


@bp.post("/improvement-projects/<project_id>/expenditures")
def create_project_expenditure(project_id):
    authenticate((ROLE_FUND_MANAGER,))
    body = parse_body([
        F("amount", "money", gt="0.00"),
        F("expenditure_kind", "enum", enum=EXPENDITURE_KINDS),
        F("expected_project_version", "integer"),
    ])
    project = must_get("improvement_projects", project_id)
    asset = get("fund_assets", project["fund_asset_id"])
    fund = _fund_of_asset(asset) if asset is not None else None
    if fund is not None:
        manager_scope(fund)
    guard_state(project["status"], ("OPEN",), ("SATISFIED", "LAPSED"))
    if body["expected_project_version"] != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION",
             "expected_project_version %s does not match current version %s"
             % (body["expected_project_version"], project["version"]))
    spend_date = now_logical()
    if not (project["window_start"] <= spend_date < project["window_end"]):
        fail("ERR_EXPENDITURE_OUTSIDE_WINDOW",
             "The logical clock is outside the project's improvement window")
    expenditure = insert("capital_expenditures", {
        "improvement_project_id": project["id"],
        "wcsh_plan_id": None,
        "amount": body["amount"],
        "expenditure_kind": body["expenditure_kind"],
        "spend_date": spend_date,
        "counts_toward_basis":
            body["expenditure_kind"] == "CAPITALIZED_IMPROVEMENT",
        "schedule_month_index": None,
    })
    touch(project)
    derive.refresh_project(project)
    if asset is not None:
        derive.recompute_asset_basis(asset)
    return one(expenditure, 201)


@bp.get("/improvement-projects/<project_id>/expenditures")
def list_project_expenditures(project_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("improvement_projects", project_id)
    return listing("capital_expenditures",
                   [("expenditure_kind", "expenditure_kind")], page,
                   extra=lambda r: r["improvement_project_id"] == project_id)


@bp.post("/improvement-projects/<project_id>/evaluate")
def evaluate_project(project_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER))
    parse_body([])
    project = must_get("improvement_projects", project_id)
    guard_state(project["status"], ("OPEN",), ("SATISFIED", "LAPSED"))
    derive.refresh_project(project)
    project["evaluated_at"] = now_logical()
    touch(project)
    outcome = calc.improvement_outcome(project["improvement_ratio_pct"],
                                       project["window_end"])
    asset = get("fund_assets", project["fund_asset_id"])
    if outcome == "SATISFIED" and asset is not None and asset["status"] == "IMPROVING":
        derive.project_satisfy(project)
    elif outcome == "LAPSED":
        derive.project_lapse(project)
    return one(project)


# ---------------------------------------------------------------------------
# Working-capital safe-harbor plans
# ---------------------------------------------------------------------------

def _plan_months(window_start, window_end):
    """Every calendar month the half-open window covers."""
    return range(month_key(window_start), month_key(window_end))


def _apply_run(plan, run):
    """Write the waterfall figures back onto the plan."""
    changed = False
    for field in ("spent_total", "unspent_amount", "overspill_amount",
                  "pacing_shortfall", "last_checkpoint_month_index"):
        if field in run and plan[field] != run[field]:
            plan[field] = run[field]
            changed = True
    if changed:
        touch(plan)
    return changed


@bp.post("/wcsh-plans")
def create_plan():
    authenticate((ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("qoz_business_id", "string", non_blank=True),
        F("window_start", "datetime"),
        F("covered_amount", "money", gt="0.00"),
        F("written_plan_reference", "string", min_len=1, max_len=80,
          non_blank=True),
        F("schedule_month_count", "integer", gte=1, lte=31),
        F("spend_schedule", "schedule"),
    ])
    schedule = body["spend_schedule"]
    indexes = [b["month_index"] for b in schedule]
    if len(set(indexes)) != len(indexes):
        fail("ERR_INVALID_REQUEST",
             "spend_schedule may not repeat a month_index")
    business = must_ref("qoz_businesses", body["qoz_business_id"])
    fund = _fund_of_business(business)
    if fund is not None:
        manager_scope(fund)
    covered = body["covered_amount"]
    planned_total = q2(sum((b["planned_amount"] for b in schedule), ZERO2))
    if planned_total != covered:
        fail("ERR_WCSH_SCHEDULE_MISMATCH",
             "spend_schedule planned amounts sum to %s, not %s"
             % (planned_total, covered))
    window_start = body["window_start"]
    window_end = calc.wcsh_window_end(window_start)
    cap = q2(business["total_asset_value"] * calc.WCSH_AGGREGATE_CAP_PCT)
    siblings = rows("wcsh_plans", lambda p: (
        p["qoz_business_id"] == business["id"]
        and p["status"] in ("DRAFT", "ACTIVE")))
    for month in _plan_months(window_start, window_end):
        total = covered
        for other in siblings:
            if month in _plan_months(other["window_start"], other["window_end"]):
                total = q2(total + other["covered_amount"])
        if total > cap:
            fail("ERR_WCSH_AGGREGATE_CAP_EXCEEDED",
                 "Covered amounts total %s in one month, above the cap of %s"
                 % (total, cap))
    complete = (len(schedule) == body["schedule_month_count"]
                and planned_total == covered)
    plan = insert("wcsh_plans", {
        "qoz_business_id": business["id"],
        "window_start": window_start,
        "window_end": window_end,
        "covered_amount": covered,
        "written_plan_reference": body["written_plan_reference"],
        "schedule_month_count": body["schedule_month_count"],
        "spend_schedule": schedule,
        "documentation_complete": complete,
        "spent_total": ZERO2,
        "unspent_amount": covered,
        "last_checkpoint_month_index": 0,
        "pacing_shortfall": ZERO2,
        "overspill_amount": ZERO2,
        "status": "DRAFT",
    })
    return one(plan, 201)


@bp.get("/wcsh-plans/<plan_id>")
def read_plan(plan_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    return one(must_get("wcsh_plans", plan_id))


@bp.get("/wcsh-plans")
def list_plans():
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    return listing("wcsh_plans", [("qoz_business_id", "qoz_business_id"),
                                  ("status", "status")], page)


@bp.post("/wcsh-plans/<plan_id>/activate")
def activate_plan(plan_id):
    authenticate((ROLE_FUND_MANAGER,))
    parse_body([])
    plan = must_get("wcsh_plans", plan_id)
    business = get("qoz_businesses", plan["qoz_business_id"])
    fund = _fund_of_business(business) if business is not None else None
    if fund is not None:
        manager_scope(fund)
    guard_state(plan["status"], ("DRAFT",), ("COMPLETED", "BLOWN"))
    clock = now_logical()
    if not (plan["window_start"] <= clock < plan["window_end"]):
        fail("ERR_WCSH_WINDOW_CLOSED",
             "The logical clock is outside the plan's 31-month window")
    if not plan["documentation_complete"]:
        fail("ERR_WCSH_PLAN_INCOMPLETE",
             "The written plan and spend schedule are not complete")
    plan["status"] = "ACTIVE"
    touch(plan)
    if business is not None:
        derive.recompute_business_nqfp(business)
    return one(plan)


@bp.post("/wcsh-plans/<plan_id>/expenditures")
def create_plan_expenditure(plan_id):
    authenticate((ROLE_FUND_MANAGER,))
    body = parse_body([
        F("amount", "money", gt="0.00"),
        F("expenditure_kind", "enum", enum=EXPENDITURE_KINDS),
    ])
    plan = must_get("wcsh_plans", plan_id)
    business = get("qoz_businesses", plan["qoz_business_id"])
    fund = _fund_of_business(business) if business is not None else None
    if fund is not None:
        manager_scope(fund)
    guard_state(plan["status"], ("ACTIVE",), ("COMPLETED", "BLOWN"))
    spend_date = now_logical()
    if not (plan["window_start"] <= spend_date < plan["window_end"]):
        fail("ERR_WCSH_WINDOW_CLOSED",
             "The logical clock is outside the plan's 31-month window")
    expenditure = insert("capital_expenditures", {
        "improvement_project_id": None,
        "wcsh_plan_id": plan["id"],
        "amount": body["amount"],
        "expenditure_kind": body["expenditure_kind"],
        "spend_date": spend_date,
        "counts_toward_basis":
            body["expenditure_kind"] == "CAPITALIZED_IMPROVEMENT",
        "schedule_month_index": None,
    })
    _apply_run(plan, calc.wcsh_waterfall(plan))
    if business is not None:
        derive.recompute_business_nqfp(business)
    return one(expenditure, 201)


@bp.get("/wcsh-plans/<plan_id>/expenditures")
def list_plan_expenditures(plan_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("wcsh_plans", plan_id)
    return listing("capital_expenditures",
                   [("expenditure_kind", "expenditure_kind")], page,
                   extra=lambda r: r["wcsh_plan_id"] == plan_id)


@bp.post("/wcsh-plans/<plan_id>/evaluate-checkpoint")
def evaluate_checkpoint(plan_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER))
    body = parse_body([F("checkpoint_month_index", "integer")])
    plan = must_get("wcsh_plans", plan_id)
    guard_state(plan["status"], ("ACTIVE",), ("COMPLETED", "BLOWN"))
    index = body["checkpoint_month_index"]
    if index < 1 or index > plan["schedule_month_count"]:
        fail("ERR_CHECKPOINT_INDEX_INVALID",
             "checkpoint_month_index must be in 1..%d"
             % plan["schedule_month_count"])
    if index < plan["last_checkpoint_month_index"]:
        fail("ERR_CHECKPOINT_INDEX_INVALID",
             "checkpoint_month_index may not walk back behind %d"
             % plan["last_checkpoint_month_index"])
    run = calc.wcsh_checkpoint(plan, index)
    outcome = run.pop("status")
    _apply_run(plan, run)
    business = get("qoz_businesses", plan["qoz_business_id"])
    fund = _fund_of_business(business) if business is not None else None
    if outcome == "BLOWN":
        derive.plan_blown_cascade(plan, business, fund)
    elif outcome == "COMPLETED":
        derive.plan_completed(plan, business)
    elif business is not None:
        derive.recompute_business_nqfp(business)
    return one(plan)


# ---------------------------------------------------------------------------
# Penalty assessments
# ---------------------------------------------------------------------------

@bp.get("/penalty-assessments/<assessment_id>")
def read_assessment(assessment_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    return one(must_get("penalty_assessments", assessment_id))


@bp.get("/penalty-assessments")
def list_assessments():
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    return listing("penalty_assessments", [("fund_id", "fund_id"),
                                           ("asset_test_id", "asset_test_id"),
                                           ("status", "status")], page)


@bp.post("/penalty-assessments/<assessment_id>/cure-requests")
def create_cure_request(assessment_id):
    authenticate((ROLE_FUND_MANAGER,))
    body = parse_body([
        F("cure_basis", "enum", enum=CURE_BASES),
        F("narrative_reference", "string", min_len=1, max_len=200,
          non_blank=True),
    ])
    assessment = must_get("penalty_assessments", assessment_id)
    fund = get("funds", assessment["fund_id"])
    if fund is not None:
        manager_scope(fund)
    guard_state(assessment["status"], ("ASSESSED",), ("CURED", "UPHELD"))
    if assessment["cure_attempt_count"] >= 2:
        fail("ERR_CURE_ATTEMPTS_EXHAUSTED",
             "Two cure requests have already been filed against this assessment")
    derive.penalty_cure_requested(assessment, fund, body["cure_basis"],
                                 body["narrative_reference"], g.user_id)
    return one(assessment)


@bp.post("/penalty-assessments/<assessment_id>/cure-decisions")
def create_cure_decision(assessment_id):
    authenticate((ROLE_COMPLIANCE_OFFICER,))
    body = parse_body([F("decision", "enum", enum=DECISIONS)])
    assessment = must_get("penalty_assessments", assessment_id)
    guard_state(assessment["status"], ("CURE_REQUESTED",), ("CURED", "UPHELD"))
    if (body["decision"] == "APPROVE"
            and assessment["cure_basis"] != "REASONABLE_CAUSE"):
        fail("ERR_CURE_BASIS_NOT_APPROVABLE",
             "Only a REASONABLE_CAUSE basis may be approved")
    fund = get("funds", assessment["fund_id"])
    if body["decision"] == "APPROVE":
        derive.penalty_cure_approved(assessment, fund, g.user_id)
    else:
        derive.penalty_cure_denied(assessment, fund, g.user_id)
    return one(assessment)
