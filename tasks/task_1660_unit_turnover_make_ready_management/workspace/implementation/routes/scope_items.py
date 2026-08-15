"""Scope item endpoints: add, approve, reject, void (PRD §3.2, §3.5)."""
from flask import Blueprint, g

import db
import services
from db import store
from errors import ApiError
from middleware import authenticate, require_roles
from response import created, ok, paged
from validation import get_body, validate_schema

bp = Blueprint("scope_items", __name__)

READ_ROLES = ["RegionalManager", "PropertyManager", "TurnCoordinator",
              "Inspector"]
MANAGER_ROLES = ["PropertyManager", "RegionalManager"]

SCOPE_ITEM_SCHEMA = {
    "turn_id": ("string", True, None),
    "category": ("enum", True, ["REPAIR", "PAINT", "CARPET", "CLEAN",
                                "APPLIANCE", "FIXTURE", "OTHER"]),
    "description": ("string", True, None),
    "estimated_cost_cents": ("integer", True, None),
}

APPROVE_SCHEMA = {
    "expected_turn_version": ("integer", True, None),
}

SCOPE_ITEM_CATEGORIES = list(SCOPE_ITEM_SCHEMA["category"][2])


def _get_item_or_404(item_id):
    item = store.scope_items.get(item_id)
    if item is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Scope item not found")
    return item


def _check_tier_authority(item):
    """PRD §3.5: PM-tier admits PM or RM; RM-tier admits only RegionalManager."""
    if item["approval_tier"] == "RM" and g.user_role != "RegionalManager":
        raise ApiError("ERR_APPROVAL_AUTHORITY_EXCEEDED", 403,
                       "RM-tier items admit only a RegionalManager")


@bp.post("/make-ready/scope-items")
def create_scope_item():
    authenticate()
    require_roles(["TurnCoordinator"])
    body = get_body()
    validate_schema(body, SCOPE_ITEM_SCHEMA)
    turn = store.turns.get(body["turn_id"])
    if turn is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Turn not found")
    if turn["status"] not in ("OPEN", "SCOPED", "IN_PROGRESS", "REWORK"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Scope items may be added only while the turn is OPEN, "
                       "SCOPED, IN_PROGRESS, or REWORK")
    if turn["status"] == "OPEN":
        tier = "NONE"
        status = "PLANNED"
    else:
        tier = services.scope_creep_tier(turn, body["estimated_cost_cents"])
        status = "PLANNED" if tier == "NONE" else "PENDING_APPROVAL"
    item = {
        "id": db.new_id(),
        "turn_id": body["turn_id"],
        "category": body["category"],
        "description": body["description"],
        "estimated_cost_cents": body["estimated_cost_cents"],
        "actual_cost_cents": None,
        "classification": "EXPENSE",
        "sequence_rank": services.SEQUENCE_RANK[body["category"]],
        "approval_tier": tier,
        "status": status,
        "rework_of_item_id": None,
    }
    db.new_common(item)
    store.scope_items[item["id"]] = item
    if status == "PLANNED":
        # Auto-approved items immediately recompute estimate and projection.
        services.sync_turn(turn)
    return created(item)


@bp.get("/make-ready/scope-items/<item_id>")
def get_scope_item(item_id):
    authenticate()
    require_roles(READ_ROLES)
    return ok(_get_item_or_404(item_id))


@bp.get("/make-ready/scope-items")
def list_scope_items():
    authenticate()
    require_roles(READ_ROLES)
    page, pg = paged(list(store.scope_items.values()),
                     ("turn_id", "rework_of_item_id", "status"))
    return ok(page, rtype="array", pagination=pg)


@bp.post("/make-ready/scope-items/<item_id>/approve")
def approve_scope_item(item_id):
    authenticate()
    require_roles(MANAGER_ROLES)
    body = get_body()
    validate_schema(body, APPROVE_SCHEMA)
    item = _get_item_or_404(item_id)
    if item["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PENDING_APPROVAL item can be approved")
    turn = store.turns[item["turn_id"]]
    # OCC (PRD §2.9): evaluated after state, before approval authority.
    if body["expected_turn_version"] != turn["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_turn_version does not match the turn's "
                       "current version")
    _check_tier_authority(item)
    item["status"] = "PLANNED"
    db.touch(item)
    turn["approved_budget_cents"] += item["estimated_cost_cents"]
    db.touch(turn)  # version += 1 (PRD §3.5)
    services.sync_turn(turn)
    return ok(item)


@bp.post("/make-ready/scope-items/<item_id>/reject")
def reject_scope_item(item_id):
    authenticate()
    require_roles(MANAGER_ROLES)
    validate_schema(get_body(), {})
    item = _get_item_or_404(item_id)
    if item["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PENDING_APPROVAL item can be rejected")
    _check_tier_authority(item)
    item["status"] = "REJECTED"
    db.touch(item)
    turn = store.turns[item["turn_id"]]
    services.sync_turn(turn)
    return ok(item)


@bp.post("/make-ready/scope-items/<item_id>/void")
def void_scope_item(item_id):
    authenticate()
    require_roles(["TurnCoordinator"])
    validate_schema(get_body(), {})
    item = _get_item_or_404(item_id)
    if item["status"] not in ("PLANNED", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PLANNED or SCHEDULED item can be voided")
    if item["status"] == "SCHEDULED":
        services.cancel_item_assignments(item)
    item["status"] = "VOIDED"
    db.touch(item)
    turn = store.turns[item["turn_id"]]
    services.sync_turn(turn)
    return ok(item)


@bp.get("/make-ready/scope-items/<item_id>/replacement-decisions")
def list_item_replacement_decisions(item_id):
    authenticate()
    require_roles(["RegionalManager", "PropertyManager", "TurnCoordinator"])
    _get_item_or_404(item_id)
    rows = [d for d in store.decisions.values()
            if d["scope_item_id"] == item_id]
    page, pg = paged(rows)
    return ok(page, rtype="array", pagination=pg)
