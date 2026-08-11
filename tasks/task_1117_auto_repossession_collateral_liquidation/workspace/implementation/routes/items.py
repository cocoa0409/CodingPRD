"""Personal property inventory, claims, returns, disposal (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint

from db import store, base_fields, touch, get_or_404, sorted_all, now
from errors import (
    ApiError, ERR_INVALID_ITEM_STATE, ERR_FORBIDDEN_OWNERSHIP,
    ERR_PROPERTY_RETENTION_ACTIVE,
)
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import item_out
from services import calc
from util import validate_body

bp = Blueprint("items", __name__)


def _secured_assignment(case_id):
    """The case's SECURED assignment (the agent holding custody), or None."""
    for a in store.repo_assignments.values():
        if a["recovery_case_id"] == case_id and a["status"] == "SECURED":
            return a
    return None


def _check_item_agent(item, user_id):
    assignment = _secured_assignment(item["recovery_case_id"])
    if assignment is None or assignment["agent_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Caller is not the agent of the case's SECURED assignment")


def _check_item_borrower(item, user_id):
    case = store.recovery_cases[item["recovery_case_id"]]
    loan = store.loan_accounts[case["loan_account_id"]]
    if loan["borrower_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Caller does not own the target case")


@bp.post("/recovery-cases/<cid>/personal-property-items")
def create_item(cid):
    user_id, _role = require_roles("RepoAgent")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    assignment = _secured_assignment(cid)
    if assignment is None or assignment["agent_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Caller is not the agent of the case's SECURED assignment")
    body = validate_body({
        "description": ("str", True, None),
        "estimated_value_cents": ("nonneg_int", False, None),
    })
    item = base_fields()
    item.update({
        "recovery_case_id": case["id"],
        "description": body["description"],
        "estimated_value_cents": body.get("estimated_value_cents", 0),
        "status": "INVENTORIED",
        "claimed_by_borrower_id": None,
        "_seq": store.next_seq(),
    })
    store.property_items[item["id"]] = item
    case["property_item_count"] += 1
    touch(case)
    return object_response(item_out(item), 201)


@bp.get("/recovery-cases/<cid>/personal-property-items")
def list_items(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.recovery_cases, cid, "RecoveryCase")
    rows = [i for i in sorted_all(store.property_items)
            if i["recovery_case_id"] == cid]
    return list_response(rows, item_out)


@bp.post("/personal-property-items/<iid>/claim")
def claim_item(iid):
    user_id, _role = require_roles("Borrower")
    item = get_or_404(store.property_items, iid, "PersonalPropertyItem")
    _check_item_borrower(item, user_id)
    validate_body({})
    if item["status"] != "INVENTORIED":
        raise ApiError(ERR_INVALID_ITEM_STATE, 409,
                       f"Item status {item['status']} does not permit claim")
    item["status"] = "CLAIMED"
    item["claimed_by_borrower_id"] = user_id
    touch(item)
    return object_response(item_out(item))


@bp.post("/personal-property-items/<iid>/unclaim")
def unclaim_item(iid):
    user_id, _role = require_roles("Borrower")
    item = get_or_404(store.property_items, iid, "PersonalPropertyItem")
    _check_item_borrower(item, user_id)
    validate_body({})
    if item["status"] != "CLAIMED":
        raise ApiError(ERR_INVALID_ITEM_STATE, 409,
                       f"Item status {item['status']} does not permit unclaim")
    if item["claimed_by_borrower_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Item was claimed by a different borrower")
    item["status"] = "INVENTORIED"
    item["claimed_by_borrower_id"] = None
    touch(item)
    return object_response(item_out(item))


@bp.post("/personal-property-items/<iid>/mark-returned")
def mark_returned(iid):
    user_id, _role = require_roles("RepoAgent")
    item = get_or_404(store.property_items, iid, "PersonalPropertyItem")
    _check_item_agent(item, user_id)
    validate_body({})
    if item["status"] != "CLAIMED":
        raise ApiError(ERR_INVALID_ITEM_STATE, 409,
                       f"Item status {item['status']} does not permit mark-returned")
    item["status"] = "RETURNED"
    touch(item)
    return object_response(item_out(item))


@bp.post("/personal-property-items/<iid>/dispose")
def dispose_item(iid):
    user_id, _role = require_roles("RepoAgent")
    item = get_or_404(store.property_items, iid, "PersonalPropertyItem")
    _check_item_agent(item, user_id)
    validate_body({})
    if item["status"] != "INVENTORIED":
        raise ApiError(ERR_INVALID_ITEM_STATE, 409,
                       f"Item status {item['status']} does not permit dispose")
    case = store.recovery_cases[item["recovery_case_id"]]
    retention_end = case["collateral_secured_at"] + timedelta(
        days=calc.PROPERTY_RETENTION_DAYS)
    if now() < retention_end:
        raise ApiError(ERR_PROPERTY_RETENTION_ACTIVE, 422,
                       "Property retention window is still active")
    item["status"] = "DISPOSED"
    touch(item)
    return object_response(item_out(item))
