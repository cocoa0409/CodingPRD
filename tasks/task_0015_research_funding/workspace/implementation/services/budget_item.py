"""BudgetItem — created during DRAFT, approved at project approval, locked at CLOSING."""

from decimal import Decimal

from common import (
    money_to_json,
    require_field,
    round_money,
    sort_by_created_at,
    stamp_create,
    to_decimal,
)
from db import db
from errors import (
    ERR_BUDGET_ITEM_NOT_FOUND,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_PROJECT_OWNER,
    raise_error,
)


VALID_CATEGORIES = {"PERSONNEL", "EQUIPMENT", "MATERIALS", "TRAVEL", "CONFERENCE", "OUTSOURCING"}


def get_budget_item_or_404(item_id):
    bi = db.budget_items.get(item_id)
    if bi is None:
        raise_error(ERR_BUDGET_ITEM_NOT_FOUND, f"budget item {item_id} not found")
    return bi


def serialize_item(bi):
    return {
        "id": bi["id"],
        "project_id": bi["project_id"],
        "category": bi["category"],
        "requested_amount": money_to_json(bi["requested_amount"]),
        "approved_amount": money_to_json(bi["approved_amount"]) if bi["approved_amount"] is not None else None,
        "spent_amount": money_to_json(bi["spent_amount"]),
        "remaining_amount": money_to_json(bi["remaining_amount"]) if bi["remaining_amount"] is not None else None,
        "status": bi["status"],
        "created_at": bi["created_at"],
        "updated_at": bi["updated_at"],
        "version": bi["version"],
    }


def create_budget_item(project, actor_id, body):
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can add budget items")
    if project["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"project must be DRAFT to add budget items (got {project['status']})")
    category = require_field(body, "category", str)
    if category not in VALID_CATEGORIES:
        raise_error(ERR_INVALID_INPUT, "invalid category")
    requested_amount = round_money(to_decimal(require_field(body, "requested_amount")))
    if requested_amount <= 0:
        raise_error(ERR_INVALID_INPUT, "requested_amount must be > 0")

    bid = db.new_id()
    bi = {
        "id": bid,
        "project_id": project["id"],
        "category": category,
        "requested_amount": requested_amount,
        "approved_amount": None,
        "spent_amount": Decimal("0.00"),
        "remaining_amount": None,
        "status": "PENDING",
    }
    stamp_create(bi)
    db.budget_items[bid] = bi
    return bi


def list_budget_items(project_id):
    items = [bi for bi in db.budget_items.values() if bi["project_id"] == project_id]
    return sort_by_created_at(items)
