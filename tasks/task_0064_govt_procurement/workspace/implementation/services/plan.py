"""Procurement plan & plan item lifecycle."""

from clock import clock
from db import bump_version, common_fields_create, db
from errors import (
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PLAN_HAS_ACTIVE_PROJECT,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)


ACTIVE_PROJECT_STATUSES = {"BIDDING_OPEN", "EVALUATING", "AWARDED", "CONTRACT_SIGNED"}
BUDGET_INCLUDED_ITEM_STATUSES = {"APPROVED", "PUBLISHED", "EXECUTED"}


def get_plan_or_404(plan_id: str) -> dict:
    p = db.plans.get(plan_id)
    if not p:
        raise_error(ERR_NOT_FOUND, f"plan '{plan_id}' not found")
    return p


def get_plan_item_or_404(item_id: str) -> dict:
    it = db.plan_items.get(item_id)
    if not it:
        raise_error(ERR_NOT_FOUND, f"plan_item '{item_id}' not found")
    return it


def get_plan_item_or_ref_404(item_id: str) -> dict:
    it = db.plan_items.get(item_id)
    if not it:
        raise_error(ERR_REFERENCE_NOT_FOUND, f"plan_item '{item_id}' not found")
    return it


def items_for_plan(plan_id: str):
    return [it for it in db.plan_items.values() if it["plan_id"] == plan_id]


def recompute_total_budget(plan: dict):
    total = 0
    for it in items_for_plan(plan["id"]):
        if it["item_status"] in BUDGET_INCLUDED_ITEM_STATUSES:
            total += int(it["budget_cents"])
    plan["total_budget_cents"] = total


def create_plan(agency_id: str, fiscal_year):
    if not isinstance(agency_id, str) or not agency_id:
        raise_error(ERR_VALIDATION, "agency_id must be non-empty string")
    if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int):
        raise_error(ERR_VALIDATION, "fiscal_year must be integer")
    if fiscal_year < 2000 or fiscal_year > 2100:
        raise_error(ERR_VALIDATION, "fiscal_year out of range [2000, 2100]")
    p = {
        "id": db.new_id(),
        **common_fields_create(),
        "agency_id": agency_id,
        "fiscal_year": fiscal_year,
        "status": "DRAFT",
        "total_budget_cents": 0,
        "published_at": None,
        "amendment_round": 0,
    }
    db.plans[p["id"]] = p
    return p


def add_plan_item(plan_id: str, title: str, category: str, budget_cents):
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "plan must be DRAFT to add items")
    if not isinstance(title, str) or not title:
        raise_error(ERR_VALIDATION, "title must be non-empty string")
    if category not in {"GOODS", "SERVICES", "WORKS"}:
        raise_error(ERR_VALIDATION, "category must be one of GOODS, SERVICES, WORKS")
    if isinstance(budget_cents, bool) or not isinstance(budget_cents, int):
        raise_error(ERR_VALIDATION, "budget_cents must be integer")
    if budget_cents <= 0:
        raise_error(ERR_VALIDATION, "budget_cents must be > 0")
    it = {
        "id": db.new_id(),
        **common_fields_create(),
        "plan_id": plan_id,
        "title": title,
        "category": category,
        "budget_cents": int(budget_cents),
        "item_status": "PROPOSED",
        "executed_amount_cents": 0,
    }
    db.plan_items[it["id"]] = it
    bump_version(plan)  # cascade: parent updated_at/version
    return it


def approve_plan_item(item_id: str):
    it = get_plan_item_or_404(item_id)
    plan = get_plan_or_404(it["plan_id"])
    if plan["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "parent plan must be UNDER_REVIEW")
    if it["item_status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "plan item must be PROPOSED")
    it["item_status"] = "APPROVED"
    bump_version(it)
    # The PRD/scaffold say total_budget_cents is recomputed on plan transitions
    # into PUBLISHED and on plan-item status changes while parent is PUBLISHED.
    if plan["status"] == "PUBLISHED":
        recompute_total_budget(plan)
        bump_version(plan)
    else:
        bump_version(plan)
    return it


def reject_plan_item(item_id: str):
    it = get_plan_item_or_404(item_id)
    plan = get_plan_or_404(it["plan_id"])
    if plan["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "parent plan must be UNDER_REVIEW")
    if it["item_status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "plan item must be PROPOSED")
    it["item_status"] = "REJECTED"
    bump_version(it)
    bump_version(plan)
    return it


def cancel_plan_item(item_id: str):
    it = get_plan_item_or_404(item_id)
    plan = get_plan_or_404(it["plan_id"])
    if it["item_status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "plan item must be PUBLISHED to cancel")
    # No Project may reference this PlanItem
    for pj in db.projects.values():
        if pj["plan_item_id"] == item_id:
            raise_error(ERR_INVALID_STATE, "plan item has a project; cannot cancel")
    it["item_status"] = "CANCELLED"
    bump_version(it)
    if plan["status"] == "PUBLISHED":
        recompute_total_budget(plan)
    bump_version(plan)
    return it


def submit_review(plan_id: str):
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "plan must be DRAFT to submit-review")
    items = items_for_plan(plan_id)
    if not any(it["item_status"] == "PROPOSED" for it in items):
        raise_error(ERR_INVALID_STATE, "plan needs >= 1 PROPOSED item to submit-review")
    plan["status"] = "UNDER_REVIEW"
    bump_version(plan)
    return plan


def publish_plan(plan_id: str):
    plan = get_plan_or_404(plan_id)
    if plan["status"] == "UNDER_REVIEW":
        items = items_for_plan(plan_id)
        if not all(it["item_status"] in {"APPROVED", "REJECTED"} for it in items):
            raise_error(ERR_INVALID_STATE, "all plan items must be APPROVED or REJECTED")
        if not any(it["item_status"] == "APPROVED" for it in items):
            raise_error(ERR_INVALID_STATE, "at least one item must be APPROVED")
        for it in items:
            if it["item_status"] == "APPROVED":
                it["item_status"] = "PUBLISHED"
                bump_version(it)
        plan["status"] = "PUBLISHED"
        if plan["amendment_round"] == 0 and plan["published_at"] is None:
            plan["published_at"] = clock.now_iso()
        recompute_total_budget(plan)
        bump_version(plan)
        return plan
    if plan["status"] == "AMENDING":
        items = items_for_plan(plan_id)
        allowed = {"APPROVED", "REJECTED", "PUBLISHED", "EXECUTED", "CANCELLED"}
        if not all(it["item_status"] in allowed for it in items):
            raise_error(ERR_INVALID_STATE, "plan items must be in {APPROVED,REJECTED,PUBLISHED,EXECUTED,CANCELLED}")
        plan["status"] = "PUBLISHED"
        plan["amendment_round"] = int(plan["amendment_round"]) + 1
        recompute_total_budget(plan)
        bump_version(plan)
        return plan
    raise_error(ERR_INVALID_STATE, "plan cannot be published from current state")


def reject_plan(plan_id: str):
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "plan must be UNDER_REVIEW to reject")
    plan["status"] = "REJECTED"
    for it in items_for_plan(plan_id):
        if it["item_status"] in {"PROPOSED", "APPROVED"}:
            it["item_status"] = "REJECTED"
            bump_version(it)
    bump_version(plan)
    return plan


def begin_amendment(plan_id: str):
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "plan must be PUBLISHED to begin amendment")
    # Serializable read of related projects BEFORE writing
    for it in items_for_plan(plan_id):
        for pj in db.projects.values():
            if pj["plan_item_id"] == it["id"] and pj["project_status"] in ACTIVE_PROJECT_STATUSES:
                raise_error(ERR_PLAN_HAS_ACTIVE_PROJECT, "plan has an active project")
    plan["status"] = "AMENDING"
    bump_version(plan)
    return plan


def archive_plan(plan_id: str):
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "plan must be PUBLISHED to archive")
    terminal = {"EXECUTED", "CANCELLED", "REJECTED"}
    if not all(it["item_status"] in terminal for it in items_for_plan(plan_id)):
        raise_error(ERR_INVALID_STATE, "all plan items must be terminal")
    plan["status"] = "ARCHIVED"
    bump_version(plan)
    return plan
