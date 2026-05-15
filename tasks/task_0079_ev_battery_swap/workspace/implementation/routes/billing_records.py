"""BillingRecord routes — list, get, pay, mark-failed, refund."""

from flask import Blueprint, g, request

from db import DB
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_REFUND_EXCEEDS_PAID,
    raise_error,
)
from middleware import auth_required
from response import list_response, success_response
from services.common import (
    bump_version,
    check_occ,
    get_body,
    get_or_404,
    get_pagination,
    paginate,
    require_int,
    sort_by_created_at_asc,
)


bp = Blueprint("billing_records", __name__, url_prefix="/swap-stations")


PAYMENT_STATUSES = {"PENDING", "PAID", "REFUNDED", "FAILED"}


@bp.route("/billing-records", methods=["GET"])
@auth_required(["Member", "PlatformAdmin"])
def list_billing_records():
    limit, offset = get_pagination()
    member_id = request.args.get("member_id")
    payment_status = request.args.get("payment_status")
    if payment_status is not None and payment_status not in PAYMENT_STATUSES:
        raise_error(ERR_INVALID_INPUT, "Unknown payment_status filter")

    items = list(DB["billing_records"].values())
    if g.user_role == "Member":
        items = [r for r in items if r.get("member_id") == g.user_id]
    if member_id is not None:
        items = [r for r in items if r.get("member_id") == member_id]
    if payment_status is not None:
        items = [r for r in items if r.get("payment_status") == payment_status]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate(items, limit, offset)
    return list_response(sliced, total, limit, offset)


@bp.route("/billing-records/<record_id>", methods=["GET"])
@auth_required(["Member", "PlatformAdmin"])
def get_billing_record(record_id):
    row = get_or_404("billing_records", record_id)
    if g.user_role == "Member" and row.get("member_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Member can only view own billing records")
    return success_response(row)


@bp.route("/billing-records/<record_id>/pay", methods=["POST"])
@auth_required(["Member"])
def pay_billing(record_id):
    row = get_or_404("billing_records", record_id)
    body = get_body()
    check_occ(row, body)

    if row.get("member_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Member can only pay own billing record")
    if row.get("payment_status") != "PENDING":
        raise_error(ERR_INVALID_STATE, "BillingRecord is not PENDING")

    row["payment_status"] = "PAID"
    bump_version(row)
    return success_response(row)


@bp.route("/billing-records/<record_id>/mark-failed", methods=["POST"])
@auth_required(["PlatformAdmin"])
def mark_failed(record_id):
    row = get_or_404("billing_records", record_id)
    body = get_body()
    check_occ(row, body)

    if row.get("payment_status") != "PENDING":
        raise_error(ERR_INVALID_STATE, "BillingRecord is not PENDING")

    row["payment_status"] = "FAILED"
    bump_version(row)
    return success_response(row)


@bp.route("/billing-records/<record_id>/refund", methods=["POST"])
@auth_required(["PlatformAdmin"])
def refund(record_id):
    row = get_or_404("billing_records", record_id)
    body = get_body()
    check_occ(row, body)

    if row.get("payment_status") != "PAID":
        raise_error(ERR_INVALID_STATE, "BillingRecord must be PAID before refund")

    refund_cents = require_int(body, "refund_cents")
    amount_due = int(row.get("amount_due_cents", 0))
    if refund_cents <= 0 or refund_cents > amount_due:
        raise_error(ERR_REFUND_EXCEEDS_PAID,
                    "refund_cents must be in (0, amount_due_cents]")

    row["refund_cents"] = int(refund_cents)
    row["payment_status"] = "REFUNDED"
    bump_version(row)

    # Full-refund compensating action — restore subscription credit if one
    # was applied at swap-complete.
    if refund_cents == amount_due and int(row.get("subscription_deduction_cents", 0)) > 0:
        member = DB["members"].get(row.get("member_id"))
        if member is not None:
            member["subscription_swaps_remaining"] = int(
                member.get("subscription_swaps_remaining", 0)
            ) + 1
            bump_version(member)

    return success_response(row)
