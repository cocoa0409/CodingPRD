"""Payment endpoints: post, reverse, with ledger reconciliation & auto-close."""
from flask import Blueprint, request

from clock import clock, format_iso8601
from db import db, stamp_create, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_ARRANGEMENT_NOT_ACCEPTED,
)
from middleware import require_roles
from response import object_response, array_response
from serializers import serialize_payment
from pagination import paginate
from validation import get_body, require_str, require_int, invalid
from services.transitions import (
    recompute_account_financials, maybe_auto_close_paid, try_fulfill_arrangements,
)

bp = Blueprint("payments", __name__)


@bp.route("/payments", methods=["POST"])
@require_roles("Collector")
def post_payment():
    body = get_body()
    account_id = require_str(body, "account_id")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    # arrangement_id is an optional FK; existence checked left-to-right.
    arrangement_id = body.get("arrangement_id")
    arrangement = None
    if arrangement_id is not None:
        if not isinstance(arrangement_id, str):
            invalid("arrangement_id must be a string")
        arrangement = db.arrangements.get(arrangement_id)
        if arrangement is None:
            raise ApiError(*ERR_NOT_FOUND, message="Arrangement not found")
    amount = require_int(body, "amount_cents")
    if amount <= 0:
        invalid("amount_cents must be greater than zero")
    # Referential guardrail: arrangement must be ACCEPTED on the same account.
    if arrangement is not None:
        if arrangement["status"] != "ACCEPTED" or arrangement["account_id"] != account_id:
            raise ApiError(*ERR_ARRANGEMENT_NOT_ACCEPTED,
                           message="arrangement_id must reference an ACCEPTED arrangement on the same account")

    p = stamp_create({
        "account_id": account_id,
        "arrangement_id": arrangement_id,
        "amount_cents": amount,
        "posted_at": format_iso8601(clock.now),
        "status": "POSTED",
    })
    db.payments[p["id"]] = p
    # Ledger + derived recompute, version bump, fulfillment, auto-close.
    recompute_account_financials(account)
    touch(account)  # posting increments account.version by 1
    try_fulfill_arrangements(account)
    maybe_auto_close_paid(account)
    return object_response(serialize_payment(p), status=201)


@bp.route("/payments/<pid>", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "System")
def get_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise ApiError(*ERR_NOT_FOUND, message="Payment not found")
    return object_response(serialize_payment(p), status=200)


@bp.route("/payments", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "System")
def list_payments():
    items = list(db.payments.values())
    account_id = request.args.get("account_id")
    arrangement_id = request.args.get("arrangement_id")
    if account_id:
        items = [p for p in items if p["account_id"] == account_id]
    if arrangement_id:
        items = [p for p in items if p.get("arrangement_id") == arrangement_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_payment(p) for p in page], limit, offset, total)


@bp.route("/payments/<pid>/reverse", methods=["POST"])
@require_roles("Collector")
def reverse_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise ApiError(*ERR_NOT_FOUND, message="Payment not found")
    body = get_body()
    expected = require_int(body, "expected_account_version")
    account = db.accounts.get(p["account_id"])
    if account is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    # OCC (412) then state. Payment must be POSTED for the transition to be defined.
    if expected != account["version"]:
        raise ApiError(*ERR_STALE_VERSION, message="expected_account_version does not match")
    if account["work_status"] in ("RECALLED", "CLOSED_PAID", "CLOSED_UNCOLLECTIBLE"):
        raise ApiError(*ERR_INVALID_STATE, message="Account is not in a reversible state")
    if p["status"] != "POSTED":
        raise ApiError(*ERR_INVALID_STATE, message="Only a POSTED payment may be reversed")
    p["status"] = "REVERSED"
    touch(p)
    recompute_account_financials(account)
    touch(account)  # reversal increments account.version by 1
    return object_response(serialize_payment(p), status=200)
