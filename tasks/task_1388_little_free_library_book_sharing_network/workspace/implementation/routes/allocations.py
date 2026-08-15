"""Allocation endpoints (PRD §3.8)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_STATE,
    ERR_STEWARD_NOT_ACTIVE,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_allocation
from util import (
    apply_filters,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("allocations", __name__)


def _load_allocation(allocation_id: str) -> dict:
    alloc = db.allocations.get(allocation_id)
    if alloc is None:
        raise_err(ERR_ALLOCATION_NOT_FOUND, "No allocation with the given id")
    return alloc


@bp.route("/library-network/allocations", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_allocations(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_allocation(a) for a in sort_by_created_at(list(db.allocations.values()))]
    items = apply_filters(items, ["run_id", "box_id", "book_item_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/allocations/<allocation_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_allocation(allocation_id: str, _user_id, _role):
    return success_object(serialize_allocation(_load_allocation(allocation_id)))


@bp.route("/library-network/allocations/<allocation_id>/receive", methods=["POST"])
@require_roles("Steward", "NetworkAdmin")
def receive_allocation(allocation_id: str, _user_id, _role):
    alloc = _load_allocation(allocation_id)
    box = db.boxes.get(alloc["box_id"])

    # Ownership (stage 2): a steward actor must own the destination box.
    if _role == "Steward" and (box is None or box["steward_id"] != _user_id):
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only receive allocations for their own box")

    # State precondition (stage 5).
    if alloc["status"] != "DISPATCHED":
        raise_err(ERR_INVALID_STATE, "Allocation is not in DISPATCHED status")

    # Cross-entity gate (stage 6): the box's steward must be ACTIVE.
    steward = db.stewards.get(box["steward_id"]) if box is not None else None
    if steward is None or steward["status"] != "ACTIVE":
        raise_err(ERR_STEWARD_NOT_ACTIVE, "The destination box steward is not ACTIVE")

    alloc["status"] = "PLACED"
    alloc["placed_at"] = db.now_logical_iso()
    db.touch(alloc)

    item = db.book_items.get(alloc["book_item_id"])
    if item is not None:
        item["status"] = "PLACED"
        db.touch(item)
        domain.bubble_up_batch(item["batch_id"])

    if box is not None:
        # +5 ALLOCATION_PLACED for the box steward; activity refresh resets
        # staleness; posture recomputes.
        domain.add_recognition_event(
            box["steward_id"], "ALLOCATION_PLACED", 5, "ALLOCATION", alloc["id"]
        )
        domain.refresh_box_activity(box)

    domain.bubble_up_run(alloc["run_id"])
    return success_object(serialize_allocation(alloc))


@bp.route("/library-network/allocations/<allocation_id>/cancel", methods=["POST"])
@require_roles("HubCoordinator", "NetworkAdmin")
def cancel_allocation(allocation_id: str, _user_id, _role):
    alloc = _load_allocation(allocation_id)
    if alloc["status"] not in ("RESERVED", "DISPATCHED"):
        raise_err(ERR_INVALID_STATE, "Allocation is not RESERVED or DISPATCHED")
    domain._cancel_allocation(alloc)
    domain.bubble_up_run(alloc["run_id"])
    return success_object(serialize_allocation(alloc))
