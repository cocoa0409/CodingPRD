"""PointsTransfer routes."""
from __future__ import annotations

from flask import Blueprint, g, request

from auth import is_cardholder, require_roles
from constants import ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN
from errors import err
from response import ok_object
from serializers import points_transfer_view
from services.account import ownership_check
from services.ledger import append_entry, recompute_balance
from services.touch import touch_versioned
from store import store
from utils import fmt_iso, get_body, require_int, require_str

bp = Blueprint("points_transfers", __name__)


@bp.post("/points-transfers")
@require_roles(ROLE_CARDHOLDER)
def post_transfer():
    body = get_body(request)
    account_id = require_str(body, "account_id")
    partner_id = require_str(body, "partner_id")
    requested_units = require_int(body, "requested_partner_units")

    # Body FK existence (priority 4)
    account = store.accounts.get(account_id)
    if account is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "account_id does not resolve")
    partner = store.transfer_partners.get(partner_id)
    if partner is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "partner_id does not resolve")

    # Ownership (priority 5)
    ownership_check(account, g.user_id)

    # State: account ACTIVE (priority 6)
    if account["lifecycle_state"] == "CLOSED":
        raise err("ERR_ACCOUNT_CLOSED", "Account is closed")
    if account["lifecycle_state"] != "ACTIVE":
        raise err("ERR_ACCOUNT_CLOSED", f"Account not ACTIVE: {account['lifecycle_state']}")

    # Business: increment shape (priority 11). Per the scaffold's validation
    # ordering, increment validity is checked BEFORE partner.is_active.
    if requested_units <= 0:
        raise err(
            "ERR_INVALID_TRANSFER_INCREMENT",
            "requested_partner_units must be > 0",
        )
    if requested_units % int(partner["min_transfer_increment"]) != 0:
        raise err(
            "ERR_INVALID_TRANSFER_INCREMENT",
            "requested_partner_units must be a multiple of min_transfer_increment",
        )

    # Business: partner active (priority 12)
    if not partner["is_active"]:
        raise err("ERR_PARTNER_INACTIVE", "Transfer partner is inactive")

    points_debited = requested_units * int(partner["conversion_ratio_points_per_unit"])

    with store.lock:
        # Fiscal: sufficient balance (priority 15)
        if points_debited > int(account["points_balance"]):
            raise err(
                "ERR_INSUFFICIENT_POINTS",
                "points_debited exceeds account points_balance",
            )

        now = store.now()
        iso = fmt_iso(now)

        tid = store.new_id()
        rec = {
            "id": tid,
            "account_id": account_id,
            "partner_id": partner_id,
            "requested_partner_units": requested_units,
            "points_debited": points_debited,
            "status": "PENDING",
            "initiated_at": iso,
            "completed_at": None,
            "created_at": iso,
        }
        store.points_transfers[tid] = rec

        append_entry(
            account_id=account_id,
            entry_type="TRANSFER_DEBIT",
            delta_points=-points_debited,
            source_entity_type="PointsTransfer",
            source_entity_id=tid,
        )
        recompute_balance(account)
        account["last_qualifying_activity_at"] = iso
        touch_versioned(account)

    return ok_object(points_transfer_view(rec), status=201)


def _get_transfer_or_404(transfer_id: str) -> dict:
    t = store.points_transfers.get(transfer_id)
    if t is None:
        raise err("ERR_NOT_FOUND", "PointsTransfer not found")
    return t


@bp.post("/points-transfers/<transfer_id>/confirm")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_confirm(transfer_id: str):
    t = _get_transfer_or_404(transfer_id)
    account = store.accounts.get(t["account_id"])
    if account is None:
        raise err("ERR_NOT_FOUND", "Account not found")

    with store.lock:
        if account["lifecycle_state"] != "ACTIVE":
            # The scaffold says "Account.lifecycle_state == ACTIVE" — if CLOSED
            # raise ACCOUNT_CLOSED, otherwise INVALID_STATE.
            if account["lifecycle_state"] == "CLOSED":
                raise err("ERR_ACCOUNT_CLOSED", "Account is closed")
            raise err("ERR_INVALID_STATE", "Account is not ACTIVE")
        if t["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", f"Transfer status is {t['status']}, not PENDING")

        now_iso = store.now_iso()
        t["status"] = "COMPLETED"
        t["completed_at"] = now_iso
        account["last_qualifying_activity_at"] = now_iso
        touch_versioned(account)

    return ok_object(points_transfer_view(t))


@bp.post("/points-transfers/<transfer_id>/reverse")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def post_reverse(transfer_id: str):
    t = _get_transfer_or_404(transfer_id)
    account = store.accounts.get(t["account_id"])
    if account is None:
        raise err("ERR_NOT_FOUND", "Account not found")

    if is_cardholder():
        ownership_check(account, g.user_id)

    with store.lock:
        if t["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", f"Transfer status is {t['status']}, not PENDING")
        t["status"] = "REVERSED"
        append_entry(
            account_id=account["id"],
            entry_type="TRANSFER_REVERSE",
            delta_points=+int(t["points_debited"]),
            source_entity_type="PointsTransfer",
            source_entity_id=t["id"],
        )
        recompute_balance(account)
        touch_versioned(account)

    return ok_object(points_transfer_view(t))
