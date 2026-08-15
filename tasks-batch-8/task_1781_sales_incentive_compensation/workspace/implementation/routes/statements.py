"""Payout statement routes: get, list, approve."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION
from middleware import authorized, check_rep_ownership
from response import success_object, success_list
from util import touch, serialize
from validate import parse_pagination, require_path_resource

bp = Blueprint("statements", __name__)

MANAGER_ONLY = ["CompManager"]
ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]


def _get_statement_rep_id(statement):
    """Get the rep_id for a statement via its assignment."""
    assignment = db["assignments"].get(statement["assignment_id"])
    return assignment["rep_id"] if assignment else None


@bp.route("/statements/<statementId>", methods=["GET"])
def get_statement(statementId):
    caller = authorized(ALL_ROLES)
    statement = require_path_resource("statements", statementId)
    if caller.role == "Rep":
        rep_id = _get_statement_rep_id(statement)
        if rep_id is None:
            raise_error(ERR_NOT_FOUND, "resource not found")
        check_rep_ownership(caller, rep_id)
    return success_object(serialize(statement))


@bp.route("/statements", methods=["GET"])
def list_statements():
    caller = authorized(ALL_ROLES)
    limit, offset = parse_pagination()

    items = list(db["statements"].values())

    # Rep callers: own statements only
    if caller.role == "Rep":
        own_assignment_ids = {
            a["id"] for a in db["assignments"].values()
            if a["rep_id"] == caller.user_id
        }
        items = [s for s in items if s["assignment_id"] in own_assignment_ids]

    # Filters
    assignment_id = request.args.get("assignment_id")
    period_index = request.args.get("period_index")
    status_filter = request.args.get("status")

    if assignment_id:
        items = [s for s in items if s["assignment_id"] == assignment_id]
    if period_index:
        try:
            pi = int(period_index)
            items = [s for s in items if s["period_index"] == pi]
        except (ValueError, TypeError):
            pass
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]

    items.sort(key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(s) for s in page], total, limit, offset)


@bp.route("/statements/<statementId>/approve", methods=["POST"])
def approve_statement(statementId):
    caller = authorized(MANAGER_ONLY)
    statement = require_path_resource("statements", statementId)

    if statement["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"statement is {statement['status']}, must be DRAFT")

    statement["status"] = "APPROVED"
    touch(statement)
    return success_object(serialize(statement))
