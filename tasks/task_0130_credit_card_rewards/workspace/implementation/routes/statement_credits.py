"""StatementCredit routes."""
from __future__ import annotations

from flask import Blueprint, g, request

from auth import require_roles
from constants import (
    MIN_REDEMPTION_CENTS,
    MIN_REDEMPTION_POINTS,
    ROLE_CARDHOLDER,
    ROLE_PLATFORM_ADMIN,
)
from errors import err
from response import ok_object
from serializers import statement_credit_view
from services.account import ownership_check
from services.ledger import append_entry, recompute_balance
from services.redemption import amount_first, points_first
from services.touch import touch_versioned
from store import store
from utils import fmt_iso, get_body, opt_int, require_str

bp = Blueprint("statement_credits", __name__)


_VALID_MODES = {"POINTS_FIRST", "AMOUNT_FIRST"}


@bp.post("/statement-credits")
@require_roles(ROLE_CARDHOLDER)
def post_credit():
    body = get_body(request)
    account_id = require_str(body, "account_id")
    redemption_mode = require_str(body, "redemption_mode")
    requested_points = opt_int(body, "requested_points")
    requested_amount_cents = opt_int(body, "requested_amount_cents")

    if redemption_mode not in _VALID_MODES:
        raise err(
            "ERR_VALIDATION",
            f"redemption_mode must be one of {sorted(_VALID_MODES)}",
        )

    # Body FK existence (priority 4)
    account = store.accounts.get(account_id)
    if account is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "account_id does not resolve")

    # Ownership (priority 5)
    ownership_check(account, g.user_id)

    # State: account ACTIVE (priority 6)
    if account["lifecycle_state"] == "CLOSED":
        raise err("ERR_ACCOUNT_CLOSED", "Account is closed")
    if account["lifecycle_state"] != "ACTIVE":
        raise err("ERR_ACCOUNT_CLOSED", f"Account not ACTIVE: {account['lifecycle_state']}")

    # ----- Business rules (priority 13 then 14) -----
    # The scaffold lists "below minimum" at priority 13 and "invalid body" at 14.
    # We follow the scaffold order, but: for clarity we still must first verify the
    # body fields are at all present in the correct mode so the minimum check has
    # a value to compare; we read the appropriate field and raise BELOW_MINIMUM
    # if too small, then INVALID_REDEMPTION_BODY if the exclusivity rule fails.
    if redemption_mode == "POINTS_FIRST":
        if requested_points is None:
            raise err(
                "ERR_INVALID_REDEMPTION_BODY",
                "POINTS_FIRST requires requested_points",
            )
        if requested_points < MIN_REDEMPTION_POINTS:
            raise err(
                "ERR_BELOW_MINIMUM_REDEMPTION",
                f"requested_points must be >= {MIN_REDEMPTION_POINTS}",
            )
        if requested_amount_cents is not None:
            raise err(
                "ERR_INVALID_REDEMPTION_BODY",
                "POINTS_FIRST must not include requested_amount_cents",
            )
        points_debited, credit_cents = points_first(
            requested_points, account["spending_tier"]
        )
    else:  # AMOUNT_FIRST
        if requested_amount_cents is None:
            raise err(
                "ERR_INVALID_REDEMPTION_BODY",
                "AMOUNT_FIRST requires requested_amount_cents",
            )
        if requested_amount_cents < MIN_REDEMPTION_CENTS:
            raise err(
                "ERR_BELOW_MINIMUM_REDEMPTION",
                f"requested_amount_cents must be >= {MIN_REDEMPTION_CENTS}",
            )
        if requested_points is not None:
            raise err(
                "ERR_INVALID_REDEMPTION_BODY",
                "AMOUNT_FIRST must not include requested_points",
            )
        points_debited, credit_cents = amount_first(
            requested_amount_cents, account["spending_tier"]
        )

    with store.lock:
        # Fiscal: sufficient balance (priority 15)
        if points_debited > int(account["points_balance"]):
            raise err(
                "ERR_INSUFFICIENT_POINTS",
                "points_debited exceeds account points_balance",
            )

        now = store.now()
        iso = fmt_iso(now)
        cid = store.new_id()
        rec = {
            "id": cid,
            "account_id": account_id,
            "redemption_mode": redemption_mode,
            "requested_points": requested_points,
            "requested_amount_cents": requested_amount_cents,
            "points_debited": points_debited,
            "credit_amount_cents": credit_cents,
            "applied_at": iso,
            "status": "APPLIED",
            "created_at": iso,
        }
        store.statement_credits[cid] = rec

        append_entry(
            account_id=account_id,
            entry_type="REDEEM_DEBIT",
            delta_points=-points_debited,
            source_entity_type="StatementCredit",
            source_entity_id=cid,
        )
        recompute_balance(account)
        account["last_qualifying_activity_at"] = iso
        touch_versioned(account)

    return ok_object(statement_credit_view(rec), status=201)


@bp.post("/statement-credits/<credit_id>/reverse")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_credit_reverse(credit_id: str):
    rec = store.statement_credits.get(credit_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "StatementCredit not found")

    account = store.accounts.get(rec["account_id"])
    if account is None:
        raise err("ERR_NOT_FOUND", "Account not found")

    with store.lock:
        if rec["status"] != "APPLIED":
            raise err("ERR_INVALID_STATE", f"StatementCredit status is {rec['status']}, not APPLIED")
        if account["lifecycle_state"] == "CLOSED":
            raise err("ERR_INVALID_STATE", "Account is closed")

        rec["status"] = "REVERSED"
        append_entry(
            account_id=account["id"],
            entry_type="REDEEM_REVERSE",
            delta_points=+int(rec["points_debited"]),
            source_entity_type="StatementCredit",
            source_entity_id=rec["id"],
        )
        recompute_balance(account)
        touch_versioned(account)

    return ok_object(statement_credit_view(rec))
