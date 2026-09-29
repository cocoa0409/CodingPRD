"""CapitalBudget authorisation, supersession, approval and locking (PRD 3.3)."""

from flask import g

import calc
import domain
import guards
import repo
import validation as v
from errors import ApiError
from middleware import ANY_ROLE, BRAND_MANAGER, FRANCHISEE_OWNER
from routing import route

APPROVE_PLAN_STATUSES = ("ISSUED", "OWNER_ACKNOWLEDGED", "IN_EXECUTION")


def _contingency(body):
    """0 <= value <= 0.50 with at most 4 decimal places."""
    raw = body["contingency_pct"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ApiError("ERR_VALIDATION", "contingency_pct must be a number")
    value = calc.frac(raw)
    places = v.decimal_places(raw)
    if (
        value < 0
        or value > calc.MAX_CONTINGENCY_PCT
        or places is None
        or places > 4
    ):
        raise ApiError(
            "ERR_CONTINGENCY_OUT_OF_RANGE",
            "contingency_pct must be between 0 and 0.50 with at most 4 decimals",
        )
    return raw


@route("/pip/capital-budgets", ["POST"], (FRANCHISEE_OWNER,))
def create_budget():
    body = v.body_json()
    plan = guards.resolve_body_fk(body, "plan_id", "plans")

    v.require(
        body,
        "plan_id",
        "total_authorized_cents",
        "contingency_pct",
        "financing_source",
        "expected_plan_version",
    )
    total = v.get_int(body, "total_authorized_cents", minimum=1)
    financing = v.get_enum(body, "financing_source", calc.FINANCING_SOURCES)
    expected = v.get_int(body, "expected_plan_version")
    contingency = _contingency(body)

    prop = domain.property_of_plan(plan)
    guards.require_franchise_not_terminated(prop)

    if expected != plan["version"]:
        raise ApiError(
            "ERR_STALE_PLAN_VERSION",
            "expected_plan_version does not match the plan's current version",
        )

    guards.require_owner(prop)

    # Creation supersedes: at most one active budget exists per plan.
    for existing in domain.budgets_of_plan(plan["id"]):
        if existing["status"] in calc.ACTIVE_BUDGET_STATUSES:
            existing["status"] = "SUPERSEDED"
            repo.touch(existing)

    row = repo.new_row(
        {
            "plan_id": plan["id"],
            "total_authorized_cents": total,
            "contingency_pct": contingency,
            "financing_source": financing,
            "status": "DRAFT",
            "committed_cents": 0,
            "approved_by_user_id": None,
        }
    )
    repo.insert("budgets", row)

    domain.recompute_plan_funding(plan)
    repo.touch(plan)
    domain.recompute_property(prop)
    return repo.single(row, 201)


@route("/pip/capital-budgets/<row_id>", ["GET"], ANY_ROLE)
def get_budget(row_id):
    return repo.single(repo.must_find("budgets", row_id))


@route("/pip/capital-budgets", ["GET"], ANY_ROLE)
def list_budgets():
    limit, offset = v.pagination()
    rows = repo.rows("budgets")
    for field in ("plan_id", "status", "financing_source"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/capital-budgets/<row_id>/approve", ["POST"], (BRAND_MANAGER,))
def approve_budget(row_id):
    budget = repo.must_find("budgets", row_id)
    plan = repo.find("plans", budget["plan_id"])

    if budget["status"] != "DRAFT":
        raise ApiError(
            "ERR_BUDGET_NOT_APPROVABLE", "only a DRAFT budget may be approved"
        )
    guards.require_execution_window(plan, APPROVE_PLAN_STATUSES)

    budget["status"] = "APPROVED"
    budget["approved_by_user_id"] = g.user_id
    repo.touch(budget)
    return repo.single(budget)


@route("/pip/capital-budgets/<row_id>/lock", ["POST"], (FRANCHISEE_OWNER,))
def lock_budget(row_id):
    budget = repo.must_find("budgets", row_id)
    plan = repo.find("plans", budget["plan_id"])
    prop = domain.property_of_plan(plan)

    # band 4 — precedes the fiscal check of band 10 (PRD section 2.6).
    if budget["status"] != "APPROVED":
        raise ApiError(
            "ERR_BUDGET_NOT_LOCKABLE", "only an APPROVED budget may be locked"
        )

    # band 8
    guards.require_owner(prop)

    # band 10
    domain.recompute_plan_funding(plan)
    if plan["funding_gap_cents"] != 0:
        raise ApiError(
            "ERR_BUDGET_UNDERFUNDED",
            "the plan still carries a funding gap of %d cents"
            % plan["funding_gap_cents"],
        )

    budget["status"] = "LOCKED"
    repo.touch(budget)
    return repo.single(budget)
