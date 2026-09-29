"""ReserveDraw lifecycle and the two capacity gates (PRD section 3.4)."""

from flask import g

import domain
import guards
import repo
import validation as v
from db import clock_iso
from errors import ApiError
from middleware import ANY_ROLE, BRAND_MANAGER, FRANCHISEE_OWNER
from routing import route

DECISIONS = ("CONSENT", "REJECT")
FUNDABLE_BUDGET_STATUSES = ("APPROVED", "LOCKED", "UNDERFUNDED")


@route("/pip/reserve-draws", ["POST"], (FRANCHISEE_OWNER,))
def create_draw():
    body = v.body_json()
    # Body foreign keys resolve in the canonical order of PRD section 2.6:
    # property_id, then the item reference, then capital_budget_id.
    prop = guards.resolve_body_fk(body, "property_id", "properties")
    item = guards.resolve_body_fk(body, "purpose_item_id", "items")
    budget = guards.resolve_body_fk(body, "capital_budget_id", "budgets")

    v.require(
        body,
        "property_id",
        "capital_budget_id",
        "purpose_item_id",
        "amount_cents",
        "expected_property_version",
    )
    amount = v.get_int(body, "amount_cents", minimum=1)
    expected = v.get_int(body, "expected_property_version")

    # band 4
    guards.require_franchise_not_terminated(prop)

    # band 5
    if expected != prop["version"]:
        raise ApiError(
            "ERR_STALE_PROPERTY_VERSION",
            "expected_property_version does not match the property's current version",
        )

    # band 8
    budget_plan = repo.find("plans", budget["plan_id"])
    if item["plan_id"] != budget["plan_id"]:
        raise ApiError(
            "ERR_DRAW_ITEM_PLAN_MISMATCH",
            "purpose_item_id must belong to the plan the budget funds",
        )
    if budget_plan is None or budget_plan["property_id"] != prop["id"]:
        raise ApiError(
            "ERR_DRAW_PROPERTY_MISMATCH",
            "property_id must be the property of the plan the budget funds",
        )
    guards.require_owner(prop)

    # band 10 — reserve availability first, then the budget's own headroom.
    available = domain.reserve_available_cents(prop)
    if amount > available:
        raise ApiError(
            "ERR_INSUFFICIENT_RESERVE",
            "only %d cents of reserve is available for a new draw" % available,
        )
    headroom = domain.budget_headroom_cents(budget)
    if amount > headroom:
        raise ApiError(
            "ERR_DRAW_EXCEEDS_BUDGET",
            "only %d cents of budget headroom remains" % headroom,
        )

    row = repo.new_row(
        {
            "property_id": prop["id"],
            "capital_budget_id": budget["id"],
            "purpose_item_id": item["id"],
            "amount_cents": amount,
            "status": "REQUESTED",
            "consented_by_user_id": None,
            "disbursed_at": None,
        }
    )
    repo.insert("draws", row)
    repo.touch(prop)
    return repo.single(row, 201)


@route("/pip/reserve-draws/<row_id>", ["GET"], ANY_ROLE)
def get_draw(row_id):
    return repo.single(repo.must_find("draws", row_id))


@route("/pip/reserve-draws", ["GET"], ANY_ROLE)
def list_draws():
    limit, offset = v.pagination()
    rows = repo.rows("draws")
    for field in ("property_id", "capital_budget_id", "purpose_item_id", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/reserve-draws/<row_id>/consent", ["POST"], (BRAND_MANAGER,))
def consent_draw(row_id):
    draw = repo.must_find("draws", row_id)
    body = v.body_json()
    v.require(body, "decision")
    decision = v.get_enum(body, "decision", DECISIONS)

    if draw["status"] != "REQUESTED":
        raise ApiError(
            "ERR_DRAW_NOT_DECIDABLE", "only a REQUESTED draw may be decided"
        )

    budget = repo.find("budgets", draw["capital_budget_id"])
    if decision == "CONSENT" and (
        budget is None or budget["status"] not in FUNDABLE_BUDGET_STATUSES
    ):
        raise ApiError(
            "ERR_BUDGET_NOT_FUNDABLE",
            "the draw's capital budget is not in a fundable state",
        )

    draw["status"] = "BRAND_CONSENTED" if decision == "CONSENT" else "REJECTED"
    draw["consented_by_user_id"] = g.user_id
    repo.touch(draw)
    return repo.single(draw)


@route("/pip/reserve-draws/<row_id>/disburse", ["POST"], (FRANCHISEE_OWNER,))
def disburse_draw(row_id):
    draw = repo.must_find("draws", row_id)
    prop = repo.find("properties", draw["property_id"])
    budget = repo.find("budgets", draw["capital_budget_id"])

    if draw["status"] != "BRAND_CONSENTED":
        raise ApiError(
            "ERR_DRAW_NOT_DISBURSABLE",
            "only a BRAND_CONSENTED draw may be disbursed",
        )
    guards.require_owner(prop)

    if (
        prop["reserve_balance_cents"] - draw["amount_cents"]
        < prop["minimum_retention_cents"]
    ):
        raise ApiError(
            "ERR_INSUFFICIENT_RESERVE",
            "the disbursement would break the property's retention floor",
        )

    draw["status"] = "DISBURSED"
    draw["disbursed_at"] = clock_iso()
    repo.touch(draw)

    prop["reserve_balance_cents"] -= draw["amount_cents"]
    repo.touch(prop)

    domain.recompute_budget_committed(budget)
    domain.append_ledger(
        budget["plan_id"],
        draw["purpose_item_id"],
        "DRAW_DISBURSED",
        draw["amount_cents"],
        "reserve draw %s disbursed" % draw["id"],
    )
    domain.recompute_property(prop)
    return repo.single(draw)


@route("/pip/reserve-draws/<row_id>/reverse", ["POST"], (FRANCHISEE_OWNER,))
def reverse_draw(row_id):
    draw = repo.must_find("draws", row_id)
    prop = repo.find("properties", draw["property_id"])
    budget = repo.find("budgets", draw["capital_budget_id"])

    if draw["status"] != "DISBURSED":
        raise ApiError(
            "ERR_DRAW_NOT_REVERSIBLE", "only a DISBURSED draw may be reversed"
        )
    guards.require_owner(prop)

    if budget is not None and budget["status"] == "CLOSED":
        raise ApiError(
            "ERR_BUDGET_CLOSED",
            "the funding budget is closed and the disbursement can no longer be unwound",
        )

    draw["status"] = "REVERSED"
    repo.touch(draw)

    prop["reserve_balance_cents"] += draw["amount_cents"]
    repo.touch(prop)

    domain.recompute_budget_committed(budget)
    domain.append_ledger(
        budget["plan_id"],
        draw["purpose_item_id"],
        "DRAW_REVERSED",
        -draw["amount_cents"],
        "reserve draw %s reversed" % draw["id"],
    )
    domain.recompute_property(prop)
    return repo.single(draw)
