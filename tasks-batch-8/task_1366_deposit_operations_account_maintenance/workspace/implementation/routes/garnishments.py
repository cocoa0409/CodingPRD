"""GarnishmentOrder endpoints (PRD §3.5): atomic hold placement with
exempt-funds analysis, and the branching REMITTED / RELEASED resolution.
"""

from datetime import date, timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_AMOUNT_EXCEEDS_COLLECTIBLE,
    ERR_ANSWER_PERIOD_NOT_ELAPSED,
    ERR_DATE_RANGE_INVALID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LEGAL_ORDER_WINDOW_CONFLICT,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles
from response import paginate, parse_pagination, success_list, success_object
from serialization import garnishment_view
from services.account import (
    derived_totals,
    get_account_or_404,
    post_transaction,
    refresh_restriction,
    touch_account,
    touch_resource,
)

bp = Blueprint("garnishments", __name__)

ORDER_TYPES = {"GARNISHMENT", "TAX_LEVY", "CHILD_SUPPORT"}
EXEMPTION_METHODS = {"FEDERAL_LOOKBACK", "STATE_MINIMUM"}

LOOKBACK_DAYS = 60
ANSWER_PERIOD_DAYS = 20
STATE_EXEMPT_FLOOR_CENTS = 100000


def _get_order_or_404(order_id):
    order = db.garnishments.get(order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, f"Garnishment order {order_id} does not exist")
    return order


@bp.post("/bank/accounts/<account_id>/garnishments")
def register_garnishment(account_id):
    user_id, _ = require_roles(["OpsOfficer"])
    acct = get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    order_type = body.get("order_type")
    if order_type not in ORDER_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "order_type must be a declared member")
    creditor_name = body.get("creditor_name")
    if not isinstance(creditor_name, str) or not creditor_name.strip():
        raise ApiError(ERR_INVALID_REQUEST, "creditor_name is required")
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be a positive integer")
    served_raw = body.get("served_date")
    if not isinstance(served_raw, str):
        raise ApiError(ERR_INVALID_REQUEST, "served_date is required")
    try:
        served = date.fromisoformat(served_raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "served_date must be a YYYY-MM-DD date")
    exemption_method = body.get("exemption_method")
    if exemption_method not in EXEMPTION_METHODS:
        raise ApiError(ERR_INVALID_REQUEST, "exemption_method must be a declared member")

    # Tier 7: closed service window [served_date, answer_deadline_date] must
    # not overlap the window of another FUNDS_HELD order on the account.
    deadline = served + timedelta(days=ANSWER_PERIOD_DAYS)
    for other in db.garnishments.values():
        if other["account_id"] == account_id and other["status"] == "FUNDS_HELD":
            o_start = date.fromisoformat(other["served_date"])
            o_end = date.fromisoformat(other["answer_deadline_date"])
            if served <= o_end and deadline >= o_start:
                raise ApiError(
                    ERR_LEGAL_ORDER_WINDOW_CONFLICT,
                    "Service window overlaps another order holding funds on this account",
                )

    # Tier 8: service cannot be future-dated.
    if served > db.clock_instant().date():
        raise ApiError(ERR_DATE_RANGE_INVALID, "served_date is in the future")

    # exempt_funds_analysis (SCAFFOLD §1.3) — runs atomically at receipt.
    balance = acct["balance_cents"]
    _, available = derived_totals(account_id)
    held = min(amount, available)

    lookback_start = served - timedelta(days=LOOKBACK_DAYS)
    benefit_total = 0
    for t in db.transactions.values():
        if t["account_id"] != account_id or t["txn_type"] != "FEDERAL_BENEFIT_DEPOSIT":
            continue
        posted = date.fromisoformat(t["posted_date"])
        if lookback_start <= posted <= served:  # closed window, both ends inclusive
            benefit_total += t["amount_cents"]

    if exemption_method == "FEDERAL_LOOKBACK":
        exempt = min(balance, benefit_total)
    else:  # STATE_MINIMUM — statutory floor of $1000
        exempt = min(balance, max(STATE_EXEMPT_FLOOR_CENTS, benefit_total))
    collectible = max(0, held - exempt)

    order = {
        "id": db.new_uuid(),
        "account_id": account_id,
        "order_type": order_type,
        "creditor_name": creditor_name,
        "amount_cents": amount,
        "served_date": served.isoformat(),
        "answer_deadline_date": deadline.isoformat(),
        "exemption_method": exemption_method,
        "held_amount_cents": held,
        "exempt_amount_cents": exempt,
        "collectible_cents": collectible,
        "remitted_amount_cents": 0,
        "released_amount_cents": 0,
        "received_by_user_id": user_id,
        "resolved_by_user_id": None,
        "status": "FUNDS_HELD",
        "created_at": db.now_timestamp(),
        "updated_at": db.now_timestamp(),
        "version": 1,
        "_seq": db.next_creation_seq(),
    }
    db.garnishments[order["id"]] = order

    # Hold placed atomically: restriction NONE -> LEGAL_HOLD (PRD §3.5).
    acct["restriction_status"] = "LEGAL_HOLD"
    touch_account(acct)
    return success_object(garnishment_view(order), status=201)


@bp.post("/bank/garnishments/<order_id>/resolve")
def resolve_garnishment(order_id):
    user_id, _ = require_roles(["OpsManager"])
    order = _get_order_or_404(order_id)
    acct = get_account_or_404(order["account_id"])
    body = request.get_json(silent=True) or {}

    resolution = body.get("resolution")
    if resolution not in ("REMITTED", "RELEASED"):
        raise ApiError(ERR_INVALID_REQUEST, "resolution must be REMITTED or RELEASED")
    remit_override = body.get("remit_amount_cents")
    if remit_override is not None:
        if not isinstance(remit_override, int) or isinstance(remit_override, bool) or remit_override < 0:
            raise ApiError(ERR_INVALID_REQUEST, "remit_amount_cents must be a non-negative integer")

    if order["status"] != "FUNDS_HELD":
        raise ApiError(ERR_INVALID_STATE, "Only a FUNDS_HELD order can be resolved")
    if user_id == order["received_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Resolver cannot be the receiving officer")

    if resolution == "REMITTED":
        # The answer period must have fully elapsed: today strictly after the deadline.
        if db.clock_instant().date() <= date.fromisoformat(order["answer_deadline_date"]):
            raise ApiError(ERR_ANSWER_PERIOD_NOT_ELAPSED, "The answer period has not elapsed")
        remit = remit_override if remit_override is not None else order["collectible_cents"]
        if remit > order["collectible_cents"]:
            raise ApiError(ERR_AMOUNT_EXCEEDS_COLLECTIBLE, "remit_amount_cents exceeds collectible_cents")
        if remit > 0:
            post_transaction(
                acct, "LEGAL_REMITTANCE", remit, False, db.clock_date_str()
            )
        order["status"] = "REMITTED"
        order["remitted_amount_cents"] = remit
        order["released_amount_cents"] = order["held_amount_cents"] - remit
    else:
        # RELEASED: no ledger transaction; the entire hold returns.
        order["status"] = "RELEASED"
        order["released_amount_cents"] = order["held_amount_cents"]
        # remitted_amount_cents stays 0

    order["resolved_by_user_id"] = user_id
    touch_resource(order)

    refresh_restriction(order["account_id"])  # -> NONE when the last hold clears
    touch_account(acct)
    return success_object(garnishment_view(order))


@bp.get("/bank/accounts/<account_id>/garnishments")
def list_garnishments(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    get_account_or_404(account_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")

    items = [g for g in db.garnishments.values() if g["account_id"] == account_id]
    items.sort(key=lambda g: g["_seq"])
    if status is not None:
        items = [g for g in items if g["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([garnishment_view(g) for g in page], total, limit, offset)
