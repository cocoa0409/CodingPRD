"""Book item endpoints (PRD §3.8)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_item
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    sort_by_created_at,
)

bp = Blueprint("items", __name__)

GRADES = {"A", "B", "C"}


@bp.route("/library-network/book-items", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_items(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_item(i) for i in sort_by_created_at(list(db.book_items.values()))]
    items = apply_filters(items, ["batch_id", "box_id", "status", "category"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/book-items/<item_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_item(item_id: str, _user_id, _role):
    item = db.book_items.get(item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, "No book item with the given id")
    return success_object(serialize_item(item))


@bp.route("/library-network/book-items/<item_id>", methods=["PATCH"])
@require_roles("HubCoordinator", "NetworkAdmin")
def grade_item(item_id: str, _user_id, _role):
    item = db.book_items.get(item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, "No book item with the given id")
    # State precondition (stage 5): grading is permitted only while the book is
    # AVAILABLE and its batch is still RECEIVED.
    batch = db.batches.get(item["batch_id"])
    if item["status"] != "AVAILABLE" or batch is None or batch["status"] != "RECEIVED":
        raise_err(ERR_INVALID_STATE, "Item cannot be graded in its current state")
    grade = require_enum(get_json_body(), "condition_grade", GRADES)
    item["condition_grade"] = grade
    db.touch(item)
    return success_object(serialize_item(item))
