"""Category plans, plan months and option plans (including the size curve)."""
from flask import Blueprint, request

from common import (F, ROLE_PLANNER, ROLE_DIRECTOR, PLANNING_ROLES, auth, fail,
                    page_of, pagination, parse_input, public, public_list,
                    respond)
import calc
import store
import svc
from store import db, make_row, touch

bp = Blueprint("plan", __name__)

BASES = ["PLANNED_BASIS", "PROJECTED_BASIS"]


def _filter(rows, name, field=None):
    value = request.args.get(name)
    if value is None:
        return rows
    return [r for r in rows if r.get(field or name) == value]


def _basis_param():
    raw = request.args.get("basis")
    if raw is None:
        return None
    if raw not in BASES:
        fail("ERR_INVALID_REQUEST", "basis must be PLANNED_BASIS or PROJECTED_BASIS")
    return raw


# ---------------------------------------------------------------------------
# Category plans
# ---------------------------------------------------------------------------
PLAN_FIELDS = [
    F("category_id", "str", min_len=1),
    F("season_code", "enum", enum=["SPRING", "SUMMER", "FALL", "HOLIDAY"]),
    F("fiscal_year", "int", minimum=2000, maximum=2100),
    F("planned_sales_cents", "int", minimum=1),
    F("planned_margin_bps", "int", minimum=0, maximum=9999),
    F("planned_turn_x100", "int", minimum=1),
]


@bp.post("/otb/category-plans")
def create_plan():
    auth([ROLE_PLANNER])
    data = parse_input(PLAN_FIELDS)
    store.get_category(data["category_id"])
    for row in db.plans.values():
        if (row["category_id"] == data["category_id"]
                and row["season_code"] == data["season_code"]
                and row["fiscal_year"] == data["fiscal_year"]):
            fail("ERR_DUPLICATE_CATEGORY_PLAN",
                 "a plan already exists for this category, season and fiscal year")
    row = make_row(
        status="DRAFT",
        reforecast_round=0,
        receipt_budget_cents=None,
        otb_posture="OPEN",
        variance_status="ON_PLAN",
        sales_variance_bps=0,
        open_ratio_bps=10000,
        submitted_by_user_id=None,
        approved_by_user_id=None,
        **data)
    db.plans[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/category-plans/<rid>")
def read_plan(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_plan(rid)))


@bp.get("/otb/category-plans")
def list_plans():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.plans.values()))
    rows = _filter(rows, "category_id")
    rows = _filter(rows, "status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


@bp.post("/otb/category-plans/<rid>/submit")
def submit_plan(rid):
    user_id, _ = auth([ROLE_PLANNER])
    parse_input([F("submission_note", "str", required=False, max_len=1000)])
    plan = store.get_plan(rid)
    if plan["status"] not in ("DRAFT", "REFORECAST_OPEN"):
        fail("ERR_INVALID_STATE", "a %s plan cannot be submitted" % plan["status"])
    if not store.plan_months(plan["id"]) or not store.plan_optionplans(plan["id"]):
        fail("ERR_INVALID_STATE",
             "submission requires at least one plan month and one option plan")
    if plan["status"] == "REFORECAST_OPEN":
        for cycle in store.plan_cycles(plan["id"]):
            if cycle["status"] not in ("CLOSED", "ABANDONED"):
                fail("ERR_INVALID_STATE",
                     "a reforecast cycle of this plan is still live")
    plan["status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = user_id
    touch(plan)
    return respond(public(plan))


@bp.post("/otb/category-plans/<rid>/approve")
def approve_plan(rid):
    user_id, _ = auth([ROLE_DIRECTOR])
    parse_input([F("approval_note", "str", required=False, max_len=1000)])
    plan = store.get_plan(rid)
    if plan.get("submitted_by_user_id") and plan["submitted_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the approving operator submitted this plan")
    if plan["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "a %s plan cannot be approved" % plan["status"])
    budget = calc.plan_receipt_budget(plan)
    if budget <= 0:
        fail("ERR_RECEIPT_BUDGET_ZERO", "the seasonal receipt budget resolves to zero")
    svc.cascade_b(plan, user_id, budget)
    return respond(public(plan))


@bp.post("/otb/category-plans/<rid>/reject")
def reject_plan(rid):
    user_id, _ = auth([ROLE_DIRECTOR])
    parse_input([F("rejection_reason", "str", min_len=1, max_len=1000)])
    plan = store.get_plan(rid)
    if plan.get("submitted_by_user_id") and plan["submitted_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the rejecting operator submitted this plan")
    if plan["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "a %s plan cannot be rejected" % plan["status"])
    svc.unwind_plan(plan)
    plan["status"] = "DRAFT"
    touch(plan)
    return respond(public(plan))


@bp.post("/otb/category-plans/<rid>/close")
def close_plan(rid):
    auth([ROLE_DIRECTOR])
    parse_input([])
    plan = store.get_plan(rid)
    if plan["status"] not in ("APPROVED", "REFORECAST_OPEN"):
        fail("ERR_INVALID_STATE", "a %s plan cannot be closed" % plan["status"])
    for month in store.plan_months(plan["id"]):
        for rc in store.month_commitments(month["id"]):
            if rc["commit_status"] == "PROPOSED":
                fail("ERR_INVALID_STATE",
                     "a receipt commitment of this plan is still PROPOSED")
    svc.close_plan_cascade(plan)
    return respond(public(plan))


@bp.get("/otb/category-plans/<rid>/otb-summary")
def plan_otb_summary(rid):
    auth(PLANNING_ROLES)
    basis = _basis_param()
    plan = store.get_plan(rid)
    months = calc.posture_month_set(plan["id"])
    planned = committed = received = open_cents = 0
    if basis is None:
        for month in months:
            planned += month["otb_planned_cents"]
            committed += month["otb_committed_cents"]
            received += month["otb_received_cents"]
            open_cents += month["otb_open_cents"]
        ratio = plan["open_ratio_bps"]
        posture = plan["otb_posture"]
        shown_basis = plan_basis(months)
    else:
        for month in months:
            figures = calc.evaluate_month(month, plan, basis)
            planned += figures["otb_planned_cents"]
            committed += figures["otb_committed_cents"]
            received += figures["otb_received_cents"]
            open_cents += figures["otb_open_cents"]
        ratio, posture = calc.compute_posture(plan, open_cents, planned, len(months))
        shown_basis = basis
    return respond({
        "category_plan_id": plan["id"],
        "basis": shown_basis,
        "receipt_budget_cents": plan["receipt_budget_cents"],
        "otb_planned_cents": planned,
        "otb_committed_cents": committed,
        "otb_received_cents": received,
        "otb_open_cents": open_cents,
        "open_ratio_bps": ratio,
        "otb_posture": posture,
        "variance_status": plan["variance_status"],
        "sales_variance_bps": plan["sales_variance_bps"],
        "month_count": len(months),
    })


def plan_basis(months):
    """The basis a plan-level summary reports when none was requested."""
    for month in months:
        if month["active_basis"] == "PROJECTED_BASIS":
            return "PROJECTED_BASIS"
    return "PLANNED_BASIS"


# ---------------------------------------------------------------------------
# Plan months
# ---------------------------------------------------------------------------
MONTH_FIELDS = [
    F("category_plan_id", "str", min_len=1),
    F("month_index", "int", minimum=1, maximum=12),
    F("fiscal_month_label", "str", min_len=7, max_len=7,
      pattern=r"^\d{4}-\d{2}$"),
    F("first_receipt_date", "datetime"),
    F("bom_inventory_cents", "int", minimum=0),
    F("planned_sales_cents", "int", minimum=0),
    F("planned_markdown_cents", "int", minimum=0),
    F("planned_eom_cents", "int", minimum=0),
]


@bp.post("/otb/plan-months")
def create_month():
    auth([ROLE_PLANNER])
    data = parse_input(MONTH_FIELDS)
    store.get_plan(data["category_plan_id"])
    for row in store.plan_months(data["category_plan_id"]):
        if row["month_index"] == data["month_index"]:
            fail("ERR_DUPLICATE_PLAN_MONTH",
                 "month_index must be unique within the category plan")
    row = make_row(
        status="DRAFT",
        active_basis="PLANNED_BASIS",
        provisional_sell_through_bps=0,
        reserve_rate_bps=0,
        markdown_reserve_cents=0,
        otb_planned_cents=0,
        otb_committed_cents=0,
        otb_received_cents=0,
        otb_open_cents=0,
        **data)
    db.months[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/plan-months/<rid>")
def read_month(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_month(rid)))


@bp.get("/otb/plan-months")
def list_months():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = sorted(db.months.values(), key=lambda m: (m["month_index"], m["_seq"]))
    rows = _filter(rows, "category_plan_id")
    rows = _filter(rows, "status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


@bp.post("/otb/plan-months/<rid>/open-season")
def open_season(rid):
    auth([ROLE_PLANNER])
    parse_input([])
    month = store.get_month(rid)
    if month["status"] != "LOCKED_PLAN":
        fail("ERR_INVALID_STATE", "a %s month cannot open for the season" % month["status"])
    plan = store.month_plan(month)
    if plan["status"] != "APPROVED":
        fail("ERR_CATEGORY_PLAN_NOT_APPROVED",
             "the parent category plan is %s" % plan["status"])
    month["status"] = "IN_SEASON"
    touch(month)
    svc.recompute_plan_posture(plan)
    return respond(public(month))


@bp.get("/otb/plan-months/<rid>/otb-ledger")
def month_ledger(rid):
    auth(PLANNING_ROLES)
    basis = _basis_param()
    month = store.get_month(rid)
    plan = store.month_plan(month)
    return respond(calc.evaluate_month(month, plan, basis or month["active_basis"]))


@bp.get("/otb/plan-months/<rid>/actuals-posts")
def month_actuals(rid):
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    month = store.get_month(rid)
    rows = store.month_actuals(month["id"])
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


# ---------------------------------------------------------------------------
# Option plans
# ---------------------------------------------------------------------------
OPTION_PLAN_FIELDS = [
    F("category_plan_id", "str", min_len=1),
    F("store_cluster_id", "str", min_len=1),
    F("tier", "enum", enum=["GOOD", "BETTER", "BEST"]),
    F("breadth_target", "int", minimum=1, maximum=200),
    F("depth_units_per_option", "int", minimum=1, maximum=500),
    F("assumed_unit_cost_cents", "int", minimum=1),
]


@bp.post("/otb/option-plans")
def create_optionplan():
    auth([ROLE_PLANNER])
    data = parse_input(OPTION_PLAN_FIELDS)
    store.get_plan(data["category_plan_id"])
    store.get_cluster(data["store_cluster_id"])
    for row in store.plan_optionplans(data["category_plan_id"]):
        if (row["store_cluster_id"] == data["store_cluster_id"]
                and row["tier"] == data["tier"]):
            fail("ERR_DUPLICATE_OPTION_PLAN",
                 "an option plan already exists for this plan, cluster and tier")
    row = make_row(
        status="OPEN",
        option_slots_total=None,
        option_slots_assigned=0,
        option_slots_open=None,
        target_units_per_option=None,
        **data)
    db.optionplans[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/option-plans/<rid>")
def read_optionplan(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_optionplan(rid)))


@bp.get("/otb/option-plans")
def list_optionplans():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.optionplans.values()))
    rows = _filter(rows, "category_plan_id")
    rows = _filter(rows, "store_cluster_id")
    rows = _filter(rows, "tier")
    rows = _filter(rows, "status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


SIZE_CELL_FIELDS = [
    F("size_label", "str", min_len=1, max_len=12),
    F("size_sort_order", "int", minimum=1, maximum=99),
    F("pct_bps", "int", minimum=1, maximum=10000),
]


@bp.put("/otb/option-plans/<rid>/size-curve")
def replace_size_curve(rid):
    auth([ROLE_PLANNER])
    body = parse_input([F("cells", "list")])
    submitted = []
    for element in body["cells"]:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "every cells element must be an object")
        submitted.append(parse_input(SIZE_CELL_FIELDS, element))
    cell = store.get_optionplan(rid)
    if not submitted:
        fail("ERR_SIZE_CURVE_EMPTY", "the cells array must not be empty")
    if sum(s["pct_bps"] for s in submitted) != 10000:
        fail("ERR_SIZE_CURVE_NOT_BALANCED", "pct_bps values must sum to exactly 10000")
    if len(set(s["size_label"] for s in submitted)) != len(submitted):
        fail("ERR_SIZE_CURVE_NOT_BALANCED", "size_label must be unique within the set")
    if len(set(s["size_sort_order"] for s in submitted)) != len(submitted):
        fail("ERR_SIZE_CURVE_NOT_BALANCED", "size_sort_order must be unique within the set")
    candidates = [dict(s) for s in submitted]
    svc.run_size_allocation(cell, False, candidates)
    for existing in store.optionplan_sizecells(cell["id"]):
        del db.sizecells[existing["id"]]
    rows = []
    for candidate in candidates:
        row = make_row(
            governed=False,
            option_plan_id=cell["id"],
            size_label=candidate["size_label"],
            size_sort_order=candidate["size_sort_order"],
            pct_bps=candidate["pct_bps"],
            raw_units_x10000=candidate["raw_units_x10000"],
            allocated_units=candidate["allocated_units"],
        )
        db.sizecells[row["id"]] = row
        rows.append(row)
    touch(cell)
    rows.sort(key=lambda r: (r["size_sort_order"], r["_seq"]))
    return respond(public_list(rows))


@bp.get("/otb/option-plans/<rid>/size-curve-cells")
def list_size_cells(rid):
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    cell = store.get_optionplan(rid)
    rows = store.optionplan_sizecells(cell["id"])
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)
