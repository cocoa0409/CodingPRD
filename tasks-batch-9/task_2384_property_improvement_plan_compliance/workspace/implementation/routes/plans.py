"""PipPlan lifecycle, cost read and the compliance sweep (PRD section 3.2, 3.9)."""

from fractions import Fraction

from flask import g

import calc
import domain
import guards
import repo
import validation as v
from db import clock_iso, clock_date
from errors import ApiError
from middleware import ANY_ROLE, BRAND_MANAGER, FRANCHISEE_OWNER
from response import object_response
from routing import route

PLAN_STATUSES = (
    "DRAFT",
    "ISSUED",
    "OWNER_ACKNOWLEDGED",
    "IN_EXECUTION",
    "READY_FOR_COMPLETION_INSPECTION",
    "COMPLETED",
    "TERMINATED",
    "WITHDRAWN",
)


@route("/pip/plans", ["POST"], (BRAND_MANAGER,))
def create_plan():
    body = v.body_json()
    prop = guards.resolve_body_fk(body, "property_id", "properties")

    v.require(body, "property_id", "trigger_type", "standards_edition")
    trigger_type = v.get_enum(body, "trigger_type", calc.TRIGGER_TYPES)
    standards_edition = v.get_str(body, "standards_edition", min_len=1, max_len=40)

    guards.require_franchise_not_terminated(prop)

    row = repo.new_row(
        {
            "property_id": prop["id"],
            "trigger_type": trigger_type,
            "standards_edition": standards_edition,
            "status": "DRAFT",
            "dispute_state": "NONE",
            "issued_by_user_id": None,
            "issued_at": None,
            "life_safety_deadline_date": None,
            "guest_facing_deadline_date": None,
            "back_of_house_deadline_date": None,
            "scope_item_count": 0,
            "brand_scoped_total_cents": 0,
            "owner_claimed_total_cents": 0,
            "funding_requirement_cents": 0,
            "funding_gap_cents": 0,
            "overdue_item_count": 0,
        }
    )
    repo.insert("plans", row)
    return repo.single(row, 201)


@route("/pip/plans/<row_id>", ["GET"], ANY_ROLE)
def get_plan(row_id):
    return repo.single(repo.must_find("plans", row_id))


@route("/pip/plans", ["GET"], ANY_ROLE)
def list_plans():
    limit, offset = v.pagination()
    rows = repo.rows("plans")
    for field in ("property_id", "status", "dispute_state"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/plans/<row_id>/issue", ["POST"], (BRAND_MANAGER,))
def issue_plan(row_id):
    plan = repo.must_find("plans", row_id)
    prop = domain.property_of_plan(plan)

    # band 4
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_ISSUABLE", "only a DRAFT plan may be issued")
    guards.require_franchise_not_terminated(prop)

    # band 9
    items = domain.plan_items(plan["id"])
    if not any(i["status"] == "SCOPED" for i in items):
        raise ApiError(
            "ERR_PLAN_HAS_NO_ITEMS", "the plan carries no item in SCOPED at issuance"
        )

    plan["status"] = "ISSUED"
    plan["issued_by_user_id"] = g.user_id
    plan["issued_at"] = clock_iso()

    issued_date = calc.parse_date(plan["issued_at"][:10])
    plan["life_safety_deadline_date"] = calc.fmt_date(
        calc.base_deadline(issued_date, "LIFE_SAFETY")
    )
    plan["guest_facing_deadline_date"] = calc.fmt_date(
        calc.base_deadline(issued_date, "GUEST_FACING")
    )
    plan["back_of_house_deadline_date"] = calc.fmt_date(
        calc.base_deadline(issued_date, "BACK_OF_HOUSE")
    )

    for item in items:
        domain.recompute_item_deadline(item, plan)
        domain.recompute_item_overdue(item)

    domain.assign_priority_ranks(plan)
    domain.recompute_plan_costs(plan)
    domain.recompute_plan_funding(plan)
    domain.recompute_plan_overdue(plan)
    repo.touch(plan)

    domain.append_ledger(
        plan["id"],
        None,
        "SCOPE_ISSUED",
        plan["brand_scoped_total_cents"],
        "plan issued with %d scoped items" % plan["scope_item_count"],
    )

    domain.recompute_property(prop)
    return repo.single(plan)


@route("/pip/plans/<row_id>/acknowledge", ["POST"], (FRANCHISEE_OWNER,))
def acknowledge_plan(row_id):
    plan = repo.must_find("plans", row_id)
    if plan["status"] != "ISSUED":
        raise ApiError(
            "ERR_PLAN_NOT_ACKNOWLEDGEABLE", "only an ISSUED plan may be acknowledged"
        )
    guards.require_owner(domain.property_of_plan(plan))

    plan["status"] = "OWNER_ACKNOWLEDGED"
    repo.touch(plan)
    return repo.single(plan)


@route("/pip/plans/<row_id>/withdraw", ["POST"], (BRAND_MANAGER,))
def withdraw_plan(row_id):
    plan = repo.must_find("plans", row_id)
    if plan["status"] not in ("DRAFT", "ISSUED"):
        raise ApiError(
            "ERR_PLAN_NOT_WITHDRAWABLE",
            "only a DRAFT or ISSUED plan may be withdrawn",
        )

    plan["status"] = "WITHDRAWN"
    for item in domain.plan_items(plan["id"]):
        if item["status"] in ("SCOPED", "DEFERRED_PENDING_EXTENSION"):
            item["status"] = "VOIDED"
            domain.recompute_item_overdue(item)
            repo.touch(item)

    domain.recompute_plan_costs(plan)
    domain.recompute_plan_funding(plan)
    domain.recompute_plan_overdue(plan)
    domain.assign_priority_ranks(plan)
    repo.touch(plan)
    domain.recompute_property(domain.property_of_plan(plan))
    return repo.single(plan)


@route("/pip/plans/<row_id>/cost-summary", ["GET"], ANY_ROLE)
def plan_cost_summary(row_id):
    plan = repo.must_find("plans", row_id)
    items = domain.included_items(plan["id"])

    brand_total = sum(i["brand_estimated_cost_cents"] for i in items)
    owner_total = 0
    for item in items:
        claimed = item["owner_claimed_cost_cents"]
        owner_total += (
            claimed if claimed is not None else item["brand_estimated_cost_cents"]
        )
    variance = owner_total - brand_total
    if brand_total == 0:
        variance_pct = 0.00
    else:
        variance_pct = calc.as_number(
            Fraction(variance * 100, brand_total), 2
        )

    budget = domain.active_budget(plan["id"])
    contingency = domain.contingency_for_plan(plan)
    requirement = 0
    for item in items:
        requirement += calc.item_funding_cents(
            item["approved_cost_cents"], item["category"], contingency
        )
    authorized = budget["total_authorized_cents"] if budget is not None else 0
    gap = 0 if budget is None else max(0, requirement - authorized)
    if requirement == 0:
        gap_pct = 0.00
    else:
        gap_pct = calc.as_number(Fraction(gap * 100, requirement), 2)

    data = {
        "plan_id": plan["id"],
        "included_item_count": len(items),
        "brand_scoped_total_cents": brand_total,
        "owner_claimed_total_cents": owner_total,
        "variance_cents": variance,
        "variance_pct": variance_pct,
        "contingency_pct_applied": calc.as_number(contingency, 4),
        "funding_requirement_cents": requirement,
        "authorized_cents": authorized,
        "funding_gap_cents": gap,
        "funding_gap_pct": gap_pct,
    }
    return object_response(data)


@route("/pip/plans/<row_id>/compliance-sweep", ["POST"], (BRAND_MANAGER,))
def compliance_sweep(row_id):
    plan = repo.must_find("plans", row_id)

    for item in domain.plan_items(plan["id"]):
        domain.recompute_item_overdue(item)
    domain.recompute_plan_overdue(plan)
    repo.touch(plan)
    domain.recompute_property(domain.property_of_plan(plan))
    return repo.single(plan)
