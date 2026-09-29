"""The transfer pipeline: submission, screening, holds, rejection, reversal (PRD 3.8)."""

from flask import Blueprint, request

from auth import caller_id, endpoint, require_ownership, require_sod
from core import (
    add_hours,
    clock_dt,
    clock_iso,
    fmt_dt,
    must_find,
    new_row,
    ok,
    parse_dt,
    store,
    touch,
)
from errors import ApiError, invalid
from rhelp import (
    require_account_open,
    require_agreement_active,
    require_available_points,
    require_not_locked,
    require_state,
)
from shapes import body, req_enum, req_int, req_string
from svc_ledger import append_entry, refresh_account
from svc_posture import hold_transfer
from svc_transfer import pin_bonus_event
from views import ADMIN, ANALYST, APPROVER, CARDHOLDER, OPS_CARD, listing, plain

bp = Blueprint("transfers", __name__)

HOLD_REASONS = ("ATO_SUSPECTED", "INSUFFICIENT_BALANCE_AFTER_CLAWBACK", "MANUAL_REVIEW")


@bp.post("/transfer-requests")
@endpoint(CARDHOLDER)
def create_transfer():
    data = body()
    account_id = data.get("account_id")
    if isinstance(account_id, str):
        require_ownership(account_id)
    if not isinstance(account_id, str) or account_id.strip() == "":
        raise invalid("'account_id' is required")
    account = must_find("accounts", account_id)
    agreement_id = data.get("partner_agreement_id")
    if not isinstance(agreement_id, str) or agreement_id.strip() == "":
        raise invalid("'partner_agreement_id' is required")
    agreement = must_find("agreements", agreement_id)

    points_out = req_int(data, "points_out", minimum=1)
    expected_account_version = req_int(data, "expected_account_version", minimum=0)
    if expected_account_version != account["version"]:
        raise ApiError(
            "ERR_STALE_ACCOUNT_VERSION",
            "Account '%s' is at version %d." % (account_id, account["version"]),
        )

    require_account_open(account)
    require_not_locked(account)
    require_agreement_active(agreement)

    if points_out < agreement["min_transfer_points"]:
        raise ApiError(
            "ERR_BELOW_MIN_TRANSFER",
            "points_out is below the agreement minimum of %d."
            % agreement["min_transfer_points"],
        )
    if points_out % agreement["transfer_increment_points"] != 0:
        raise ApiError(
            "ERR_TRANSFER_INCREMENT_INVALID",
            "points_out must be an exact multiple of %d."
            % agreement["transfer_increment_points"],
        )
    require_available_points(account, points_out)

    event = pin_bonus_event(agreement_id, clock_dt())
    row = store(
        "transfer_requests",
        new_row(
            "transfer_requests",
            {
                "account_id": account_id,
                "partner_agreement_id": agreement_id,
                "bonus_event_id": event["id"] if event is not None else None,
                "points_out": points_out,
                "ratio_points_out_applied": None,
                "ratio_partner_units_in_applied": None,
                "base_units": 0,
                "bonus_units": 0,
                "partner_units_credited": 0,
                "status": "SUBMITTED",
                "hold_reason": None,
                "held_by_user_id": None,
                "released_by_user_id": None,
                "screening_cleared_at": None,
                "scheduled_post_at": None,
                "completed_at": None,
                "reversed_at": None,
                "resolution_reason": None,
            },
        ),
    )
    append_entry(
        account,
        "TRANSFER_DEBIT",
        -points_out,
        "TRANSFER_REQUEST",
        row["id"],
        "Points debited on transfer submission",
    )
    refresh_account(account)
    touch(account)
    return ok(plain(row), 201)


@bp.get("/transfer-requests/<transfer_id>")
@endpoint(OPS_CARD)
def read_transfer(transfer_id):
    return ok(plain(must_find("transfer_requests", transfer_id)))


@bp.get("/transfer-requests")
@endpoint(OPS_CARD)
def list_transfers():
    args = request.args
    filters = {
        "account_id": args.get("account_id"),
        "partner_agreement_id": args.get("partner_agreement_id"),
        "bonus_event_id": args.get("bonus_event_id"),
        "status": args.get("status"),
        "hold_reason": args.get("hold_reason"),
    }
    return listing("transfer_requests", args, filters)


@bp.post("/transfer-requests/<transfer_id>/hold")
@endpoint(ANALYST)
def hold(transfer_id):
    transfer = must_find("transfer_requests", transfer_id)
    account = must_find("accounts", transfer["account_id"])
    hold_reason = req_enum(body(), "hold_reason", HOLD_REASONS)
    require_state(transfer, ("SUBMITTED", "QUEUED"))
    hold_transfer(account, transfer, hold_reason, caller_id())
    return ok(plain(transfer))


@bp.post("/transfer-requests/<transfer_id>/release")
@endpoint(APPROVER)
def release(transfer_id):
    transfer = must_find("transfer_requests", transfer_id)
    require_sod(transfer["held_by_user_id"])
    account = must_find("accounts", transfer["account_id"])
    require_state(transfer, ("HELD",))
    require_not_locked(account)
    transfer["status"] = "SUBMITTED"
    transfer["released_by_user_id"] = caller_id()
    transfer["scheduled_post_at"] = None
    touch(transfer)
    return ok(plain(transfer))


@bp.post("/transfer-requests/<transfer_id>/clear-screening")
@endpoint(ANALYST)
def clear_screening(transfer_id):
    transfer = must_find("transfer_requests", transfer_id)
    account = must_find("accounts", transfer["account_id"])
    agreement = must_find("agreements", transfer["partner_agreement_id"])
    require_state(transfer, ("SUBMITTED",))
    require_not_locked(account)
    require_agreement_active(agreement)
    cleared = clock_dt()
    transfer["status"] = "QUEUED"
    transfer["screening_cleared_at"] = fmt_dt(cleared)
    transfer["scheduled_post_at"] = fmt_dt(
        add_hours(cleared, agreement["transfer_latency_hours"])
    )
    touch(transfer)
    return ok(plain(transfer))


@bp.post("/transfer-requests/<transfer_id>/reject")
@endpoint(ANALYST)
def reject(transfer_id):
    transfer = must_find("transfer_requests", transfer_id)
    account = must_find("accounts", transfer["account_id"])
    resolution_reason = req_string(body(), "resolution_reason")
    require_state(transfer, ("HELD",))
    transfer["status"] = "REJECTED"
    transfer["resolution_reason"] = resolution_reason
    touch(transfer)
    append_entry(
        account,
        "TRANSFER_REVERSAL",
        transfer["points_out"],
        "TRANSFER_REQUEST",
        transfer["id"],
        "Points returned on transfer rejection",
    )
    refresh_account(account)
    touch(account)
    return ok(plain(transfer))


@bp.post("/transfer-requests/<transfer_id>/reverse")
@endpoint(ADMIN)
def reverse(transfer_id):
    transfer = must_find("transfer_requests", transfer_id)
    account = must_find("accounts", transfer["account_id"])
    agreement = must_find("agreements", transfer["partner_agreement_id"])
    resolution_reason = req_string(body(), "resolution_reason")
    require_state(transfer, ("COMPLETED",))
    deadline = add_hours(parse_dt(transfer["completed_at"]), agreement["reversal_window_hours"])
    if clock_dt() > deadline:
        raise ApiError(
            "ERR_TRANSFER_REVERSAL_WINDOW_EXPIRED",
            "The reversal window for transfer '%s' has expired." % transfer_id,
        )
    transfer["status"] = "REVERSED"
    transfer["reversed_at"] = clock_iso()
    transfer["resolution_reason"] = resolution_reason
    transfer["partner_units_credited"] = 0
    transfer["base_units"] = 0
    transfer["bonus_units"] = 0
    touch(transfer)
    append_entry(
        account,
        "TRANSFER_REVERSAL",
        transfer["points_out"],
        "TRANSFER_REQUEST",
        transfer["id"],
        "Points returned on transfer reversal",
    )
    refresh_account(account)
    touch(account)
    return ok(plain(transfer))
