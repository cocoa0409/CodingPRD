"""Accounts: opening, amendment and the credit posture (PRD 3.9)."""

from flask import Blueprint

from db import insert, store, touch
from errors import ApiError
from routes.common import authenticate, created, fetch, listing, ok, unique
from services import ledgers
from validators import json_body, opt_enum, opt_int, req_enum, req_int, req_str

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = ("DEALER", "BUILDER", "COMMERCIAL")
ACCOUNT_STATUSES = ("ACTIVE", "CREDIT_HOLD", "CLOSED")
LIVE_ORDER_STATUSES = ("SUBMITTED", "ALLOCATED", "BACKORDERED", "CUT")


@bp.post("/mill/accounts")
def open_account():
    authenticate(("MillPlanner", "PlantAdmin"))
    body = json_body()
    account_code = req_str(body, "account_code", minlen=3, maxlen=32)
    account_type = req_enum(body, "account_type", ACCOUNT_TYPES)
    credit_limit_cents = req_int(body, "credit_limit_cents", ge=0)

    unique("accounts", "account_code", account_code)

    account = insert(
        store.accounts,
        {
            "account_code": account_code,
            "account_type": account_type,
            "credit_limit_cents": credit_limit_cents,
            "credit_used_cents": 0,
            "status": "ACTIVE",
        },
    )
    return created("account", account)


@bp.patch("/mill/accounts/<account_id>")
def amend_account(account_id):
    authenticate(("MillPlanner", "PlantAdmin"))
    body = json_body()
    credit_limit_cents = opt_int(body, "credit_limit_cents", ge=0)
    status = opt_enum(body, "status", ACCOUNT_STATUSES)

    account = fetch("accounts", account_id)

    if account["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "A CLOSED account can no longer be amended")

    if status == "CLOSED":
        for order in ledgers.orders_of_account(account["id"]):
            if order["status"] in LIVE_ORDER_STATUSES:
                raise ApiError(
                    "ERR_ACCOUNT_HAS_OPEN_ORDERS",
                    "The account still holds open cut orders",
                )

    if credit_limit_cents is not None:
        account["credit_limit_cents"] = credit_limit_cents

    if status == "CLOSED":
        account["status"] = "CLOSED"
    else:
        # The posture is derived; amending the limit re-evaluates it immediately.
        ledgers.recompute_account(account)

    touch(account)
    return ok("account", account)


@bp.get("/mill/accounts/<account_id>")
def read_account(account_id):
    actor = authenticate(("MillPlanner", "PlantAdmin", "DealerBuyer"))
    if actor.role == "DealerBuyer" and actor.user_id != account_id:
        raise ApiError(
            "ERR_ACCOUNT_SCOPE_VIOLATION",
            "A DealerBuyer may only read its own account",
        )
    account = fetch("accounts", account_id)
    return ok("account", account)


@bp.get("/mill/accounts")
def list_accounts():
    authenticate(("MillPlanner", "PlantAdmin"))
    return listing(
        "account",
        "accounts",
        enum_filters={"account_type": ACCOUNT_TYPES, "status": ACCOUNT_STATUSES},
    )
