"""Cash movements (PRD 3.9): OCC-guarded; deposits/journal credits cure
satisfied OPEN calls with cure_method DEPOSIT."""
from flask import Blueprint

from authz import ANY_ROLE, CUSTOMER, check_customer_ownership, require_roles
from calc import binding_official_excess, recompute_account
from cascades import cure_open_calls, posture_recheck
from db import store
from errors import (
    account_closed,
    account_restricted,
    cash_movement_not_found,
    insufficient_cash,
    maintenance_excess_negative,
    stale_version,
)
from response import success
from serialize import ser_cash_movement
from store_ops import (
    json_body,
    new_id,
    paginate,
    req_enum,
    req_int,
    req_positive_int,
    sorted_by_creation,
    stamp_new,
    touch,
)
from routes.accounts import get_account_or_404

bp = Blueprint("cash", __name__)

MOVEMENT_TYPES = ("DEPOSIT", "WITHDRAWAL", "JOURNAL_CREDIT", "JOURNAL_DEBIT")
_CREDITS = ("DEPOSIT", "JOURNAL_CREDIT")


@bp.route("/margin/accounts/<aid>/cash-movements", methods=["POST"])
def create_cash_movement(aid):
    data = json_body()
    movement_type = req_enum(data, "movement_type", MOVEMENT_TYPES)
    amount = req_positive_int(data, "amount_cents")
    expected_version = req_int(data, "expected_account_version")
    uid, _ = require_roles([CUSTOMER])
    account = get_account_or_404(aid)
    check_customer_ownership(uid, account["customer_id"])
    # OCC on the parent account (PRD 2.8), before state/fiscal evaluation.
    if expected_version != account["version"]:
        raise stale_version()
    if account["account_status"] == "CLOSED":
        raise account_closed()
    is_credit = movement_type in _CREDITS
    # Priority 5: withdrawals and journal debits require ACTIVE posture;
    # deposits and journal credits are permitted on any non-CLOSED account.
    if not is_credit and account["account_status"] == "RESTRICTED":
        raise account_restricted()
    if not is_credit:
        # Priority 10: cash sufficiency, then the maintenance-excess floor.
        if amount > account["cash_balance_cents"]:
            raise insufficient_cash()
        new_cash = account["cash_balance_cents"] - amount
        new_equity_official = (account["equity_official_cents"]
                               - account["cash_balance_cents"] + new_cash)
        binding = new_equity_official - max(account["reg_req_official_cents"],
                                            account["house_req_official_cents"])
        if binding < 0:
            raise maintenance_excess_negative()

    account["cash_balance_cents"] += amount if is_credit else -amount
    movement = {
        "id": new_id(),
        "account_id": aid,
        "movement_type": movement_type,
        "amount_cents": amount,
        "resulting_cash_balance_cents": account["cash_balance_cents"],
    }
    stamp_new(movement)
    store.cash_movements[movement["id"]] = movement

    # One mutation: cash applied + derived fields recomputed on both bases.
    recompute_account(account)
    touch(account)
    # A deposit or journal credit that satisfies an OPEN call's cure test
    # resolves it with cure_method DEPOSIT, then the posture recheck runs.
    if is_credit:
        cure_open_calls(account, "DEPOSIT")
    return success(ser_cash_movement(movement), status=201)


@bp.route("/margin/accounts/<aid>/cash-movements", methods=["GET"])
def list_account_cash_movements(aid):
    require_roles(ANY_ROLE)
    get_account_or_404(aid)
    items = sorted_by_creation(
        [m for m in store.cash_movements.values() if m["account_id"] == aid])
    page, pagination = paginate(items)
    return success([ser_cash_movement(m) for m in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/cash-movements/<mid>", methods=["GET"])
def get_cash_movement(mid):
    require_roles(ANY_ROLE)
    movement = store.cash_movements.get(mid)
    if movement is None:
        raise cash_movement_not_found()
    return success(ser_cash_movement(movement))
