"""FleetAccount and FleetCard endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

from db import STORE, new_id, now_utc, date_str
from errors import (
    ApiError,
    ERR_FLEET_ACCOUNT_NOT_FOUND,
    ERR_FLEET_CARD_NOT_FOUND,
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_ACCOUNT_NOT_SUSPENDED,
    ERR_OUTSTANDING_BALANCE_NONZERO,
    ERR_CARD_ALREADY_REVOKED,
    ERR_CARD_NUMBER_EXISTS,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_caller, require_role, check_account_ownership, check_card_ownership,
)
from response import success_object, success_list
from serializers import fleet_account_out, fleet_card_out
from services.core import touch
from validators import (
    body, require_fields, require_string, require_positive_int,
    require_positive_number, require_enum, parse_pagination, paginate,
)

bp = Blueprint("fleet", __name__)

_ACCOUNT_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer",
                 "FleetAccountManager", "FleetDriver"]
_CARD_READ = ["NetworkOperator", "StationManager", "FleetAccountManager", "FleetDriver"]


def get_account_or_404(aid: str) -> dict:
    a = STORE.fleet_accounts.get(aid)
    if a is None:
        raise ApiError(ERR_FLEET_ACCOUNT_NOT_FOUND, 404, "Fleet account id does not exist")
    return a


def get_card_or_404(cid: str) -> dict:
    c = STORE.fleet_cards.get(cid)
    if c is None:
        raise ApiError(ERR_FLEET_CARD_NOT_FOUND, 404, "Fleet card id does not exist")
    return c


# ---------------- Fleet accounts ----------------

@bp.post("/cng/fleet-accounts")
def create_fleet_account():
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    data = body()
    require_fields(data, ["account_name", "billing_email", "credit_limit_cents"])
    account_name = require_string(data, "account_name")
    billing_email = require_string(data, "billing_email")
    credit_limit = require_positive_int(data, "credit_limit_cents")
    now = now_utc()
    account = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "account_name": account_name,
        "billing_email": billing_email,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    }
    STORE.fleet_accounts[account["id"]] = account
    return success_object(fleet_account_out(account), status=201)


@bp.get("/cng/fleet-accounts")
def list_fleet_accounts():
    caller = get_caller()
    require_role(caller, _ACCOUNT_READ)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = sorted(STORE.fleet_accounts.values(), key=lambda a: (a["created_at"], a["id"]))
    if status is not None:
        items = [a for a in items if a["status"] == status]
    # Ownership scoping (PRD §2.10)
    if caller.role == "FleetAccountManager":
        items = [a for a in items if a["id"] == caller.user_id]
    elif caller.role == "FleetDriver":
        own_card = STORE.fleet_cards.get(caller.user_id)
        own_account_id = own_card["fleet_account_id"] if own_card else None
        items = [a for a in items if a["id"] == own_account_id]
    page, total = paginate(items, limit, offset)
    return success_list([fleet_account_out(a) for a in page], limit, offset, total)


@bp.get("/cng/fleet-accounts/<accountId>")
def get_fleet_account(accountId: str):
    caller = get_caller()
    require_role(caller, _ACCOUNT_READ)
    account = get_account_or_404(accountId)
    if caller.role == "FleetAccountManager":
        check_account_ownership(caller, accountId)
    elif caller.role == "FleetDriver":
        own_card = STORE.fleet_cards.get(caller.user_id)
        if own_card is None or own_card["fleet_account_id"] != accountId:
            raise ApiError(ERR_ACCOUNT_OWNERSHIP_MISMATCH, 403,
                           "FleetDriver may only view their own account")
    return success_object(fleet_account_out(account))


@bp.post("/cng/fleet-accounts/<accountId>/suspend")
def suspend_account(accountId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    account = get_account_or_404(accountId)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409,
                       "Account suspend requires ACTIVE status")
    account["status"] = "SUSPENDED"
    touch(account)
    return success_object(fleet_account_out(account))


@bp.post("/cng/fleet-accounts/<accountId>/resume")
def resume_account(accountId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    account = get_account_or_404(accountId)
    if account["status"] != "SUSPENDED":
        raise ApiError(ERR_ACCOUNT_NOT_SUSPENDED, 409,
                       "Account resume requires SUSPENDED status")
    account["status"] = "ACTIVE"
    touch(account)
    return success_object(fleet_account_out(account))


@bp.post("/cng/fleet-accounts/<accountId>/close")
def close_account(accountId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    account = get_account_or_404(accountId)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409,
                       "Account close requires ACTIVE status")
    if account["outstanding_balance_cents"] != 0:
        raise ApiError(ERR_OUTSTANDING_BALANCE_NONZERO, 409,
                       "Account close requires outstanding_balance_cents == 0")
    account["status"] = "CLOSED"
    touch(account)
    # Cascade: all non-REVOKED cards -> REVOKED
    for card in STORE.fleet_cards.values():
        if card["fleet_account_id"] == accountId and card["status"] != "REVOKED":
            card["status"] = "REVOKED"
            touch(card)
    return success_object(fleet_account_out(account))


# ---------------- Fleet cards ----------------

@bp.post("/cng/fleet-cards")
def create_fleet_card():
    caller = get_caller()
    require_role(caller, ["FleetAccountManager", "NetworkOperator"])
    data = body()
    require_fields(data, ["fleet_account_id", "card_number", "vehicle_plate", "daily_gge_limit"])
    fleet_account_id = require_string(data, "fleet_account_id")
    card_number = require_string(data, "card_number")
    vehicle_plate = require_string(data, "vehicle_plate")
    daily_gge_limit = require_positive_number(data, "daily_gge_limit")

    account = get_account_or_404(fleet_account_id)
    # Ownership (stage 5)
    check_account_ownership(caller, fleet_account_id)
    # State (stage 6)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409,
                       "Card issuance requires an ACTIVE account")
    # Uniqueness (stage 8)
    for c in STORE.fleet_cards.values():
        if c["card_number"] == card_number:
            raise ApiError(ERR_CARD_NUMBER_EXISTS, 409,
                           "card_number already registered")

    now = now_utc()
    card = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_account_id": fleet_account_id,
        "card_number": card_number,
        "vehicle_plate": vehicle_plate,
        "daily_gge_limit": daily_gge_limit,
        "status": "ACTIVE",
        "current_day_gge": Decimal("0"),
        "current_day_date": date_str(now),
    }
    STORE.fleet_cards[card["id"]] = card
    return success_object(fleet_card_out(card), status=201)


@bp.get("/cng/fleet-cards")
def list_fleet_cards():
    caller = get_caller()
    require_role(caller, _CARD_READ)
    limit, offset = parse_pagination()
    fleet_account_id = request.args.get("fleet_account_id")
    status = request.args.get("status")
    items = sorted(STORE.fleet_cards.values(), key=lambda c: (c["created_at"], c["id"]))
    if fleet_account_id is not None:
        items = [c for c in items if c["fleet_account_id"] == fleet_account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if caller.role == "FleetAccountManager":
        items = [c for c in items if c["fleet_account_id"] == caller.user_id]
    elif caller.role == "FleetDriver":
        items = [c for c in items if c["id"] == caller.user_id]
    page, total = paginate(items, limit, offset)
    return success_list([fleet_card_out(c) for c in page], limit, offset, total)


@bp.get("/cng/fleet-cards/<cardId>")
def get_fleet_card(cardId: str):
    caller = get_caller()
    require_role(caller, _CARD_READ)
    card = get_card_or_404(cardId)
    if caller.role == "FleetAccountManager":
        check_account_ownership(caller, card["fleet_account_id"])
    elif caller.role == "FleetDriver":
        check_card_ownership(caller, cardId)
    return success_object(fleet_card_out(card))


@bp.post("/cng/fleet-cards/<cardId>/set-status")
def set_card_status(cardId: str):
    caller = get_caller()
    require_role(caller, ["FleetAccountManager", "NetworkOperator"])
    data = body()
    require_fields(data, ["to_status"])
    to_status = require_enum(data, "to_status", {"ACTIVE", "SUSPENDED", "REVOKED"})
    card = get_card_or_404(cardId)
    # Ownership (stage 5)
    if caller.role == "FleetAccountManager":
        check_account_ownership(caller, card["fleet_account_id"])
    # State (stage 6)
    if card["status"] == "REVOKED":
        raise ApiError(ERR_CARD_ALREADY_REVOKED, 409,
                       "Card is already REVOKED")
    allowed = {
        "ACTIVE": {"SUSPENDED", "REVOKED"},
        "SUSPENDED": {"ACTIVE", "REVOKED"},
    }
    if to_status not in allowed.get(card["status"], set()):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Cannot transition card from {card['status']} to {to_status}")
    if to_status == "ACTIVE":
        account = STORE.fleet_accounts.get(card["fleet_account_id"])
        if account is None or account["status"] != "ACTIVE":
            raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409,
                           "Resuming a card requires its account to be ACTIVE")
    card["status"] = to_status
    touch(card)
    return success_object(fleet_card_out(card))
