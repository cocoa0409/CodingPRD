"""Operating budgets, their revision cycle and variance authority."""

from flask import Blueprint

import validate as v
from auth import READ_ROLES, authenticate
from db import by_seq, new_row, serialize, store, touch
from errors import ApiError
from money import as_json_number
from response import ok
from routes.common import paged
from services import calc, core
from timeutil import add_days_iso, cmp_iso

bp = Blueprint("budgets", __name__)

BUDGET_DECISIONS = ("APPROVE", "REQUEST_REVISION")
VARIANCE_CATEGORIES = ("OPERATING", "CAPITAL_FFE", "CAPITAL_BRAND")
VARIANCE_DECISIONS = ("APPROVE", "DENY")
CATEGORY_LINE = {
    "OPERATING": "budgeted_operating_expenses_cents",
    "CAPITAL_FFE": "budgeted_capital_ffe_cents",
    "CAPITAL_BRAND": "budgeted_capital_brand_cents",
}
AUTHORITY = {
    "AssetManager": ("ASSET_MANAGER",),
    "OwnerRep": ("ASSET_MANAGER", "OWNER_REP"),
}


def _apply_derived(budget, agreement):
    base_fee, centralized, agop = calc.budget_derived(
        budget["budgeted_revenue_cents"],
        budget["budgeted_operating_expenses_cents"],
        agreement["base_fee_pct"],
        agreement["centralized_services_cap_pct"],
    )
    budget["budgeted_base_fee_cents"] = base_fee
    budget["budgeted_centralized_cents"] = centralized
    budget["budgeted_agop_cents"] = agop


# ---------------------------------------------------------------------------
# POST /hotel-management/agreements/{id}/budgets
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements/<agreement_id>/budgets")
def create_budget(agreement_id):
    authenticate(["HotelManagerOps"])
    body = v.body()
    fiscal_year = v.req_int(body, "fiscal_year", ge=2000, le=2100)
    budgeted_revenue_cents = v.req_int(body, "budgeted_revenue_cents", gt=0)
    budgeted_operating_expenses_cents = v.req_int(
        body, "budgeted_operating_expenses_cents", ge=0
    )
    expected_version = v.req_int(body, "expected_agreement_version")
    budgeted_capital_ffe_cents = v.opt_int(body, "budgeted_capital_ffe_cents", default=0, ge=0)
    budgeted_capital_brand_cents = v.opt_int(body, "budgeted_capital_brand_cents", default=0, ge=0)
    supersedes_budget_id = v.opt_str(body, "supersedes_budget_id")

    agreement = core.find_agreement(agreement_id)

    # rule 16
    target = None
    if supersedes_budget_id is not None:
        target = store.budgets.get(supersedes_budget_id)
        if (
            target is None
            or target["agreement_id"] != agreement["id"]
            or target["fiscal_year"] != fiscal_year
            or target["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED")
        ):
            raise ApiError("ERR_SUPERSEDE_TARGET_INVALID")

    # rule 17
    if expected_version != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION")

    # rule 18
    core.require_active(agreement)

    budget = new_row(
        {
            "agreement_id": agreement["id"],
            "supersedes_budget_id": supersedes_budget_id,
            "fiscal_year": fiscal_year,
            "status": "DRAFT",
            "budgeted_revenue_cents": budgeted_revenue_cents,
            "budgeted_operating_expenses_cents": budgeted_operating_expenses_cents,
            "budgeted_capital_ffe_cents": budgeted_capital_ffe_cents,
            "budgeted_capital_brand_cents": budgeted_capital_brand_cents,
            "budgeted_base_fee_cents": 0,
            "budgeted_centralized_cents": 0,
            "budgeted_agop_cents": 0,
            "revision_round": 0,
            "submitted_at": None,
            "submitted_by_user_id": None,
            "owner_decision_deadline_utc": None,
            "decided_by_user_id": None,
            "carryforward_applied": False,
        }
    )
    _apply_derived(budget, agreement)
    store.budgets[budget["id"]] = budget

    if target is not None:
        target["status"] = "SUPERSEDED"
        touch(target)

    touch(agreement)
    return ok(serialize(budget), 201)


@bp.get("/hotel-management/budgets/<budget_id>")
def read_budget(budget_id):
    authenticate(READ_ROLES)
    return ok(serialize(core.find_budget(budget_id)))


@bp.get("/hotel-management/budgets")
def list_budgets():
    authenticate(READ_ROLES)
    rows = by_seq(list(store.budgets.values()))
    agreement_id = v.query_str("agreement_id")
    supersedes_budget_id = v.query_str("supersedes_budget_id")
    fiscal_year = v.query_int("fiscal_year")
    status = v.query_str("status")
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if supersedes_budget_id is not None:
        rows = [r for r in rows if r["supersedes_budget_id"] == supersedes_budget_id]
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows, strict=True)


# ---------------------------------------------------------------------------
# POST /hotel-management/budgets/{id}/submit
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/budgets/<budget_id>/submit")
def submit_budget(budget_id):
    user_id, _role = authenticate(["HotelManagerOps"])
    body = v.body()
    revenue = v.opt_int(body, "budgeted_revenue_cents", gt=0)
    opex = v.opt_int(body, "budgeted_operating_expenses_cents", ge=0)
    ffe = v.opt_int(body, "budgeted_capital_ffe_cents", ge=0)
    brand = v.opt_int(body, "budgeted_capital_brand_cents", ge=0)

    budget = core.find_budget(budget_id)
    agreement = core.find_agreement(budget["agreement_id"])
    core.require_active(agreement)
    if budget["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_BUDGET_STATE")

    if budget["status"] == "REVISION_REQUESTED":
        budget["revision_round"] = budget["revision_round"] + 1

    if revenue is not None:
        budget["budgeted_revenue_cents"] = revenue
    if opex is not None:
        budget["budgeted_operating_expenses_cents"] = opex
    if ffe is not None:
        budget["budgeted_capital_ffe_cents"] = ffe
    if brand is not None:
        budget["budgeted_capital_brand_cents"] = brand

    budget["status"] = "SUBMITTED"
    budget["submitted_at"] = store.now_iso
    budget["submitted_by_user_id"] = user_id
    budget["owner_decision_deadline_utc"] = add_days_iso(
        budget["submitted_at"], agreement["owner_review_window_days"]
    )
    _apply_derived(budget, agreement)
    touch(budget)
    return ok(serialize(budget))


# ---------------------------------------------------------------------------
# POST /hotel-management/budgets/{id}/decision
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/budgets/<budget_id>/decision")
def decide_budget(budget_id):
    user_id, _role = authenticate(["OwnerRep"])
    body = v.body()
    decision = v.req_str(body, "decision")
    v.opt_str(body, "note")
    v.check_enum(decision, BUDGET_DECISIONS, "decision")

    budget = core.find_budget(budget_id)
    agreement = core.find_agreement(budget["agreement_id"])
    core.require_active(agreement)
    if budget["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BUDGET_STATE")
    if user_id == budget["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if cmp_iso(store.now_iso, budget["owner_decision_deadline_utc"]) > 0:
        raise ApiError("ERR_OWNER_DECISION_WINDOW_CLOSED")

    if decision == "APPROVE":
        if core.approved_equivalent_budget_exists(
            agreement["id"], budget["fiscal_year"], exclude_id=budget["id"]
        ):
            raise ApiError("ERR_BUDGET_YEAR_ALREADY_APPROVED")
        budget["status"] = "APPROVED"
        budget["decided_by_user_id"] = user_id
        touch(budget)
        return ok(serialize(budget))

    # REQUEST_REVISION -- the branch is selected purely by rounds already spent
    if budget["revision_round"] < agreement["max_revision_rounds"]:
        budget["status"] = "REVISION_REQUESTED"
        budget["decided_by_user_id"] = user_id
        touch(budget)
        return ok(serialize(budget))

    budget["status"] = "DEADLOCK_CARRYFORWARD"
    budget["decided_by_user_id"] = user_id
    source = core.select_budget_for_year(agreement["id"], budget["fiscal_year"] - 1)
    if source is not None:
        budget["carryforward_applied"] = True
        for field in (
            "budgeted_revenue_cents",
            "budgeted_operating_expenses_cents",
            "budgeted_capital_ffe_cents",
            "budgeted_capital_brand_cents",
        ):
            budget[field] = calc.carryforward_amount(source[field])
    _apply_derived(budget, agreement)
    touch(budget)
    return ok(serialize(budget))


# ---------------------------------------------------------------------------
# Variance requests
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/budgets/<budget_id>/variance-requests")
def create_variance(budget_id):
    user_id, _role = authenticate(["HotelManagerOps"])
    body = v.body()
    category = v.req_str(body, "category")
    requested_amount_cents = v.req_int(body, "requested_amount_cents", gt=0)
    justification = v.req_str(body, "justification")
    v.check_enum(category, VARIANCE_CATEGORIES, "category")

    budget = core.find_budget(budget_id)
    agreement = core.find_agreement(budget["agreement_id"])
    core.require_active(agreement)

    baseline = budget[CATEGORY_LINE[category]]
    for sibling in by_seq(
        [
            r
            for r in store.variance_requests.values()
            if r["budget_id"] == budget["id"]
            and r["category"] == category
            and r["status"] in ("AUTO_APPROVED", "APPROVED")
        ]
    ):
        baseline += sibling["requested_amount_cents"]

    if baseline <= 0:
        raise ApiError("ERR_VARIANCE_BASELINE_ZERO")

    variance_pct, approval_level, status = calc.variance_routing(
        requested_amount_cents, baseline
    )
    row = new_row(
        {
            "budget_id": budget["id"],
            "category": category,
            "requested_amount_cents": requested_amount_cents,
            "justification": justification,
            "effective_baseline_cents": baseline,
            "variance_pct": as_json_number(variance_pct),
            "approval_level": approval_level,
            "status": status,
            "requested_by_user_id": user_id,
            "decided_by_user_id": None,
            "denied_by_cascade": False,
        }
    )
    store.variance_requests[row["id"]] = row
    return ok(serialize(row), 201)


@bp.get("/hotel-management/budgets/<budget_id>/variance-requests")
def list_variances(budget_id):
    authenticate(READ_ROLES)
    budget = core.find_budget(budget_id)
    rows = by_seq(
        [r for r in store.variance_requests.values() if r["budget_id"] == budget["id"]]
    )
    category = v.query_str("category")
    status = v.query_str("status")
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows)


@bp.post("/hotel-management/variance-requests/<variance_id>/decision")
def decide_variance(variance_id):
    user_id, role = authenticate(["AssetManager", "OwnerRep"])
    body = v.body()
    decision = v.req_str(body, "decision")
    v.opt_str(body, "note")
    v.check_enum(decision, VARIANCE_DECISIONS, "decision")

    variance = core.find_variance(variance_id)
    budget = core.find_budget(variance["budget_id"])
    agreement = core.find_agreement(budget["agreement_id"])
    core.require_active(agreement)
    if variance["status"] != "PENDING":
        raise ApiError("ERR_INVALID_VARIANCE_STATE")
    if user_id == variance["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if variance["approval_level"] not in AUTHORITY.get(role, ()):
        raise ApiError("ERR_APPROVAL_AUTHORITY_INSUFFICIENT")

    variance["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    variance["decided_by_user_id"] = user_id
    touch(variance)
    return ok(serialize(variance))
