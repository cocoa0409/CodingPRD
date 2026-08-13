"""Exit request endpoints: value, approve, settle, reject, withdraw (PRD 3.9).
Also depreciation schedule reads."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import (
    EARLY_EXIT_BP,
    MARKET_VALUE_BP,
    MIN_HOLD_YEARS,
    exit_view,
    schedule_view,
    touch,
)
from util import body, paginate_sorted, round_half_up_cents

bp = Blueprint("exits", __name__)


def _get_exit(xid):
    x = db.exit_requests.get(xid)
    if not x:
        raise ApiError("ERR_NOT_FOUND", 404, "Exit request not found")
    return x


# ---------------------------------------------------------------------------
# Depreciation schedules (read-only)
# ---------------------------------------------------------------------------

@bp.route("/depreciation-schedules/<did>", methods=["GET"])
def get_schedule(did):
    require_roles(*ALL_ROLES)
    d = db.depreciation_schedules.get(did)
    if not d:
        raise ApiError("ERR_NOT_FOUND", 404, "Depreciation schedule not found")
    return ok(schedule_view(d))


@bp.route("/depreciation-schedules", methods=["GET"])
def list_schedules():
    require_roles(*ALL_ROLES)
    share_id = request.args.get("share_id")
    items = list(db.depreciation_schedules.values())
    if share_id is not None:
        items = [d for d in items if d["share_id"] == share_id]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([schedule_view(d) for d in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Exit requests
# ---------------------------------------------------------------------------

@bp.route("/exit-requests/<xid>", methods=["GET"])
def get_exit(xid):
    require_roles(*ALL_ROLES)
    return ok(exit_view(_get_exit(xid)))


@bp.route("/exit-requests", methods=["GET"])
def list_exits():
    require_roles(*ALL_ROLES)
    share_id = request.args.get("share_id")
    status = request.args.get("exit_status")
    items = list(db.exit_requests.values())
    if share_id is not None:
        items = [x for x in items if x["share_id"] == share_id]
    if status is not None:
        items = [x for x in items if x["exit_status"] == status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([exit_view(x) for x in page], total, limit, offset)


@bp.route("/exit-requests/<xid>/value", methods=["POST"])
def value_exit(xid):
    user_id, role = require_roles("FinanceOps")
    x = _get_exit(xid)
    if x["exit_status"] in ("SETTLED", "REJECTED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Exit request is already {x['exit_status']}")
    if x["exit_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Exit request must be SUBMITTED to value")
    share = db.shares[x["share_id"]]
    # Referential: no CONFIRMED bookings may remain on the share.
    if any(
        b["share_id"] == share["id"] and b["booking_status"] == "CONFIRMED"
        for b in db.bookings.values()
    ):
        raise ApiError("ERR_REFERENTIAL_CONFLICT", 409,
                       "Share still has CONFIRMED bookings")

    market_value = round_half_up_cents(
        Decimal(share["purchase_price_cents"])
        * Decimal(MARKET_VALUE_BP) / Decimal(10000)
    )
    years_held = share["contract_year_index"]
    if years_held >= MIN_HOLD_YEARS:
        penalty = 0
    else:
        penalty = round_half_up_cents(
            Decimal(market_value)
            * Decimal(EARLY_EXIT_BP)
            * Decimal(MIN_HOLD_YEARS - years_held)
            / Decimal(10000 * MIN_HOLD_YEARS)
        )
    x["buyout_amount_cents"] = market_value - penalty
    x["early_exit_penalty_cents"] = penalty
    x["exit_status"] = "VALUED"
    x["_valued_by"] = user_id
    touch(x)
    return ok(exit_view(x))


@bp.route("/exit-requests/<xid>/approve", methods=["POST"])
def approve_exit(xid):
    user_id, role = require_roles("FinanceOps")
    x = _get_exit(xid)
    if x["exit_status"] in ("SETTLED", "REJECTED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Exit request is already {x['exit_status']}")
    if x["exit_status"] == "SUBMITTED":
        raise ApiError("ERR_EXIT_NOT_VALUED", 409,
                       "Exit request must be valued before approval")
    if x["exit_status"] != "VALUED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Exit request must be VALUED to approve")
    if x.get("_valued_by") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Approver must differ from the valuer")
    x["exit_status"] = "APPROVED"
    touch(x)
    return ok(exit_view(x))


@bp.route("/exit-requests/<xid>/settle", methods=["POST"])
def settle_exit(xid):
    require_roles("FinanceOps")
    x = _get_exit(xid)
    if x["exit_status"] in ("SETTLED", "REJECTED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Exit request is already {x['exit_status']}")
    if x["exit_status"] in ("SUBMITTED",):
        raise ApiError("ERR_EXIT_NOT_VALUED", 409,
                       "Exit request must be valued before settlement")
    if x["exit_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Exit request must be APPROVED to settle")
    share = db.shares[x["share_id"]]
    owner = db.owners[share["owner_id"]]

    # Outstanding invoice balance over open-ish statuses, as of settle clock.
    outstanding_statuses = ("OPEN", "ISSUED", "PAST_DUE", "DISPUTED")
    outstanding = 0
    for inv in db.invoices.values():
        if inv["owner_id"] == owner["id"] and inv["invoice_status"] in outstanding_statuses:
            outstanding += inv["total_due_cents"]
            # Force-close: netted into the settlement.
            inv["invoice_status"] = "PAID"
            touch(inv)

    # buyout_amount_cents is already market_value - penalty (per scaffold's
    # exit_buyout_formula); settlement nets outstanding invoices and the
    # deposit against it.
    settlement = (
        x["buyout_amount_cents"]
        - outstanding
        + owner["deposit_balance_cents"]
    )
    x["settlement_cents"] = settlement
    x["exit_status"] = "SETTLED"
    touch(x)

    owner["deposit_balance_cents"] = 0
    # Share IN_EXIT -> CLOSED
    share["share_status"] = "CLOSED"
    touch(share)
    # Owner EXITED when final non-CLOSED share closes.
    remaining = [
        s for s in db.shares.values()
        if s["owner_id"] == owner["id"] and s["share_status"] != "CLOSED"
    ]
    if not remaining and owner["owner_standing"] != "EXITED":
        owner["owner_standing"] = "EXITED"
    touch(owner)
    return ok(exit_view(x))


@bp.route("/exit-requests/<xid>/reject", methods=["POST"])
def reject_exit(xid):
    require_roles("FinanceOps")
    x = _get_exit(xid)
    if x["exit_status"] in ("SETTLED", "REJECTED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Exit request is already {x['exit_status']}")
    if x["exit_status"] not in ("SUBMITTED", "VALUED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Exit request must be SUBMITTED or VALUED to reject")
    x["exit_status"] = "REJECTED"
    touch(x)
    share = db.shares[x["share_id"]]
    if share["share_status"] == "IN_EXIT":
        share["share_status"] = "ACTIVE"
        touch(share)
    return ok(exit_view(x))


@bp.route("/exit-requests/<xid>/withdraw", methods=["POST"])
def withdraw_exit(xid):
    user_id, role = require_roles("Owner")
    x = _get_exit(xid)
    share = db.shares[x["share_id"]]
    if share["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the share's owner may withdraw the exit")
    if x["exit_status"] in ("SETTLED", "REJECTED", "WITHDRAWN"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Exit request is already {x['exit_status']}")
    if x["exit_status"] not in ("SUBMITTED", "VALUED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Exit request must be SUBMITTED or VALUED to withdraw")
    x["exit_status"] = "WITHDRAWN"
    touch(x)
    if share["share_status"] == "IN_EXIT":
        share["share_status"] = "ACTIVE"
        touch(share)
    return ok(exit_view(x))
