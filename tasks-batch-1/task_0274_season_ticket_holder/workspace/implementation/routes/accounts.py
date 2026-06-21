"""Accounts: register, fetch, list, suspend, grant-points, reverse subscription list."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (
    account_view,
    get_json_body,
    get_or_404,
    optional_int,
    paginate,
    require_int,
    require_str,
    subscription_view,
)
from middleware import get_auth, require_role
from response import success, success_list

bp = Blueprint("accounts", __name__)

ALL_ROLES = {"BoxOfficeAgent", "AccountHolder", "FinanceClerk"}


@bp.route("/accounts", methods=["POST"])
def create_account():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    consecutive = optional_int(body, "consecutive_seasons", default=0, minimum=0)
    with db.lock:
        # Email uniqueness across accounts.
        for a in db.accounts.values():
            if a["email"] == email:
                raise err("ERR_INVALID_REQUEST", "email must be unique")
        row = db.new_common()
        row.update(
            {
                "full_name": full_name,
                "email": email,
                "consecutive_seasons": consecutive,
                "priority_points": 0,
                "status": "ACTIVE",
            }
        )
        db.accounts[row["id"]] = row
        return success(account_view(row), 201)


@bp.route("/accounts/<rid>", methods=["GET"])
def get_account(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        row = get_or_404(db.accounts, rid)
        return success(account_view(row))


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent", "FinanceClerk"})
    with db.lock:
        rows = list(db.accounts.values())
        page, limit, offset, total = paginate(rows)
        return success_list([account_view(r) for r in page], limit, offset, total)


@bp.route("/accounts/<rid>/suspend", methods=["POST"])
def suspend_account(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    with db.lock:
        row = get_or_404(db.accounts, rid)
        row["status"] = "SUSPENDED"
        db.touch(row)
        return success(account_view(row))


@bp.route("/accounts/<rid>/subscriptions", methods=["GET"])
def list_account_subscriptions(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    status = request.args.get("status")
    with db.lock:
        get_or_404(db.accounts, rid)
        rows = [
            s
            for s in db.subscriptions.values()
            if s["account_id"] == rid and (status is None or s["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([subscription_view(r) for r in page], limit, offset, total)


@bp.route("/_accounts/<rid>/grant-points", methods=["POST"])
def grant_points(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    with db.lock:
        row = get_or_404(db.accounts, rid)
        body = get_json_body()
        points = require_int(body, "priority_points")
        row["priority_points"] = points
        db.touch(row)
        return success(account_view(row))
