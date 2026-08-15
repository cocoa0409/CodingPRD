"""Credit entry routes: get, list."""
from flask import Blueprint, request

from db import db
from middleware import authorized, check_rep_ownership
from response import success_object, success_list
from util import serialize
from validate import parse_pagination, require_path_resource

bp = Blueprint("credit_entries", __name__)

ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]


@bp.route("/credit-entries/<creditEntryId>", methods=["GET"])
def get_credit_entry(creditEntryId):
    caller = authorized(ALL_ROLES)
    entry = require_path_resource("credit_entries", creditEntryId)
    check_rep_ownership(caller, entry["rep_id"])
    return success_object(serialize(entry))


@bp.route("/credit-entries", methods=["GET"])
def list_credit_entries():
    caller = authorized(ALL_ROLES)
    limit, offset = parse_pagination()

    items = list(db["credit_entries"].values())

    # Rep callers: own credits only
    if caller.role == "Rep":
        items = [c for c in items if c["rep_id"] == caller.user_id]

    # Filters
    transaction_id = request.args.get("transaction_id")
    assignment_id = request.args.get("assignment_id")
    rep_id = request.args.get("rep_id")
    parent_credit_id = request.args.get("parent_credit_id")
    status_filter = request.args.get("status")

    if transaction_id:
        items = [c for c in items if c["transaction_id"] == transaction_id]
    if assignment_id:
        items = [c for c in items if c["assignment_id"] == assignment_id]
    if rep_id:
        items = [c for c in items if c["rep_id"] == rep_id]
    if parent_credit_id:
        items = [c for c in items if c.get("parent_credit_id") == parent_credit_id]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]

    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(c) for c in page], total, limit, offset)
