"""ScopeDispute filing and the resolution cascade (PRD 3.9)."""

from flask import g

import calc
import domain
import guards
import repo
import validation as v
from errors import ApiError
from middleware import ANY_ROLE, BRAND_MANAGER, FRANCHISEE_OWNER
from routing import route

REMOVABLE_ITEM_STATUSES = ("SCOPED", "DEFERRED_PENDING_EXTENSION", "IN_PROGRESS")
RESOLVED_STATUS = {
    "UPHOLD": "RESOLVED_UPHELD",
    "REVISE": "RESOLVED_REVISED",
    "REMOVE": "RESOLVED_REMOVED",
}
RESOLVED_DISPUTE_STATE = {
    "UPHOLD": "DISPUTE_RESOLVED_UPHELD",
    "REVISE": "DISPUTE_RESOLVED_REVISED",
    "REMOVE": "DISPUTE_RESOLVED_REMOVED",
}


@route("/pip/disputes", ["POST"], (FRANCHISEE_OWNER,))
def create_dispute():
    body = v.body_json()
    plan = guards.resolve_body_fk(body, "plan_id", "plans")
    item = guards.resolve_body_fk(body, "item_id", "items")

    v.require(body, "plan_id", "item_id", "dispute_basis", "claimed_cost_cents")
    basis = v.get_enum(body, "dispute_basis", calc.DISPUTE_BASES)
    claimed = v.get_int(body, "claimed_cost_cents", minimum=0)

    # band 4 — one open dispute per item.
    for other in domain.disputes_of_item(item["id"]):
        if other["status"] == "FILED":
            raise ApiError(
                "ERR_DISPUTE_ALREADY_OPEN",
                "a dispute on this item is already FILED",
            )

    # band 8
    if item["plan_id"] != plan["id"]:
        raise ApiError(
            "ERR_ITEM_PLAN_MISMATCH", "item_id must belong to plan_id"
        )
    prop = domain.property_of_plan(plan)
    guards.require_owner(prop)

    row = repo.new_row(
        {
            "plan_id": plan["id"],
            "item_id": item["id"],
            "dispute_basis": basis,
            "claimed_cost_cents": claimed,
            "filed_by_user_id": g.user_id,
            "status": "FILED",
            "revised_cost_cents": None,
            "panel_decision_note": None,
        }
    )
    repo.insert("disputes", row)

    item["owner_claimed_cost_cents"] = claimed
    repo.touch(item)

    # The dispute dimension moves; the lifecycle dimension is untouched.
    plan["dispute_state"] = "DISPUTE_OPEN"
    domain.recompute_plan_costs(plan)
    repo.touch(plan)
    domain.recompute_property(prop)
    return repo.single(row, 201)


@route("/pip/disputes/<row_id>", ["GET"], ANY_ROLE)
def get_dispute(row_id):
    return repo.single(repo.must_find("disputes", row_id))


@route("/pip/disputes", ["GET"], ANY_ROLE)
def list_disputes():
    limit, offset = v.pagination()
    rows = repo.rows("disputes")
    for field in ("plan_id", "item_id", "dispute_basis", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/disputes/<row_id>/resolve", ["POST"], (BRAND_MANAGER,))
def resolve_dispute(row_id):
    dispute = repo.must_find("disputes", row_id)
    plan = repo.find("plans", dispute["plan_id"])
    item = repo.find("items", dispute["item_id"])

    body = v.body_json()
    v.require(body, "resolution")
    resolution = v.get_enum(body, "resolution", calc.DISPUTE_RESOLUTIONS)
    note = v.get_str(body, "panel_decision_note", required=False, max_len=2000)

    # band 3 — the revised-cost coupling.
    revised = None
    if resolution == "REVISE":
        if body.get("revised_cost_cents") is None:
            raise ApiError(
                "ERR_REVISION_COST_REQUIRED",
                "revised_cost_cents is required when resolution is REVISE",
            )
        raw = body["revised_cost_cents"]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ApiError(
                "ERR_REVISION_COST_REQUIRED",
                "revised_cost_cents must be an integer >= 0",
            )
        revised = raw
    elif v.present(body, "revised_cost_cents"):
        raise ApiError(
            "ERR_REVISION_NOT_ALLOWED_FOR_RESOLUTION",
            "revised_cost_cents may only accompany a REVISE resolution",
        )

    # band 4
    if dispute["status"] != "FILED":
        raise ApiError(
            "ERR_DISPUTE_NOT_RESOLVABLE", "only a FILED dispute may be resolved"
        )
    for other in domain.disputes_of_plan(plan["id"]):
        if other["id"] != dispute["id"] and other["status"] == "FILED":
            raise ApiError(
                "ERR_DISPUTE_OPEN_BLOCKS_SIGNOFF",
                "another dispute on this plan is still FILED",
            )
    if resolution == "REMOVE" and item["status"] not in REMOVABLE_ITEM_STATUSES:
        raise ApiError(
            "ERR_ITEM_NOT_REMOVABLE",
            "the contested item is no longer removable from scope",
        )

    dispute["status"] = RESOLVED_STATUS[resolution]
    if note is not None:
        dispute["panel_decision_note"] = note

    prop = domain.property_of_plan(plan)

    if resolution == "REVISE":
        previous = item["approved_cost_cents"]
        dispute["revised_cost_cents"] = revised
        item["_cost_revised"] = True
        item["approved_cost_cents"] = revised
        repo.touch(item)
        repo.touch(dispute)

        plan["dispute_state"] = RESOLVED_DISPUTE_STATE[resolution]
        domain.recompute_plan_costs(plan)
        domain.recompute_plan_funding(plan)
        domain.assign_priority_ranks(plan)
        repo.touch(plan)
        domain.recompute_property(prop)
        domain.append_ledger(
            plan["id"],
            item["id"],
            "COST_REVISED",
            revised - previous,
            "dispute %s revised the item's approved cost" % dispute["id"],
        )
        return repo.single(dispute)

    if resolution == "REMOVE":
        removed_cost = item["approved_cost_cents"]
        item["status"] = "REMOVED_BY_DISPUTE"
        domain.recompute_item_overdue(item)
        repo.touch(item)
        repo.touch(dispute)

        plan["dispute_state"] = RESOLVED_DISPUTE_STATE[resolution]
        domain.recompute_plan_costs(plan)
        domain.recompute_plan_funding(plan)
        domain.recompute_plan_overdue(plan)
        domain.assign_priority_ranks(plan)
        # plan.status is explicitly untouched by a REMOVE resolution.
        repo.touch(plan)
        domain.recompute_property(prop)
        domain.append_ledger(
            plan["id"],
            item["id"],
            "ITEM_REMOVED",
            -removed_cost,
            "dispute %s removed the item from scope" % dispute["id"],
        )
        return repo.single(dispute)

    # UPHOLD — no cost movement at all.
    repo.touch(dispute)
    plan["dispute_state"] = RESOLVED_DISPUTE_STATE[resolution]
    repo.touch(plan)
    domain.recompute_property(prop)
    return repo.single(dispute)
