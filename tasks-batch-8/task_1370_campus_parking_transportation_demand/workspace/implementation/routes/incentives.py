"""Incentive account endpoints."""
from flask import Blueprint, request

import db
from errors import (
    bad_request,
    not_found,
    conflict,
    forbidden,
    unprocessable,
    ERR_PATRON_NOT_FOUND,
    ERR_INCENTIVE_ACCOUNT_NOT_FOUND,
    ERR_INELIGIBLE_COMMUTE_MODE,
    ERR_ACCOUNT_EXISTS,
    ERR_INSUFFICIENT_POINTS,
)
from middleware import get_caller, require_roles, require_ownership, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import (
    new_record,
    serialize,
    touch,
    POINTS_PER_DAY,
    REDEMPTION_BLOCK_POINTS,
    REDEMPTION_BLOCK_CREDIT_CENTS,
)

bp = Blueprint("incentives", __name__)


def _get_account_or_404(account_id: str) -> dict:
    record = db.incentive_accounts.get(account_id)
    if record is None:
        raise not_found(ERR_INCENTIVE_ACCOUNT_NOT_FOUND, "No incentive account with the given id")
    return record


@bp.post("/parking/incentive-accounts")
def enroll():
    caller = get_caller()
    require_roles(caller, ["Commuter"])
    body = request.get_json(silent=True) or {}

    patron_id = body.get("patron_id")
    if not isinstance(patron_id, str) or not patron_id:
        raise bad_request("patron_id is required")

    # Ownership (priority 3)
    require_ownership(caller, patron_id)

    # Existence (priority 4)
    patron = db.patrons.get(patron_id)
    if patron is None:
        raise not_found(ERR_PATRON_NOT_FOUND, "No patron with the given id")

    # Eligibility (priority 10)
    if patron["primary_commute_mode"] == "DRIVE_ALONE":
        raise forbidden(
            ERR_INELIGIBLE_COMMUTE_MODE,
            "DRIVE_ALONE patrons are ineligible for the incentive program",
        )

    # Uniqueness (priority 11)
    for acct in db.incentive_accounts.values():
        if acct["patron_id"] == patron_id:
            raise conflict(ERR_ACCOUNT_EXISTS, "Patron already has an incentive account")

    record = new_record()
    record.update(
        patron_id=patron_id,
        points_balance=0,
        lifetime_points=0,
        credit_balance_cents=0,
    )
    db.incentive_accounts[record["id"]] = record
    return success(serialize(record), 201)


@bp.get("/parking/incentive-accounts")
def list_accounts():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    patron_id = request.args.get("patron_id")
    items = list(db.incentive_accounts.values())
    if patron_id is not None:
        items = [a for a in items if a["patron_id"] == patron_id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(a) for a in page], limit, offset, total)


@bp.get("/parking/incentive-accounts/<accountId>")
def get_account(accountId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = _get_account_or_404(accountId)
    return success(serialize(record), 200)


@bp.post("/parking/incentive-accounts/<accountId>/accruals")
def post_accrual(accountId):
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    record = _get_account_or_404(accountId)
    body = request.get_json(silent=True) or {}

    days = body.get("days_commuted")
    if not isinstance(days, int) or isinstance(days, bool) or not (1 <= days <= 31):
        raise bad_request("days_commuted must be an integer in 1..31")

    points = days * POINTS_PER_DAY
    record["points_balance"] += points
    record["lifetime_points"] += points
    touch(record)
    return success(serialize(record), 201)


@bp.post("/parking/incentive-accounts/<accountId>/redeem")
def redeem(accountId):
    caller = get_caller()
    require_roles(caller, ["Commuter"])
    record = _get_account_or_404(accountId)

    # Ownership (priority 3)
    require_ownership(caller, record["patron_id"])

    body = request.get_json(silent=True) or {}
    blocks = body.get("blocks")
    if not isinstance(blocks, int) or isinstance(blocks, bool) or blocks < 1:
        raise bad_request("blocks must be an integer >= 1")

    needed = blocks * REDEMPTION_BLOCK_POINTS
    if record["points_balance"] < needed:
        raise unprocessable(ERR_INSUFFICIENT_POINTS, "points_balance < blocks * 500")

    record["points_balance"] -= needed
    record["credit_balance_cents"] += blocks * REDEMPTION_BLOCK_CREDIT_CENTS
    touch(record)
    return success(serialize(record), 200)
